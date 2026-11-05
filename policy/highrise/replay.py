"""Replays a stored action log with no controller and compares every step: replay.py <run dir>"""
import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge as judge_module
import run_trial
import sim as S
import world as W


def read_log(path):
    """Reads the log and checks the hash chain before the sim starts."""
    with gzip.open(path, "rt") as f:
        rows = [json.loads(line, parse_constant=W._reject_constant) for line in f]
    prev = run_trial.GENESIS
    for n, row in enumerate(rows):
        if row["i"] != n - 1 or S.digest(prev, row["i"], row["a"], row["s"]) != row["h"]:
            raise ValueError(f"hash chain breaks at log line {n}")
        prev = row["h"]
    return rows, prev


def replay(run_dir, keep=None):
    """Runs the stored actions. keep(sim, i) is called after every step, for renderers."""
    run = Path(run_dir)
    world = W.load(run / "world.json")
    stored = json.loads((run / "result.json").read_text())
    report = {"world_match": W.world_hash(world) == stored["world_sha256"]}
    rows, head = read_log(run / "actions.jsonl.gz")
    report["chain_ok"] = head == stored["action_chain_head"]
    sim = S.Sim(world, stored["seed"])
    report["model_match"] = sim.model_sha == stored["model_sha256"]
    report["start_state_match"] = sim.start_sha == stored["start_state_sha256"]
    judge = judge_module.Judge()
    first_divergence = None
    action = [0.0] * len(S.ACTION_FIELDS)
    for row in rows[1:]:
        action = row["a"]
        if not sim.step(action):
            first_divergence = row["i"] if first_divergence is None else first_divergence
            break
        judge.update(sim, action)
        if first_divergence is None and sim.state_sha() != row["s"]:
            first_divergence = row["i"]
        if keep is not None:
            keep(sim, row["i"])
    result = judge.finish(sim, action)
    keys = ("failure", "passed", "coverage", "reported_done", "slip_m", "peak_tether_n", "time_s")
    report.update({
        "steps_replayed": len(rows) - 1, "first_divergent_step": first_divergence,
        "final_state_match": sim.state_sha() == stored["final_state_sha256"],
        "outcome": {k: {"stored": stored[k], "replay": result[k]} for k in keys},
        "fired_match": list(result["fired"]) == list(stored["fired"]),
    })
    report["outcome_match"] = all(v["stored"] == v["replay"] for v in report["outcome"].values())
    report["match"] = bool(report["chain_ok"] and report["model_match"] and report["start_state_match"] and report["world_match"]
                           and first_divergence is None and report["final_state_match"] and report["outcome_match"]
                           and report["fired_match"])
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()
    r = replay(args.run_dir)
    (Path(args.run_dir) / "replay.json").write_text(json.dumps(r, indent=1) + "\n")
    print(json.dumps(r, indent=1))
    print("MATCH" if r["match"] else "MISMATCH")
    sys.exit(0 if r["match"] else 1)
