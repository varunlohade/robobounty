"""Runs the lab worlds, judges them from their records, and writes results.json. Exit code 0 means every check held.

Every number is simulated: one upstream policy, one upstream robot model, no calibration.
"""
import hashlib
import json
import subprocess
import sys

import numpy as np

import judge as J
import sim as S
import world as W

OUT = S.HERE / "out"
SEED = 0
BOX = {"name": "box", "x": 2.5, "y": 0.0, "sx": 0.3, "sy": 1.2, "sz": 0.4}
WORLDS = {
    "flat": W.build(),
    "box_in_path": W.build(("add_box", BOX)),
    "low_friction": W.build(("set_ground", {"mu": 0.05})),
    "clear_box": W.build(("add_box", {**BOX, "y": 2.7})),
    "ramp_drop": W.build(("add_ramp", {"name": "ramp", "x": 2.0, "y": 0.0, "length": 2.0, "width": 3.0, "height": 0.3})),
    "ramp_long": W.build(("add_ramp", {"name": "ramp", "x": 1.5, "y": 0.0, "length": 8.0, "width": 8.0, "height": 0.5})),
    "steps": W.build(("add_steps", {"name": "steps", "x": 2.0, "y": 0.0, "width": 3.0, "depth": 0.4, "rise": 0.06, "count": 4})),
}
REFUSALS = [
    ("add_box", {"name": "x", "x": 0.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "blocks_start"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": -1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": True, "sy": 1, "sz": 1}, "bad_args"),
    ("add_box", {"name": "x", "x": float("nan"), "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "X; rm", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "bad_name"),
    ("add_box", {"name": "x", "x": 29.9, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "outside_world"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1, "mesh": "a.obj"}, "bad_args"),
    ("add_ramp", {"name": "x", "x": 2.0, "y": 0.0, "length": 0.2, "width": 1, "height": 1.0}, "too_steep"),
    ("set_ground", {"mu": 9.0}, "out_of_range"),
    ("run_code", {}, "unknown_function"),
]


def nearest_object_m(rec, world):
    gaps = [np.inf]
    for obj in world["objects"]:
        x0, x1, y0, y1 = W.footprint(obj)
        xy = rec["base_q"][:, :2]
        gaps.append(float(np.hypot(np.maximum(np.maximum(x0 - xy[:, 0], xy[:, 0] - x1), 0), np.maximum(np.maximum(y0 - xy[:, 1], xy[:, 1] - y1), 0)).min()))
    return round(min(gaps), 3) if len(gaps) > 1 else None


def metrics(rec):
    contact = rec["feet"]
    force = rec["obstacle_f"]
    speed = rec["foot_v_xy"][contact]
    return {
        "obstacle_peak_N": round(float(force.max()), 1),
        "obstacle_contact_s": round(float((rec["obstacle_n"] > 0).sum() * S.POLICY_DT), 2),
        "foot_slip_mps": round(float(speed.mean()), 3) if speed.size else None,
        "body_on_ground_peak_N": round(float(rec["body_on_ground_f"].max()), 1),
        "mean_ground_N": round(float(rec["ground_f"][50:].mean()), 1),
    }


def state_diff(a, b):
    return {
        "bitwise_equal": bool(all(np.array_equal(a[k], b[k]) for k in ("body_q", "joint_q", "body_qd"))),
        "final_base_m": float(np.linalg.norm(a["base_q"][-1, :3] - b["base_q"][-1, :3])),
        "max_base_m": float(np.linalg.norm(a["base_q"][:, :3] - b["base_q"][:, :3], axis=1).max()),
    }


def _child(name, seed, out):
    code = (
        "import sys; sys.path.insert(0, %r); import json, check_lab as C, sim as S; "
        "S.run(C.WORLDS[%r], seed=%d, out=%r)" % (str(S.HERE), name, seed, str(out))
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, cwd="/tmp")
    return J.load(out)[0]


def main():
    results = {"label": S.code_label(), "note": "Simulated. Not calibrated. Not a real-robot result.", "worlds": {}}
    failures = []

    for fn, args, code in REFUSALS:
        got = W.call(W.new_world(), fn, args)["result"]
        if got != f"cannot_build:{code}":
            failures.append(f"refusal {fn} {args}: {got}")

    results["weight_N"] = round(float(S.build_model(W.new_world())[0].body_mass.numpy().sum()) * 9.81, 1)
    records = {}
    for name, world in WORLDS.items():
        rec, meta = S.run(world, seed=SEED, out=OUT / f"{name}.npz")
        records[name] = rec
        results["worlds"][name] = {
            **J.judge(rec, world["target"]), **metrics(rec), "nearest_object_m": nearest_object_m(rec, world), "shapes": meta["shapes"],
            "peak_base_z_m": round(float(rec["base_q"][:, 2].max()), 3), "rtf": round(meta["rtf"], 2), "peak_nacon": meta["peak_nacon"], "peak_nefc": meta["peak_nefc"],
        }
        print(name, results["worlds"][name], flush=True)

    # MuJoCo takes the larger friction of two equal-priority geoms, so a low mu with priority 0 should change nothing.
    rec, _ = S.run(WORLDS["low_friction"], seed=SEED, surface_priority=0)
    results["low_friction_without_priority"] = {**J.judge(rec, WORLDS["flat"]["target"]), **metrics(rec), "vs_flat": state_diff(rec, records["flat"])}

    results["clear_box_vs_flat"] = state_diff(records["clear_box"], records["flat"])
    results["box_in_path_vs_flat"] = state_diff(records["box_in_path"], records["flat"])

    again, _ = S.run(WORLDS["flat"], seed=SEED)
    other_process = _child("flat", SEED, OUT / "flat_process2.npz")
    other_seed, _ = S.run(WORLDS["flat"], seed=SEED + 1)
    results["determinism"] = {
        "same_seed_same_process": state_diff(records["flat"], again),
        "same_seed_new_process": state_diff(records["flat"], other_process),
        "different_seed": state_diff(records["flat"], other_seed),
        "final_state_sha256": hashlib.sha256(records["flat"]["joint_q"][-1].tobytes()).hexdigest()[:16],
    }
    (OUT / "flat_process2.npz").unlink()

    w = results["worlds"]
    def need(ok, text):
        if not ok:
            failures.append(text)
    need(w["flat"]["verdict"] == "reached", "flat should reach the target")
    need(w["clear_box"]["nearest_object_m"] >= 1.9, "clear_box should stay about 2 m from the box")
    need(w["clear_box"]["shapes"] == w["flat"]["shapes"] + 1, "clear_box should hold one more shape than flat")
    need(abs(w["flat"]["mean_ground_N"] - results["weight_N"]) < 0.15 * results["weight_N"], "mean ground force should be near the weight")
    need(w["box_in_path"]["obstacle_peak_N"] > 0, "box_in_path should record contact")
    need(w["box_in_path"]["verdict"] != "reached", "box_in_path should not reach the target")
    need(w["clear_box"]["obstacle_peak_N"] == 0, "clear_box should record no contact")
    need(w["low_friction"]["foot_slip_mps"] > w["flat"]["foot_slip_mps"], "low_friction should slip more than flat")
    need(results["determinism"]["same_seed_same_process"]["bitwise_equal"], "same seed in one process should match")
    need(results["determinism"]["same_seed_new_process"]["bitwise_equal"], "same seed in a new process should match")
    need(not results["determinism"]["different_seed"]["bitwise_equal"], "a different seed should differ")
    results["failures"] = failures
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({k: v for k, v in results.items() if k != "worlds"}, indent=1))
    print("FAIL" if failures else "PASS", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
