"""Judges a run from its recorded state and the world only. The controller's own report is never read. Thresholds are ours, not from any standard. Results are simulated."""
import numpy as np

from . import controller as C
from . import model as M
from . import sim as S

MIN_COVERAGE = 0.90
MAX_LANE_ERROR_M = 0.15
MAX_WHEEL_SLIP = 0.25  # 95th percentile on straight runs
STUCK_WINDOW_S = 10.0
STUCK_TRAVEL_M = 0.02
CRUISE_MIN_MS = 0.1


def coverage(rec, world):
    s, b = S.final_fouling(rec)
    xs, ys = S.cell_centres()
    p = world["patch"]
    ix = (xs > p["x0"]) & (xs < p["x1"])
    iy = (ys > p["y0"]) & (ys < p["y1"])
    region = np.ix_(iy, ix)
    was = (rec["fouling0_slime"][region] / 255.0 > S.CLEAN_LEVEL) | (rec["fouling0_barnacle"][region] / 255.0 > S.CLEAN_LEVEL)
    clean = (s[region] <= S.CLEAN_LEVEL) & (b[region] <= S.CLEAN_LEVEL)
    return float((clean & was).sum() / max(was.sum(), 1))


def judge(rec, world):
    t = rec["t"]
    xy = rec["body_q"][:, 0, :2].astype(np.float64)
    q = rec["body_q"][:, 0, 3:7].astype(np.float64)
    heading = np.arctan2(2 * (q[:, 3] * q[:, 2] + q[:, 0] * q[:, 1]), 1 - 2 * (q[:, 1] ** 2 + q[:, 2] ** 2))
    vel = rec["chassis_vel"].astype(np.float64)
    along = vel[:, 0] * np.cos(heading) + vel[:, 1] * np.sin(heading)
    lateral = -vel[:, 0] * np.sin(heading) + vel[:, 1] * np.cos(heading)
    rim = rec["wheel_rate"][:, :2].astype(np.float64) * M.WHEEL_R  # the driven pair
    straight = (np.abs(vel[:, 5]) < 0.05) & (np.abs(rim).mean(axis=1) > CRUISE_MIN_MS)
    slip = np.abs(rim - along[:, None]) / np.maximum(np.abs(rim), 0.05)
    slip_p95 = float(np.percentile(slip[straight], 95)) if straight.any() else 1.0
    slip_mean = float(slip[straight].mean()) if straight.any() else 1.0
    crab = float(np.percentile(np.abs(lateral[straight]), 95)) if straight.any() else 0.0

    dt = float(t[1] - t[0])
    gaps = rec["gap"]
    all_off = (gaps > S.DETACH_GAP_M).all(axis=1)
    hold = max(1, round(S.DETACH_HOLD_S / dt))
    run = np.convolve(all_off, np.ones(hold), "valid") >= hold
    detach_t = float(t[int(np.argmax(run))]) if run.any() else None

    lanes = np.array([world["patch"]["y0"] + 0.2 + i * C.LANE_SPACING for i in range(max(1, int(np.ceil((world["patch"]["y1"] - world["patch"]["y0"]) / C.LANE_SPACING - 1e-9))))])
    lane_err = np.abs(xy[:, 1, None] - lanes).min(axis=1)
    on_lane = np.abs(np.cos(heading)) > 0.99
    lane_max = float(lane_err[straight & on_lane].max()) if (straight & on_lane).any() else 0.0

    window = round(STUCK_WINDOW_S / dt)
    stuck_t = None
    if len(t) > window:
        moved = np.linalg.norm(xy[window:] - xy[:-window], axis=1)
        spinning = np.abs(rec["wheel_rate"][window:, :2]).max(axis=1) * M.WHEEL_R > 0.05
        hits = np.flatnonzero((moved < STUCK_TRAVEL_M) & spinning)
        if len(hits):
            stuck_t = float(t[hits[0]])

    cov = coverage(rec, world)
    limit = float(world["time_limit_s"])
    finished = float(t[-1]) < limit - 0.5
    sim_failed = bool(rec["sim_failed"])
    if sim_failed:
        verdict, reason = "sim_failed", "The physics blew up, so this run says nothing about the robot."
    elif detach_t is not None:
        verdict, reason = "detached", f"All four wheels left the plate at {detach_t:.1f} s, at x {xy[int(detach_t / dt), 0]:.2f} m, y {xy[int(detach_t / dt), 1]:.2f} m. Coverage reached {cov:.0%}."
    elif stuck_t is not None:
        verdict, reason = "stuck", f"The wheels turned but the robot stopped moving at {stuck_t:.1f} s, at x {xy[int(stuck_t / dt), 0]:.2f} m. Coverage reached {cov:.0%}."
    elif not finished:
        verdict, reason = "timed_out", f"The lanes were not done after {limit:.0f} s. Coverage reached {cov:.0%}."
    elif lane_max > MAX_LANE_ERROR_M:
        verdict, reason = "off_lane", f"The robot strayed {lane_max:.2f} m off its lane. The limit is {MAX_LANE_ERROR_M:.2f} m. Coverage reached {cov:.0%}."
    elif slip_p95 > MAX_WHEEL_SLIP:
        verdict, reason = "slipping", f"Wheel slip on straight runs reached {slip_p95:.0%} at the 95th percentile. The limit is {MAX_WHEEL_SLIP:.0%}."
    elif cov < MIN_COVERAGE:
        verdict, reason = "low_coverage", f"Coverage was {cov:.1%}. The limit is {MIN_COVERAGE:.0%}."
    else:
        verdict, reason = "passed", f"The robot cleaned {cov:.1%} of the patch in {float(t[-1]):.0f} s and kept all wheels on the plate."
    return {
        "verdict": verdict, "passed": verdict == "passed", "reason": reason, "coverage": round(cov, 4), "wheel_slip_mean": round(slip_mean, 4), "wheel_slip_p95": round(slip_p95, 4),
        "crab_p95_ms": round(crab, 4), "detached": detach_t is not None, "detach_t_s": detach_t, "stuck_t_s": stuck_t, "lane_error_max_m": round(lane_max, 4), "gap_max_m": round(float(gaps.max()), 4),
        "magnet_min_total_n": round(float(rec["magnet_n"].sum(axis=1).min()), 1), "time_s": round(float(t[-1]), 2), "simulated": True,
    }
