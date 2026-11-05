"""Runs many trials: campaign.py --n N --seed S [--vary wind|all] [--out DIR] [--procs P]

Resumable: a rerun with the same arguments skips trials already in results.jsonl.
The first trials are controls on the nominal world. Each trial stores its world, action log and qpos.
"""
import argparse
import json
import math
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_trial
import world as W

MAX_PROCS = 4
RUNS = HERE.parent / "runs" / "highrise"

WIND_RANGES = {
    "steady_wind_ms": (0.0, 10.0),
    "gust_speed_ms": (3.0, 40.0),
    "gust_start_s": (10.0, 200.0),
    "gust_duration_s": (3.0, 25.0),
    "gust_period_s": (20.0, 90.0),
    "wind_dir_deg": (-180.0, 180.0),
}
OTHER_RANGES = {
    "wetness": (0.0, 0.6),
    "mullion_depth_m": (0.001, 0.012),
    "mullion_spacing_m": (1.0, 2.4),
    "mullion_offset_m": (0.0, 2.4),
    "joint_gap_m": (0.0, 0.008),
    "edge_margin_m": (0.5, 2.0),
    "area_width_m": (1.6, 3.2),
    "area_height_m": (2.0, 4.0),
    "drop_below_roof_m": (8.0, 60.0),
    "suction_pa": (2200.0, 3500.0),
    "seal_leak_mm2": (100.0, 350.0),
    "battery_start_frac": (0.25, 1.0),
    "pad_force_n": (15.0, 40.0),
    "dirt_level": (0.3, 1.0),
    "ledge_depth_m": (0.02, 0.10),
    "ledge_x_m": (-2.0, 2.0),
    "ledge_width_m": (0.5, 3.0),
    "sun_level": (0.3, 1.0),
}
LEDGE_INSIDE_SHARE = 0.3


def sample_world(nominal, campaign_seed, index, vary):
    rng = np.random.default_rng([campaign_seed, index, 101])
    world = dict(nominal)
    for name, (lo, hi) in WIND_RANGES.items():
        world[name] = round(float(rng.uniform(lo, hi)), 4)
    world["gust_count"] = int(rng.integers(0, 5))
    if vary == "all":
        for name, (lo, hi) in OTHER_RANGES.items():
            world[name] = round(float(rng.uniform(lo, hi)), 4)
        h = world["area_height_m"]
        if rng.uniform() < LEDGE_INSIDE_SHARE:
            world["ledge_below_top_m"] = round(float(rng.uniform(0.5, h)), 4)
        else:
            world["ledge_below_top_m"] = round(float(rng.uniform(h + 1.0, 14.0)), 4)
    return W.validate(world)


def run_one(job):
    trial, world, seed, kind, out = job
    r = run_trial.run(world, seed, Path(out) / trial)
    return {"trial": trial, "kind": kind, "seed": seed, "passed": r["passed"], "failure": r["failure"],
            "fired": list(r["fired"]), "first_t": min([v["t"] for v in r["fired"].values()], default=None),
            "coverage": r["coverage"], "reported_done": r["reported_done"], "reported_coverage": r["reported_coverage"],
            "slip_m": r["slip_m"], "peak_tether_n": r["peak_tether_n"], "min_pressure_pa": r["min_pressure_pa"],
            "time_s": r["time_s"], "wall_s": r["wall_s"], "world": world}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def table(rows):
    lines = []
    for kind in ("control", "varied"):
        sub = [r for r in rows if r["kind"] == kind]
        passed = sum(r["passed"] for r in sub)
        lo, hi = wilson(passed, len(sub))
        lines.append(f"{kind}: {passed}/{len(sub)} passed, 95% interval {lo:.2f}-{hi:.2f}")
        first = Counter(r["failure"] for r in sub if not r["passed"])
        anyf = Counter(f for r in sub for f in r["fired"])
        lines.append(f"  {'failure type':<16}{'first':>7}{'any':>7}  example")
        for name, n in first.most_common():
            ex = next(r["trial"] for r in sub if r["failure"] == name)
            lines.append(f"  {name:<16}{n:>7}{anyf[name]:>7}  {ex}")
        for name, n in anyf.items():
            if name not in first:
                ex = next(r["trial"] for r in sub if name in r["fired"])
                lines.append(f"  {name:<16}{0:>7}{n:>7}  {ex}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--vary", choices=("wind", "all"), default="all")
    ap.add_argument("--controls", type=int, default=None)
    ap.add_argument("--out")
    ap.add_argument("--procs", type=int, default=MAX_PROCS)
    a = ap.parse_args()
    procs = min(a.procs, MAX_PROCS)
    out = Path(a.out) if a.out else RUNS / f"campaign_{a.vary}_{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    controls = a.controls if a.controls is not None else max(5, a.n // 20)
    meta = {"n": a.n, "seed": a.seed, "vary": a.vary, "controls": controls}
    meta_path = out / "campaign.json"
    if meta_path.exists() and json.loads(meta_path.read_text()) != meta:
        raise SystemExit(f"{out} holds a different campaign")
    meta_path.write_text(json.dumps(meta) + "\n")

    nominal = W.load(HERE / "worlds" / "nominal.json")
    results_path = out / "results.jsonl"
    rows = [json.loads(l) for l in results_path.read_text().splitlines()] if results_path.exists() else []
    done = {r["trial"] for r in rows}
    jobs = []
    for i in range(controls):
        jobs.append((f"control{i:03d}", nominal, 1000 + i, "control", str(out)))
    for i in range(a.n):
        world = sample_world(nominal, a.seed, i, a.vary)
        jobs.append((f"t{i:04d}", world, a.seed * 100000 % 2**31 + i, "varied", str(out)))
    jobs = [j for j in jobs if j[0] not in done]
    print(f"{len(done)} done, {len(jobs)} to run on {procs} processes", flush=True)
    t0 = time.time()
    if jobs:
        with mp.Pool(procs) as pool, results_path.open("a") as f:
            for n, row in enumerate(pool.imap_unordered(run_one, jobs), 1):
                f.write(json.dumps(row) + "\n")
                f.flush()
                rows.append(row)
                if n % 50 == 0:
                    print(f"{n}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    wall = time.time() - t0
    rate = len(jobs) / wall * 60 if jobs and wall > 0 else 0.0
    text = table(rows) + f"\nthis run: {len(jobs)} trials in {wall:.1f}s = {rate:.0f} trials per minute on {procs} processes\n"
    (out / "table.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
