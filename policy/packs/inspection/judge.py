"""Judges a run from its recorded state and the route only. The controller's own report is never read.

Thresholds are ours, not from any standard. check_pack.py prints how far a clean run stays from them. Results are simulated.
"""
import math

import numpy as np

from . import world as W

REACH_M = 0.6  # wider than the follower's ARRIVE_M, so the judge counts what the follower passes
FALL_UP_Z = 0.5
FALL_CLEARANCE_M = 0.30  # a standing ANYmal C holds its base about 0.59 m above the surface
FALL_HOLD_S = 1.0
STUCK_WINDOW_S = 6.0
STUCK_TRAVEL_M = 0.3
OFF_ROUTE_M = 1.0


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


def _route_points(world):
    return [(0.0, 0.0)] + [(p["x"], p["y"]) for p in world["route"]["waypoints"]]


def _deviation(xy, points):
    best = np.full(len(xy), np.inf)
    for a, b in zip(points, points[1:]):
        a, b = np.array(a), np.array(b)
        d = b - a
        s = np.clip(((xy - a) @ d) / (d @ d), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(xy - (a + s[:, None] * d), axis=1))
    return best


def _near(world, x, y):
    """The name of the object closest to a point, within 1.5 m."""
    best, name = 1.5, None
    for obj in world["objects"]:
        x0, x1, y0, y1 = W.footprint(obj)
        gap = math.hypot(max(x0 - x, x - x1, 0.0), max(y0 - y, y - y1, 0.0))
        if gap < best:
            best, name = gap, obj["name"]
    return name


def judge(rec, world):
    t = rec["t"]
    sim_failed = bool(rec["sim_failed"])
    if len(t) < 2:
        return {"verdict": "sim_failed", "passed": False, "reason": "The physics blew up at the start, so this run says nothing about the robot."}
    xy = rec["base_q"][:, :2].astype(np.float64)
    base_z = rec["base_q"][:, 2].astype(np.float64)
    qx, qy = rec["base_q"][:, 3], rec["base_q"][:, 4]
    up_z = 1.0 - 2.0 * (qx * qx + qy * qy)
    points = _route_points(world)
    n = len(points) - 1

    reached = []
    target = 1
    for i in range(len(t)):
        if target > n:
            break
        if math.hypot(xy[i, 0] - points[target][0], xy[i, 1] - points[target][1]) <= REACH_M:
            reached.append(round(float(t[i]), 2))
            target += 1
    finish_t = reached[-1] if len(reached) == n else None

    clearance = base_z - np.array([W.surface_height(world, float(x), float(y)) for x, y in xy])
    fell_t = _first_held((up_z < FALL_UP_Z) | (clearance < FALL_CLEARANCE_M), t, FALL_HOLD_S)
    if fell_t is not None and finish_t is not None and finish_t < fell_t:
        fell_t = None

    # A stall starts when the base stays within STUCK_TRAVEL_M of one spot. A stall that lasts to the end of the run is stuck.
    stall_start = 0
    longest_stall = 0.0
    for i in range(len(t)):
        if math.hypot(xy[i, 0] - xy[stall_start, 0], xy[i, 1] - xy[stall_start, 1]) > STUCK_TRAVEL_M:
            stall_start = i
        longest_stall = max(longest_stall, float(t[i] - t[stall_start]))
    stuck_t = None
    if fell_t is None and finish_t is None and float(t[-1] - t[stall_start]) >= STUCK_WINDOW_S:
        stuck_t = float(t[stall_start])

    dev = _deviation(xy, points)
    end = np.searchsorted(t, fell_t) if fell_t is not None else len(t)
    dev_max = float(dev[:max(end, 1)].max())
    dev_mean = float(dev[:max(end, 1)].mean())
    speed = rec["foot_v_xy"][rec["feet"]]

    place = None
    if sim_failed:
        verdict, reason = "sim_failed", "The physics blew up, so this run says nothing about the robot."
    elif fell_t is not None:
        i = int(np.searchsorted(t, fell_t))
        place = _near(world, *xy[min(i, len(xy) - 1)])
        verdict, reason = "fell", f"The robot fell at {fell_t:.1f} s, at x {xy[min(i, len(xy) - 1), 0]:.1f} m, y {xy[min(i, len(xy) - 1), 1]:.1f} m, after {len(reached)} of {n} waypoints" + (f", near {place}." if place else ".")
    elif stuck_t is not None:
        i = int(np.searchsorted(t, stuck_t))
        place = _near(world, *xy[i])
        verdict, reason = "stuck", f"The robot stopped making progress at {stuck_t:.1f} s, after {len(reached)} of {n} waypoints" + (f", near {place}." if place else ".")
    elif finish_t is None:
        verdict, reason = "timed_out", f"The robot reached {len(reached)} of {n} waypoints in {float(t[-1]):.0f} s and ran out of time. Its longest stall was {longest_stall:.1f} s."
    elif dev_max > OFF_ROUTE_M:
        verdict, reason = "off_route", f"The robot reached every waypoint, but strayed {dev_max:.2f} m from the route. The limit is {OFF_ROUTE_M:.1f} m."
    else:
        verdict, reason = "passed", f"The robot reached all {n} waypoints in {finish_t:.1f} s, and stayed within {dev_max:.2f} m of the route."
    return {
        "verdict": verdict, "passed": verdict == "passed", "reason": reason, "waypoints_reached": len(reached), "waypoints": n, "waypoint_t_s": reached, "time_s": finish_t, "fell_t_s": None if fell_t is None else round(fell_t, 2), "stuck_t_s": None if stuck_t is None else round(stuck_t, 2), "longest_stall_s": round(longest_stall, 1),
        "deviation_max_m": round(dev_max, 3), "deviation_mean_m": round(dev_mean, 3), "min_up_z": round(float(up_z.min()), 3), "min_clearance_m": round(float(clearance.min()), 3),
        "end_xy_m": [round(float(v), 2) for v in xy[-1]], "object_peak_N": round(float(rec["object_f"].max()), 1), "object_contact_s": round(float((rec["object_f"] > 0).sum()) * float(t[1] - t[0]), 2),
        "foot_slip_mps": round(float(speed.mean()), 3) if speed.size else None, "body_on_ground_peak_N": round(float(rec["body_on_ground_f"].max()), 1),
    }
