"""Pass or fail from sim state only. The controller's own report is never trusted for a pass."""
import math

import sim as S

COVERAGE_REQUIRED = 0.90
SLIP_LIMIT_M = 0.30  # longest single slide
SLIP_EPISODE_GAP_S = 1.0  # a slide ends after this long without slip
DETACH_GAP_M = 0.03  # body off the glass by this much
DETACH_HOLD_S = 0.10
TETHER_LOAD_LIMIT_N = 1000.0
TIME_LIMIT_S = 600.0
POST_DETACH_S = 8.0  # keep running this long after a detach to record the catch

RULES = ("detach", "tether_load", "slip_distance", "time_limit", "coverage", "false_done")


class Judge:
    def __init__(self):
        self.fired = {}
        self.slip_m = 0.0
        self.slip_episode_m = 0.0
        self.since_slip_s = 0.0
        self.peak_tension = 0.0
        self.peak_chassis = 0.0
        self.gap_time = 0.0
        self.detached_t = None
        self.min_dp = math.inf
        self.finished = False

    def _fire(self, rule, t, value):
        if rule not in self.fired:
            self.fired[rule] = {"t": t, "value": round(float(value), 4)}

    def update(self, sim, action):
        t = sim.t
        self.peak_tension = max(self.peak_tension, sim.tension_tick)
        self.peak_chassis = max(self.peak_chassis, sim.impact_tick)
        self.min_dp = min(self.min_dp, sim.dp)
        # A pivot skids its tracks by design, so slip counts only when the tracks run together on the glass.
        on_glass = sim.rollers_on_glass > 0
        if on_glass and sim.slip_rate > S.SLIP_FLOOR_MS and abs(sim.encoder_left - sim.encoder_right) < S.PIVOT_TRACK_DIFF_MS:
            self.slip_episode_m += sim.slip_rate * S.DT_CONTROL
            self.since_slip_s = 0.0
        else:
            self.since_slip_s += S.DT_CONTROL
            if self.since_slip_s > SLIP_EPISODE_GAP_S:
                self.slip_episode_m = 0.0
        self.slip_m = max(self.slip_m, self.slip_episode_m)
        if self.slip_episode_m > SLIP_LIMIT_M:
            self._fire("slip_distance", t, self.slip_episode_m)
        self.gap_time = self.gap_time + S.DT_CONTROL if sim.gap_center > DETACH_GAP_M else 0.0
        if self.gap_time >= DETACH_HOLD_S:
            self._fire("detach", t, sim.gap_center)
            self.detached_t = self.detached_t if self.detached_t is not None else t
        if sim.tension_tick > TETHER_LOAD_LIMIT_N:
            self._fire("tether_load", t, sim.tension_tick)

    def should_stop(self, sim, action):
        if action[4] >= 0.5:
            return True
        if self.detached_t is not None and sim.t - self.detached_t >= POST_DETACH_S:
            return True
        return sim.t >= TIME_LIMIT_S

    def finish(self, sim, action):
        reported_done = bool(action[4] >= 0.5)
        coverage = sim.coverage()
        if sim.t >= TIME_LIMIT_S and not reported_done:
            self._fire("time_limit", sim.t, sim.t)
        if coverage < COVERAGE_REQUIRED:
            self._fire("false_done" if reported_done else "coverage", sim.t, coverage)
        ordered = sorted(self.fired.items(), key=lambda kv: kv[1]["t"])
        return {
            "passed": not self.fired,
            "failure": ordered[0][0] if ordered else None,
            "fired": dict(ordered),
            "coverage": round(coverage, 4),
            "reported_done": reported_done,
            "reported_coverage": round(float(action[5]), 4),
            "slip_m": round(self.slip_m, 4),
            "peak_tether_n": round(self.peak_tension, 2),
            "peak_chassis_contact_n": round(self.peak_chassis, 2),
            "min_pressure_pa": round(self.min_dp, 1),
            "time_s": round(sim.t, 3),
            "end_battery": round(sim.soc, 4),
        }
