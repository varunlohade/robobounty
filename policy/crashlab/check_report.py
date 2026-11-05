"""Recomputes report.json counts directly from the run folders: check_report.py <batch dir>. Exit 1 on any mismatch."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report as report_module

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    batch = Path(ap.parse_args().batch).resolve()
    report = json.loads((batch / "report.json").read_text())
    errors = []

    def same(label, got, want):
        print(f"{'ok ' if got == want else 'BAD'} {label}: report={got} folders={want}")
        if got != want:
            errors.append(label)

    results = {p.parent.name: json.loads(p.read_text()) for p in batch.glob("*/result.json")}
    scored = passed = control_n = control_pass = varied_n = varied_pass = 0
    excluded = {}
    failed = set()
    for name, r in results.items():
        if r["status"] in ("completed", "invalid_action"):
            scene = json.loads((batch / name / "scene.json").read_text())
            digest = hashlib.sha256(json.dumps(scene, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if digest != r["scene_sha256"]:
                errors.append(f"{name}: scene hash")
            last = (batch / name / "actions.jsonl").read_text().splitlines()[-1]
            if json.loads(last)["h"] != r["action_chain_head"]:
                errors.append(f"{name}: action chain head")
            ok = r["success"] is True
            scored += 1
            passed += ok
            if not (scene["objects"] or scene["colours"] or scene["clutter"] or scene["light"] != 1.0):
                control_n += 1
                control_pass += ok
            else:
                varied_n += 1
                varied_pass += ok
            if not ok:
                failed.add(name)
        else:
            excluded[r["status"]] = excluded.get(r["status"], 0) + 1

    counts = report["counts"]
    same("scenes_run", counts["scenes_run"], scored)
    same("scenes_passed", counts["scenes_passed"], passed)
    same("control", (report["control"]["passed"], report["control"]["scored"]), (control_pass, control_n))
    same("varied", (report["score"]["passed"], report["score"]["scored"]), (varied_pass, varied_n))
    same("excluded", {k: v for k, v in counts["excluded"].items() if v}, excluded)
    same("scenes_in_batch", counts["scenes_in_batch"], len(list((batch / "scenes").glob("*.json")))
         if (batch / "scenes").exists() else counts["scenes_in_batch"])
    same("run_dirs_vs_batch", counts["scenes_in_batch"] - counts["scenes_unfinished"], len(results))

    library = {run["name"] for e in report["failures"] for run in e["runs"]}
    same("failure_library_runs", sorted(library), sorted(failed))
    same("fingerprints_unique", len({e["fingerprint"] for e in report["failures"]}), len(report["failures"]))
    same("task_rows", sum(t["control"]["scored"] + t["varied"]["scored"] for t in report["by_task"].values()), scored)
    for e in report["failures"]:
        for run in e["runs"]:
            if run["video"] and not (REPO_ROOT / run["video"]).exists():
                errors.append(f"missing video {run['video']}")
            status = "not_run"
            replay = REPO_ROOT / run["run_dir"] / "replay.json"
            if replay.exists():
                status = "match" if json.loads(replay.read_text()).get("match") else "mismatch"
            if status != run["replay_status"]:
                errors.append(f"stale replay status in report: {run['name']}")

    logged = [json.loads(line)["name"] for line in (batch / "results.jsonl").read_text().splitlines()]
    same("results_log_names", sorted(set(logged)), sorted(results))
    same("results_log_no_duplicates", len(logged), len(set(logged)))

    base = {"schema": 1, "task_id": 1, "init_state": 3, "seed": 1, "light": 1.0, "colours": [], "clutter": [],
            "objects": [{"object": 0, "dx": 0.041, "dy": 0.0, "dyaw": 0.0}]}
    near = {**base, "seed": 2, "objects": [{"object": 0, "dx": 0.042, "dy": 0.0, "dyaw": 0.0}]}
    far = {**base, "objects": [{"object": 0, "dx": -0.04, "dy": 0.0, "dyaw": 0.0}]}
    same("near_identical_seed_collapses", report_module.scene_bucket(base), report_module.scene_bucket(near))
    if report_module.scene_bucket(base) == report_module.scene_bucket(far):
        errors.append("a far scene shares a bucket")
    same("wilson_known_values", [round(x, 3) for x in report_module.wilson(5, 10)], [0.237, 0.763])

    print("CHECK FAILED: " + "; ".join(errors) if errors else "CHECK PASSED")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
