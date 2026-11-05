"""Builds report.json from a batch's run folders: report.py <batch dir>. The folders are the only source of results."""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene as scene_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
Z_95 = 1.959964
XY_BUCKET_M, YAW_BUCKET_RAD, LIGHT_BUCKET = 0.02, math.pi / 4, 0.25
CLUTTER_XY_BUCKET_M, CLUTTER_SIZE_BUCKET_M, RGB_LEVELS = 0.05, 0.01, 2
SLIDE_FLAG_M = 0.015  # sim.MAX_XY_DRIFT_M. Not imported, because sim.py loads MuJoCo
TARGET_NAME = scene_schema.OBJECTS[scene_schema.TARGET_OBJECT]

KNOWN_SCENE_PROBLEMS = {
    5: "Stock problem: the bowl sits on the ramekin and slides while settling, with no edits "
       "(3.7 cm measured on an earlier run). Results on this task are flagged, and the model did not cause the slide.",
}
EXCLUDED_STATUSES = ("scene_invalid", "excluded_target_recolour", "runner_error", "rejected")
SCORED_STATUSES = ("completed", "invalid_action")

METHOD = {
    "score": "Goal reached / scored scenes, for the varied group. The control group gets its own line.",
    "scored_scene": "The policy ran to success or the 280-step limit, or it produced a non-finite action (a failure). "
                    "Excluded and counted: scenes that fail settling, target recolours, rejected files, runner errors.",
    "interval": "95% Wilson score interval, z=1.959964, no continuity correction.",
    "difference": "Varied rate minus control rate. Interval: Newcombe method 10 (hybrid score, unpaired). "
                  "Pairs share task, init state and seed. paired.p is a two-sided exact sign test on discordant pairs.",
    "by_variation": "A scene usually holds several variation types, so it counts under each. "
                    "These rows overlap and do not show cause.",
    "fingerprint": "sha256 of [model id@revision, task, scene bucket, reason]. The bucket drops the seed and rounds "
                   "edits: position 2 cm, yaw 45 deg, light 0.25, clutter position 5 cm, clutter size 1 cm, "
                   "rgb 3 levels per channel. Values near a rounding edge can still split into two entries.",
}
CANNOT_CLAIM = [
    "Simulator only: LIBERO on MuJoCo. It says nothing direct about a real robot.",
    "Small sample: see the interval. Task and variation rows are too small to rank anything.",
    "One model at one pinned revision. It does not rank SmolVLA against any other policy.",
    "One rollout per scene. A failure has not passed the 3-of-3 jittered re-run in the threat model, risk 9.",
    "Replay proof covers this machine and this MuJoCo version only (threat model, risk 5).",
    "Scenes use stock init states and a fixed generator seed, so they are known in advance (threat model, risk 4). "
    "This is a baseline measurement and cannot support a bounty payout.",
    "A target or distractor move can weaken a relational phrase such as 'next to the ramekin'. Some varied failures "
    "may come from a less accurate instruction, not from the policy.",
]


def wilson(passed, n):
    if n == 0:
        return None
    p = passed / n
    z2 = Z_95**2
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n**2)) / (1 + z2 / n)
    # p=0 and p=1 have exact bounds, and rounding must not move them.
    return [0.0 if passed == 0 else max(0.0, centre - half), 1.0 if passed == n else min(1.0, centre + half)]


def rate_block(rows):
    n = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    return {"passed": passed, "scored": n, "rate": passed / n if n else None, "wilson95": wilson(passed, n)}


def newcombe(a, b):
    """Interval for rate(a) - rate(b), from the two Wilson intervals."""
    if not a["scored"] or not b["scored"]:
        return None
    d = a["rate"] - b["rate"]
    (la, ua), (lb, ub) = a["wilson95"], b["wilson95"]
    return [d - math.hypot(a["rate"] - la, ub - b["rate"]), d + math.hypot(ua - a["rate"], b["rate"] - lb)]


def sign_test(x, y):
    n = x + y
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(x, y) + 1)) / 2**n
    return min(1.0, 2 * tail)


def scene_bucket(scene):
    """Same bucket for scenes that differ only by seed or by a small nudge."""
    parts = [f"init={scene['init_state']}"]
    for e in scene["objects"]:
        parts.append(f"obj{e['object']}={round(e['dx'] / XY_BUCKET_M)},{round(e['dy'] / XY_BUCKET_M)},"
                     f"{round(e['dyaw'] / YAW_BUCKET_RAD)}")
    if round(scene["light"] / LIGHT_BUCKET) != round(1.0 / LIGHT_BUCKET):
        parts.append(f"light={round(scene['light'] / LIGHT_BUCKET)}")
    for c in scene["colours"]:
        parts.append(f"col{c['object']}=" + ",".join(str(round(v * RGB_LEVELS)) for v in c["rgb"]))
    for b in sorted(scene["clutter"], key=lambda b: (b["x"], b["y"])):
        parts.append(f"box={round(b['x'] / CLUTTER_XY_BUCKET_M)},{round(b['y'] / CLUTTER_XY_BUCKET_M)},"
                     f"{round(b['half_size'] / CLUTTER_SIZE_BUCKET_M)}")
    return "|".join(parts)


def fingerprint(model, task_id, bucket, reason):
    return hashlib.sha256(json.dumps([model, task_id, bucket, reason], separators=(",", ":")).encode()).hexdigest()


def is_control(scene):
    return not (scene["objects"] or scene["colours"] or scene["clutter"] or scene["light"] != 1.0)


def variation_types(scene):
    moved = {e["object"] for e in scene["objects"] if e["dx"] or e["dy"] or e["dyaw"]}
    found = []
    if scene_schema.TARGET_OBJECT in moved:
        found.append("target_moved")
    if scene_schema.GOAL_OBJECT in moved:
        found.append("goal_moved")
    if moved - {scene_schema.TARGET_OBJECT, scene_schema.GOAL_OBJECT}:
        found.append("distractor_moved")
    if scene["light"] != 1.0:
        found.append("light")
    if scene["colours"]:
        found.append("colour")
    if scene["clutter"]:
        found.append("clutter")
    return found


def rel(path):
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def replay_status(run_dir):
    path = run_dir / "replay.json"
    if not path.exists():
        return "not_run"
    return "match" if json.loads(path.read_text()).get("match") else "mismatch"


def load_runs(batch):
    rows = []
    for path in sorted(batch.glob("*/result.json")):
        run_dir = path.parent
        result = json.loads(path.read_text())
        scene_path = run_dir / "scene.json"
        scene = scene_schema.load(scene_path) if scene_path.exists() else None
        rows.append({"name": run_dir.name, "dir": run_dir, "result": result, "scene": scene,
                     "status": result["status"], "passed": result["success"] is True})
    return rows


def run_flags(row):
    flags = []
    if row["scene"]["task_id"] in KNOWN_SCENE_PROBLEMS:
        flags.append("known_scene_problem")
    if target_stock_slide(row) > SLIDE_FLAG_M:
        flags.append("target_slides_in_stock_scene")
    return flags


def target_stock_slide(row):
    """Metres the target slid with no edits, where this run measured it. A light or colour edit cannot move it."""
    settle = row["result"].get("settle") or {}
    stock = settle.get("stock_xy_drift_m")
    if stock is not None:
        return stock.get(TARGET_NAME, 0.0)
    return settle.get("objects", {}).get(TARGET_NAME, {}).get("xy_drift_m", 0.0)


def single_value(rows, key):
    values = sorted({r["result"][key] for r in rows if key in r["result"]})
    return values[0] if len(values) == 1 else values


def failure_library(scored):
    entries = {}
    for row in scored:
        if row["passed"]:
            continue
        r, s = row["result"], row["scene"]
        model = f"{r['model_id']}@{r['model_revision']}"
        bucket = scene_bucket(s)
        key = fingerprint(model, s["task_id"], bucket, r["reason"])
        video = row["dir"] / "video.mp4"
        run = {
            "name": row["name"], "run_dir": rel(row["dir"]), "video": rel(video) if video.exists() else None,
            "replay_status": replay_status(row["dir"]), "seed": s["seed"], "scene_sha256": r["scene_sha256"],
            "action_chain_head": r.get("action_chain_head"), "steps": r["steps"], "metrics": r.get("metrics"),
        }
        entry = entries.setdefault(key, {
            "fingerprint": key, "model_id": r["model_id"], "model_revision": r["model_revision"],
            "task_id": s["task_id"], "task": r.get("task"), "scene_bucket": bucket, "reason": r["reason"],
            "group": "control" if is_control(s) else "varied", "variations": variation_types(s),
            "flags": run_flags(row), "run_dir": run["run_dir"], "video": run["video"],
            "replay_status": run["replay_status"], "runs": [],
        })
        entry["runs"].append(run)
    return sorted(entries.values(), key=lambda e: (e["reason"], e["task_id"], e["fingerprint"]))


def warnings_for(control, varied, excluded, total):
    out = []
    for name, block in (("control", control), ("varied", varied)):
        if block["scored"] and block["passed"] in (0, block["scored"]):
            out.append(f"Every {name} scene had the same outcome ({block['passed']}/{block['scored']}).")
    if control["scored"] and varied["scored"] and varied["rate"] > control["rate"]:
        out.append("The varied group beat the control group, which suggests noise or easy edits.")
    if total and excluded / total > 0.2:
        out.append(f"{excluded} of {total} scenes were excluded, so the score rests on a selected subset.")
    return out


def build(batch):
    meta = json.loads((batch / "batch_meta.json").read_text())
    rows = load_runs(batch)
    scored = [r for r in rows if r["status"] in SCORED_STATUSES]
    unknown = {r["status"] for r in rows} - set(SCORED_STATUSES) - set(EXCLUDED_STATUSES)
    if unknown:
        raise SystemExit(f"unknown status: {sorted(unknown)}")
    controls = [r for r in scored if is_control(r["scene"])]
    varied = [r for r in scored if not is_control(r["scene"])]
    control_block, varied_block = rate_block(controls), rate_block(varied)

    by_key = {(r["scene"]["task_id"], r["scene"]["init_state"], r["scene"]["seed"]): r for r in controls}
    pairs = {"both_pass": 0, "control_only": 0, "varied_only": 0, "both_fail": 0}
    for r in varied:
        c = by_key.get((r["scene"]["task_id"], r["scene"]["init_state"], r["scene"]["seed"]))
        if c:
            label = {(True, True): "both_pass", (True, False): "control_only",
                     (False, True): "varied_only", (False, False): "both_fail"}[(c["passed"], r["passed"])]
            pairs[label] += 1

    tasks = {}
    for r in scored:
        t = tasks.setdefault(r["scene"]["task_id"], {"task": r["result"].get("task"), "control": [], "varied": []})
        t["control" if is_control(r["scene"]) else "varied"].append(r)
    by_task = {}
    for task_id in sorted(tasks):
        t = tasks[task_id]
        by_task[str(task_id)] = {"task": t["task"], "control": rate_block(t["control"]), "varied": rate_block(t["varied"]),
                                 "known_scene_problem": KNOWN_SCENE_PROBLEMS.get(task_id)}

    types = {}
    for r in varied:
        for v in variation_types(r["scene"]):
            types.setdefault(v, []).append(r)

    reasons = {}
    for r in scored:
        group = "control" if is_control(r["scene"]) else "varied"
        reasons.setdefault(r["result"]["reason"], {"control": 0, "varied": 0})[group] += 1

    flagged = [{"name": r["name"], "task_id": r["scene"]["task_id"], "flags": run_flags(r), "passed": r["passed"],
                "target_stock_slide_m": target_stock_slide(r),
                "group": "control" if is_control(r["scene"]) else "varied"}
               for r in scored if run_flags(r)]
    clean = [r for r in scored if not run_flags(r)]

    excluded = [{"name": r["name"], "status": r["status"], "task_id": r["scene"]["task_id"] if r["scene"] else None,
                 "group": ("control" if is_control(r["scene"]) else "varied") if r["scene"] else None,
                 "detail": (r["result"].get("settle") or {}).get("problems") or r["result"].get("detail")}
                for r in rows if r["status"] in EXCLUDED_STATUSES]
    excluded_counts = {s: sum(1 for e in excluded if e["status"] == s) for s in EXCLUDED_STATUSES}

    sessions = meta["sessions"]
    wall = sum(s["finished"] - s["started"] for s in sessions if "finished" in s)
    versions = meta.get("versions", {})
    return {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "batch": batch.name,
        "complete": len(rows) == len(meta["scenes"]),
        "model": {"id": single_value(rows, "model_id"), "revision": single_value(rows, "model_revision")},
        "simulator": {"suite": "libero_spatial", "mujoco": single_value(rows, "mujoco"),
                      "robosuite": single_value(rows, "robosuite")},
        "device": single_value(rows, "device"),
        "software": versions,
        "generator": meta.get("generator"),
        "method": METHOD,
        "counts": {
            "scenes_in_batch": len(meta["scenes"]), "scenes_unfinished": len(meta["scenes"]) - len(rows),
            "scenes_run": len(scored), "scenes_passed": sum(1 for r in scored if r["passed"]),
            "control_run": len(controls), "varied_run": len(varied),
            "excluded": excluded_counts, "excluded_total": len(excluded),
        },
        "score": varied_block,
        "control": control_block,
        "comparison": {
            "difference_varied_minus_control": (varied_block["rate"] - control_block["rate"])
            if varied and controls else None,
            "newcombe95": newcombe(varied_block, control_block),
            "paired": {**pairs, "pairs": sum(pairs.values()), "p": sign_test(pairs["control_only"], pairs["varied_only"])},
        },
        "without_flagged_scenes": {
            "score": rate_block([r for r in clean if not is_control(r["scene"])]),
            "control": rate_block([r for r in clean if is_control(r["scene"])]),
        },
        "by_variation": {v: rate_block(types[v]) for v in sorted(types)},
        "by_task": by_task,
        "by_reason": dict(sorted(reasons.items())),
        "known_scene_problems": [{"task_id": k, "note": v} for k, v in KNOWN_SCENE_PROBLEMS.items()],
        "flagged_results": flagged,
        "excluded": excluded,
        "failures": failure_library(scored),
        "warnings": warnings_for(control_block, varied_block, len(excluded), len(rows)),
        "cannot_claim": CANNOT_CLAIM,
        "timing": {"wall_s": wall, "sessions": len(sessions), "workers": [s["workers"] for s in sessions],
                   "dropped_to_one_worker": [s["dropped_to_one_worker"] for s in sessions if "dropped_to_one_worker" in s]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    args = ap.parse_args()
    batch = Path(args.batch).resolve()
    report = build(batch)
    (batch / "report.json").write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("complete", "counts", "score", "control", "warnings")}, indent=1))


if __name__ == "__main__":
    main()
