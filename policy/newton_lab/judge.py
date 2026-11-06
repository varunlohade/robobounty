"""Judges a run from its recorded state only: reached the target, fell over, stuck, or none of them.

Thresholds are ours, not from any standard. A flat-ground run stays far from all of them; check_lab.py prints the margins.
"""
import json
import sys

import numpy as np

FALL_UP_Z = 0.5
FALL_BASE_Z_M = 0.15
FALL_HOLD_S = 0.5
STUCK_WINDOW_S = 3.0
STUCK_TRAVEL_M = 0.25


def _first_held(flags, t, hold_s):
    start = None
    for i, flag in enumerate(flags):
        if not flag:
            start = None
            continue
        start = t[i] if start is None else start
        if t[i] - start >= hold_s:
            return float(start)
    return None


def judge(rec, target):
    t = rec["t"]
    xy = rec["base_q"][:, :2]
    qx, qy = rec["base_q"][:, 3], rec["base_q"][:, 4]
    up_z = 1.0 - 2.0 * (qx * qx + qy * qy)
    base_z = rec["base_q"][:, 2]

    dist = np.hypot(xy[:, 0] - target["x"], xy[:, 1] - target["y"])
    reached_idx = np.flatnonzero(dist <= target["radius"])
    reached_t = float(t[reached_idx[0]]) if reached_idx.size else None
    fell_t = _first_held((up_z < FALL_UP_Z) | (base_z < FALL_BASE_Z_M), t, FALL_HOLD_S)

    last = t >= t[-1] - STUCK_WINDOW_S
    travel = float(np.hypot(*(xy[last][-1] - xy[last][0])))
    stuck = bool(fell_t is None and reached_t is None and travel < STUCK_TRAVEL_M)

    if reached_t is not None and (fell_t is None or reached_t < fell_t):
        verdict = "reached"
    elif fell_t is not None:
        verdict = "fell"
    elif stuck:
        verdict = "stuck"
    else:
        verdict = "not_reached"
    return {
        "verdict": verdict,
        "reached_t_s": reached_t,
        "fell_t_s": fell_t,
        "closest_m": round(float(dist.min()), 3),
        "last_3s_travel_m": round(travel, 3),
        "final_xy_m": [round(float(v), 3) for v in xy[-1]],
        "min_up_z": round(float(up_z.min()), 3),
        "min_base_z_m": round(float(base_z.min()), 3),
    }


def load(path):
    with np.load(path, allow_pickle=False) as data:
        rec = {k: data[k] for k in data.files}
    return rec, json.loads(str(rec["meta"]))


if __name__ == "__main__":
    rec, meta = load(sys.argv[1])
    print(json.dumps(judge(rec, meta["world"]["target"]), indent=1))
