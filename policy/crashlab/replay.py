"""Replays stored actions with no policy in the loop and compares every step: replay.py <run dir>"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene as scene_schema

GENESIS = "0" * 64


def read_log(path, step_digest):
    """Reads the log and checks the hash chain before the sim starts."""
    rows = [json.loads(line, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
            for line in path.read_text().splitlines()]
    prev = GENESIS
    for n, row in enumerate(rows):
        if row["i"] != n - 1 or step_digest(prev, row["i"], row["a"], row["s"]) != row["h"]:
            raise ValueError(f"hash chain breaks at log line {n}")
        prev = row["h"]
    return rows, prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()
    run = Path(args.run_dir)

    scene = scene_schema.load(run / "scene.json")
    stored = json.loads((run / "result.json").read_text())
    stored_final = json.loads((run / "final_state.json").read_text())
    if scene_schema.scene_hash(scene) != stored["scene_sha256"]:
        print("MISMATCH: scene hash differs from result.json")
        return 1

    import numpy as np
    import sim

    report = {"scene_sha256": stored["scene_sha256"], "stored_mujoco": stored["mujoco"]}
    try:
        rows, head = read_log(run / "actions.jsonl", sim.step_digest)
    except (ValueError, KeyError, TypeError) as e:
        print(f"MISMATCH: {e}")
        return 1
    report["chain_ok"] = head == stored["action_chain_head"]

    wrapper, _, settle = sim.prepare(scene)
    inner = wrapper._env.env
    report["replay_mujoco"] = sim.versions()["mujoco"]
    report["model_match"] = sim.model_sha(inner.sim) == stored["model_state_sha256"]
    report["start_state_match"] = sim.state_sha(inner.sim) == stored["start_state_sha256"]

    outcome = sim.Outcome(wrapper)
    first_divergence = None
    success = False
    for row in rows[1:]:
        _, _, _, _, info = wrapper.step(np.array(row["a"], dtype=np.float64))
        success = bool(info["is_success"])
        outcome.update()
        if first_divergence is None and sim.state_sha(inner.sim) != row["s"]:
            first_divergence = row["i"]

    reason, _ = outcome.finish(success, stored["status"] == "invalid_action")
    final = sim.final_state(inner.sim)
    report.update({
        "steps_replayed": len(rows) - 1,
        "first_divergent_step": first_divergence,
        "success": {"stored": stored["success"], "replay": success},
        "reason": {"stored": stored["reason"], "replay": reason},
        "final_state_sha_match": sim.state_sha(inner.sim) == stored["final_state_sha256"],
        "final_qpos_max_abs_diff": float(np.max(np.abs(np.array(final["qpos"]) - np.array(stored_final["qpos"])))),
        "final_qvel_max_abs_diff": float(np.max(np.abs(np.array(final["qvel"]) - np.array(stored_final["qvel"])))),
    })
    report["outcome_match"] = success == stored["success"] and reason == stored["reason"]
    report["match"] = bool(
        report["chain_ok"] and report["model_match"] and report["start_state_match"]
        and report["outcome_match"] and report["final_state_sha_match"] and first_divergence is None
    )
    wrapper.close()
    (run / "replay.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    print("MATCH" if report["match"] else "MISMATCH")
    return 0 if report["match"] else 1


if __name__ == "__main__":
    sys.exit(main())
