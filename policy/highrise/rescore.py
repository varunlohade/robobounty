"""Re-scores stored trials with the current judge by replaying their action logs: rescore.py <campaign dir> [--procs P]

The trial counts only if every step's state hash still matches. The old results stay in results_before_rescore.jsonl.
"""
import argparse
import json
import multiprocessing as mp
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import campaign
import replay

FIELDS = ("outcome", "hold_s", "hold_mean_wind_ms", "passed", "failure", "coverage", "reported_done", "reported_coverage", "slip_m",
          "peak_tether_n", "min_pressure_pa", "time_s")


def one(job):
    folder, row = job
    run = Path(folder) / row["trial"]
    rep = replay.replay(run)
    res = rep["judge_result"]
    same_states = rep["first_divergent_step"] is None and rep["final_state_match"] and rep["chain_ok"]
    if not same_states:
        return row["trial"], None, None
    if row["failure"] == "sim_diverged":
        return row["trial"], row, None
    stored = json.loads((run / "result.json").read_text())
    stored.update({k: res[k] for k in FIELDS})
    stored["fired"] = res["fired"]
    stored["rescored"] = True
    (run / "result.json").write_text(json.dumps(stored, indent=1) + "\n")
    new = dict(row)
    new.update({k: res[k] for k in FIELDS})
    new["fired"] = list(res["fired"])
    new["first_t"] = min([v["t"] for v in res["fired"].values()], default=None)
    return row["trial"], new, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--procs", type=int, default=campaign.MAX_PROCS)
    a = ap.parse_args()
    out = Path(a.folder)
    src = out / "results.jsonl"
    before = out / "results_before_rescore.jsonl"
    if not before.exists():
        shutil.copy(src, before)
    rows = [json.loads(l) for l in before.read_text().splitlines()]
    with mp.Pool(min(a.procs, campaign.MAX_PROCS)) as pool:
        done = pool.map(one, [(str(out), r) for r in rows])
    bad = [t for t, n, _ in done if n is None]
    if bad:
        raise SystemExit(f"state mismatch, not re-scored: {bad[:10]}")
    new = [n for _, n, _ in done]
    src.write_text("".join(json.dumps(r) + "\n" for r in new))
    text = campaign.table(new) + f"\nre-scored {len(new)} trials from stored logs, all state hashes match\n"
    (out / "table.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
