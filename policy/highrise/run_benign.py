"""Runs the hand-written benign worlds in worlds/benign.json, two seeds each: run_benign.py [--out DIR]

A second control, not used for any tuning. Writes the same results.jsonl rows and trial folders as campaign.py.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import campaign
import world as W

SEEDS = (2001, 2002)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(campaign.RUNS / "benign"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    nominal = W.load(HERE / "worlds" / "nominal.json")
    rows = []
    with (out / "results.jsonl").open("w") as f:
        for entry in json.loads((HERE / "worlds" / "benign.json").read_text()):
            changes = {k: v for k, v in entry.items() if k != "name"}
            world = W.validate({**nominal, **changes})
            for seed in SEEDS:
                r = campaign.run_trial.run(world, seed, out / f"{entry['name']}_{seed}")
                row = {"trial": f"{entry['name']}_{seed}", "kind": "benign", "seed": seed, "passed": r["passed"], "failure": r["failure"],
                       "fired": list(r["fired"]), "first_t": min([v["t"] for v in r["fired"].values()], default=None),
                       "coverage": r["coverage"], "reported_done": r["reported_done"], "reported_coverage": r["reported_coverage"],
                       "slip_m": r["slip_m"], "peak_tether_n": r["peak_tether_n"], "min_pressure_pa": r["min_pressure_pa"],
                       "time_s": r["time_s"], "wall_s": r["wall_s"], "outcome": r["outcome"], "hold_s": r["hold_s"],
                       "hold_mean_wind_ms": r["hold_mean_wind_ms"], "diverged_reason": r.get("diverged_reason"), "world": world}
                f.write(json.dumps(row) + "\n")
                rows.append(row)
    text = campaign.table(rows) + "\n"
    (out / "table.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
