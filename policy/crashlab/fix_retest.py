"""One pre-registered larger test of a saved patch, with no LLM: fix_retest.py <campaign dir> <try dir> <out dir> --seeds A,B --controls N [--procs P]

The plan stays in <out dir>/PLAN.md, committed before this runs. Nothing is applied to controller.py. Writes <out dir>/report.json.
"""
import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fix
import world as W  # before scenarios, which puts this folder and its own world.py first on the path
import scenarios as sc

MAX_PROCS = 3
GUARD_PA = 1500.0


def trace_counts(run_dir):
    """Steps in the clean phase with true pressure below the guard, how many the estimate caught, and whether the run ever retreated."""
    path = Path(run_dir) / "trace.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt") as f:
        t = json.load(f)
    c = {n: i for i, n in enumerate(t["columns"])}
    est = c.get("estimate_pa", c.get("est_fraction"))
    low = [r for r in t["rows"] if r[c["phase"]] == "clean" and r[c["dp"]] < GUARD_PA]
    return {"clean_steps_true_below_guard": len(low), "of_those_estimate_below_guard": sum(r[est] < GUARD_PA for r in low),
            "retreated": any(r[c["phase"]] == "retreat" for r in t["rows"])}


def guard_side(root, side, items):
    rows = [trace_counts(Path(root) / "runs" / "fresh" / side / t) for t, _, _ in items]
    rows = [r for r in rows if r]
    return {"worlds_with_a_retreat": sum(r["retreated"] for r in rows), "clean_steps_true_below_guard": sum(r["clean_steps_true_below_guard"] for r in rows),
            "of_those_estimate_below_guard": sum(r["of_those_estimate_below_guard"] for r in rows)}


def estimator_floor(controller_file, speed):
    """Runs the patched file's own estimator at very high power, its low end."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("controller_retest", controller_file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ctl = m.Controller({"area": {"x0": 0.0, "x1": 2.4, "z0": 135.0, "z1": 138.0}, "anchor": (0.0, -0.3, 160.0), "start_x": 0.0, "start_z": 138.0})
    ctl.speed_est, ctl.current_avg = speed if speed else m.SUCTION_CLEAN, 1e6
    return {"suction_clean": m.SUCTION_CLEAN, "lowest_estimate_pa": round(ctl._pressure_estimate({"battery_volts": 15.0}), 1), "guard_pa": m.LOW_PRESSURE_PA}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("try_dir")
    ap.add_argument("out")
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--controls", type=int, required=True)
    ap.add_argument("--procs", type=int, default=MAX_PROCS)
    a = ap.parse_args()
    out, campaign, try_dir = Path(a.out).resolve(), Path(a.campaign).resolve(), Path(a.try_dir).resolve()
    if (out / "report.json").exists():
        raise SystemExit("this is the only rerun, and it already has a report")
    patched = try_dir / "controller.py"
    meta = json.loads((campaign / "campaign.json").read_text())
    plan = json.loads((Path(meta["scenarios"]) / "scenarios.json").read_text())
    used = {W.world_hash(json.loads(l)["world"]) for l in (campaign / "results.jsonl").read_text().splitlines()}
    fresh = []
    for seed in (int(x) for x in a.seeds.split(",")):
        made = sc.run("fresh worlds from a stored plan", out / f"worlds_{seed}", seed, plan["llm_reply"])
        for w in made["worlds"]:
            world = W.load(out / f"worlds_{seed}" / w["file"])
            if W.world_hash(world) in used:
                raise SystemExit("a fresh world repeats a seen world")
            used.add(W.world_hash(world))
            fresh.append((f"s{seed}_{len(fresh):04d}", world, (seed * 1000 + len(fresh)) % 2**31))
    nominal = W.load(fix.HIGHRISE / "worlds" / "nominal.json")
    sets = {"fresh": fresh, "controls": [(f"control{i:03d}", nominal, 4000 + i) for i in range(a.controls)]}
    procs = min(a.procs, MAX_PROCS)
    rows = {**fix.run_side("A", fix.BASE, out, sets, procs), **fix.run_side("B", patched, out, sets, procs)}
    if not all(r["passed"] for r in rows[("controls", "A")]):
        raise SystemExit("the base controller failed its controls in the sandbox, so the harness or the sim is broken. No result recorded.")
    fresh_ab = fix.paired(rows[("fresh", "A")], rows[("fresh", "B")])
    controls = fix.paired(rows[("controls", "A")], rows[("controls", "B")])
    baseline_fails = fresh_ab["A"]["fail"]
    floor = estimator_floor(patched, None)
    guards = {"A": guard_side(out, "A", fresh), "B": guard_side(out, "B", fresh)}
    risen = [k for k in ("detach", "slip_distance") if fresh_ab["B"]["failures"].get(k, 0) > fresh_ab["A"]["failures"].get(k, 0)]
    sign_pass = fresh_ab["better"] > fresh_ab["worse"] and fresh_ab["sign_test_p_one_sided"] < 0.05
    guard_ok = floor["lowest_estimate_pa"] < floor["guard_pa"]
    report = {"schema": "crashlab.fix_retest.v1", "plan": "PLAN.md", "applied": False, "patch_sha256": hashlib.sha256(patched.read_bytes()).hexdigest(),
              "base_sha256": hashlib.sha256(fix.BASE.read_bytes()).hexdigest(), "seeds": a.seeds, "fresh_worlds": len(fresh), "baseline_failing_worlds": baseline_fails,
              "enough_baseline_failures": baseline_fails >= 30, "fresh": fresh_ab, "controls": controls, "sign_test_pass": sign_pass,
              "controls_all_pass": controls["B"]["pass"] == controls["n"], "detach_or_slip_rose": risen, "blind_point": {"floor": floor, "guard_still_can_fire_in_clean": guard_ok, "fresh_traces": guards},
              "per_world": [{"trial": t[0], "A": x["outcome"], "A_failure": x["failure"], "B": y["outcome"], "B_failure": y["failure"], "replay_ok": y["replay_ok"]}
                            for t, x, y in zip(fresh, rows[("fresh", "A")], rows[("fresh", "B")])],
              "better_by_change": dict(Counter(f"{x['failure'] or x['outcome']} to {y['failure'] or y['outcome']}" for x, y in zip(rows[("fresh", "A")], rows[("fresh", "B")]) if x["outcome"] != y["outcome"] or x["failure"] != y["failure"])),
              "limits": ["In this simulation only. The physics is uncalibrated.", "sandbox-exec is not a VM."]}
    report["conclusion"] = ("helped on the counts and kept the guard" if sign_pass and report["controls_all_pass"] and not risen and guard_ok else
                            "helped on the counts but removed the low-pressure guard in the clean phase" if sign_pass and report["controls_all_pass"] and not risen else "did not help")
    (out / "report.json").write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "per_world"}, indent=1))
    print("CONCLUSION", report["conclusion"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
