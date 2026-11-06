"""First-attempt controller for the suction window robot. It sees only Sim.obs and the mission numbers.

It cleans a lawnmower path of vertical lanes, starting at the top of the left lane. Position comes
from track encoders and the heading from gravity. There is no absolute position sensor on the robot.
Pressure comes from impeller current, using the fan curve the robot was designed with.
"""
import math

# Lane plan.
PAD_WIDTH = 0.30
LANE_SPACING = 0.27
PAD_BEHIND_CENTRE = 0.13
CLEAN_SPEED = 0.15  # m/s
CROSS_SPEED = 0.07  # m/s over a joint
TURN_SPEED = 0.08  # track speed, m/s, when pivoting
MAX_TRACK_SPEED = 0.35
HEADING_GAIN = 0.6  # track speed per radian
LANE_X_GAIN = 0.8  # radians of steering per metre off the lane
LANE_X_STEER_LIMIT = 0.25
TURN_TOLERANCE = 0.03
PIVOT_SAG_M_PER_RAD = 0.125  # a pivot skids the tracks, so the body slides down this much, measured on the nominal world
LANE_OVERRUN_M = 0.10  # drive this far past the area edge, for position error

# Suction.
SUCTION_CLEAN = 0.85
SUCTION_MAX = 1.0

# Pressure estimate from impeller current. Design numbers of the fan.
DESIGN_P_MAX = 2800.0
DESIGN_Q_MAX = 0.03
DESIGN_EFFICIENCY = 0.35
DESIGN_LOSS_W = 25.0
DESIGN_V_FULL = 14.0
DESIGN_SPEED_LAG_S = 0.4
CURRENT_FILTER_S = 0.3
LOW_PRESSURE_PA = 1500.0  # stop and back away below this
RESUME_PRESSURE_PA = 1700.0
SPEED_SETTLE = 0.02  # ignore the estimate while the impeller is still changing speed by more than this
HOLD_RECOVER_S = 2.0
RETREAT_M = 0.25
MAX_RETREATS_PER_LANE = 3

# Nose sensors.
JOINT_SEEN_M = 0.003
MAX_CROSS_HEIGHT_M = 0.018
JOINT_BODY_CLEAR_M = 0.45  # distance to keep the slow speed after seeing a joint
NOSE_FILTER_HITS = 2

# Wind.
WIND_PAUSE_MS = 10.0  # unvalidated vendor figure, see PARAMETERS.md
WIND_RESUME_MS = 7.0
WIND_RESUME_WAIT_S = 5.0

# Tether.
TETHER_SLACK_M = 1.0
TETHER_REEL_GAIN = 1.0
TETHER_RATE_MAX = 0.6
TETHER_TENSION_PAYOUT_N = 80.0

# Battery.
BATTERY_LOW_V = 12.8


class Controller:
    def __init__(self, mission):
        self.m = mission
        a = mission["area"]
        n_lanes = max(1, math.ceil((a["x1"] - a["x0"] - PAD_WIDTH) / LANE_SPACING) + 1)
        x0 = a["x0"] + PAD_WIDTH / 2 - 0.03
        self.lane_xs = [x0 + i * LANE_SPACING for i in range(n_lanes)]
        self.z_top = a["z1"] + PAD_BEHIND_CENTRE + LANE_OVERRUN_M
        self.z_bottom = a["z0"] - PAD_BEHIND_CENTRE - LANE_OVERRUN_M
        self.anchor = mission["anchor"]
        self.x, self.z = mission["start_x"], mission["start_z"]
        self.heading0 = -math.pi / 2
        self.lane = 0
        self.going_down = True
        self.phase = "seal"
        self.phase_t = 0.0
        self.turn_target = None
        self.after_turn = None
        self.side_target = None
        self.retreat_left = 0.0
        self.retreats = 0
        self.ok_since = None
        self.calm_since = None
        self.wind_hold = False
        self.current_avg = None
        self.joint_until = 0.0  # odometer reading where the slow zone ends
        self.odo = 0.0
        self.clean_m = 0.0
        self.plan_m = (self.z_top - self.z_bottom) * n_lanes
        self.nose_hits = {"joint": 0, "edge": 0, "high": 0}
        self.resume_phase = None
        self.estimate = 0.0
        self.speed_est = 1.0  # impeller speed, tracked from the commands sent
        self.last_cap = 1.0
        self.last_heading = None

    def _set(self, phase, t):
        self.phase, self.phase_t = phase, t

    def _pressure_estimate(self, o):
        """Inverts power = loss + dP Q / eff on the fan curve, on the high-pressure side of its peak."""
        s = self.speed_est
        power = o["battery_volts"] * self.current_avg - DESIGN_LOSS_W * s ** 3
        pm, qm = DESIGN_P_MAX * s * s, DESIGN_Q_MAX * s
        lo, hi = 2.0 / 3.0, 1.0  # pressure fraction; power falls as this rises
        for _ in range(14):
            mid = (lo + hi) / 2
            model = pm * mid * qm * math.sqrt(1 - mid) / DESIGN_EFFICIENCY
            if model > power:
                lo = mid
            else:
                hi = mid
        return pm * (lo + hi) / 2

    def _update_position(self, o):
        v = (o["encoder_left"] + o["encoder_right"]) / 2
        h = o["imu_heading"]
        self.x += v * math.cos(h) * 0.05
        self.z += v * math.sin(h) * 0.05
        self.odo += abs(v) * 0.05
        if self.phase == "turn" and self.last_heading is not None:
            self.z -= PIVOT_SAG_M_PER_RAD * abs(_wrap(h - self.last_heading))
        self.last_heading = h

    def _nose(self, o):
        """Counts consecutive hits so one bad reading does not trigger anything."""
        readings = [n for n in o["nose"] if n["valid"]]
        joint = any(n["height"] > JOINT_SEEN_M for n in readings)
        high = any(n["height"] > MAX_CROSS_HEIGHT_M for n in readings)
        edge = any(n["off_glass"] for n in readings)
        for key, seen in (("joint", joint), ("high", high), ("edge", edge)):
            self.nose_hits[key] = self.nose_hits[key] + 1 if seen else 0
        return {k: v >= NOSE_FILTER_HITS for k, v in self.nose_hits.items()}

    def _steer(self, o, heading_want, speed):
        err = _wrap(heading_want - o["imu_heading"])
        w = HEADING_GAIN * err
        return _clamp(speed - w, -MAX_TRACK_SPEED, MAX_TRACK_SPEED), _clamp(speed + w, -MAX_TRACK_SPEED, MAX_TRACK_SPEED)

    def _tether(self, o):
        """Keeps the line a little longer than the estimated distance to the roof anchor."""
        ax, ay, az = self.anchor
        want = math.sqrt((self.x - ax) ** 2 + ay ** 2 + (self.z - az) ** 2) + TETHER_SLACK_M
        rate = TETHER_REEL_GAIN * (want - o["tether_length"])
        if o["tether_tension"] > TETHER_TENSION_PAYOUT_N:
            rate = max(rate, TETHER_RATE_MAX)
        return max(-TETHER_RATE_MAX, min(TETHER_RATE_MAX, rate))

    def _lane_done(self):
        return self.z <= self.z_bottom if self.going_down else self.z >= self.z_top

    def _begin_side_step(self, t):
        if self.lane + 1 >= len(self.lane_xs):
            self._set("finished", t)
            return
        self.lane += 1
        self.retreats = 0
        self.turn_target = 0.0  # face +x
        self.after_turn = "side_step"
        self._set("turn", t)

    def step(self, o):
        t = o["t"]
        self.current_avg = o["fan_current"] if self.current_avg is None else (
            self.current_avg + (o["fan_current"] - self.current_avg) * min(1.0, 0.05 / CURRENT_FILTER_S))
        self._update_position(o)
        nose = self._nose(o)
        left = right = 0.0
        suction = SUCTION_CLEAN
        done = 0.0

        # Wind response: stop and hold on maximum suction.
        if o["roof_wind"] > WIND_PAUSE_MS:
            self.wind_hold = True
            self.calm_since = None
        elif self.wind_hold and o["roof_wind"] < WIND_RESUME_MS:
            self.calm_since = t if self.calm_since is None else self.calm_since
            if t - self.calm_since > WIND_RESUME_WAIT_S:
                self.wind_hold = False
        else:
            self.calm_since = None

        pressure = self._pressure_estimate(o)
        self.estimate = pressure
        settled = abs(self.last_cap - self.speed_est) < SPEED_SETTLE
        low = settled and pressure < LOW_PRESSURE_PA

        if self.phase == "seal":
            suction = SUCTION_MAX
            if t - self.phase_t > 2.0:
                self._set("clean", t)
        elif self.phase in ("clean", "side_step", "turn") and (self.wind_hold or low):
            self.resume_phase = self.phase
            self.ok_since = None
            if low and not self.wind_hold and self.retreats < MAX_RETREATS_PER_LANE:
                self.retreats += 1
                self.retreat_left = RETREAT_M
                self._set("retreat", t)
            else:
                self._set("hold", t)
        elif self.phase == "hold":
            suction = SUCTION_MAX
            if not self.wind_hold and settled and pressure >= RESUME_PRESSURE_PA:
                self.ok_since = t if self.ok_since is None else self.ok_since
                if t - self.ok_since > HOLD_RECOVER_S:
                    if self.retreats >= MAX_RETREATS_PER_LANE and self.resume_phase == "clean":
                        self.resume_phase = None
                        self._begin_side_step_from_stop(t)
                    else:
                        self._set(self.resume_phase, t)
            else:
                self.ok_since = None
        elif self.phase == "retreat":
            suction = SUCTION_MAX
            left, right = self._steer(o, o["imu_heading"], -CROSS_SPEED)
            self.retreat_left -= CROSS_SPEED * 0.05
            if self.retreat_left <= 0:
                self.ok_since = None
                self._set("hold", t)
        elif self.phase == "clean":
            down = -math.pi / 2
            up = math.pi / 2
            lane_err = self.lane_xs[self.lane] - self.x
            steer = max(-LANE_X_STEER_LIMIT, min(LANE_X_STEER_LIMIT, LANE_X_GAIN * lane_err))
            want = down + steer if self.going_down else up - steer
            speed = CLEAN_SPEED
            if nose["joint"]:
                self.joint_until = self.odo + JOINT_BODY_CLEAR_M
            if self.odo < self.joint_until:
                speed = CROSS_SPEED
                suction = SUCTION_MAX
            left, right = self._steer(o, want, speed)
            self.clean_m += speed * 0.05 if abs(o["encoder_left"] + o["encoder_right"]) > 0.02 else 0.0
            if nose["high"] or nose["edge"]:
                left = right = 0.0
                self._begin_side_step_from_stop(t)
            elif self._lane_done():
                left = right = 0.0
                self._begin_side_step(t)
        elif self.phase == "turn":
            suction = SUCTION_MAX
            err = _wrap(self.turn_target - o["imu_heading"])
            if abs(err) < TURN_TOLERANCE:
                self._set(self.after_turn, t)
            else:
                turn = TURN_SPEED if err > 0 else -TURN_SPEED
                left, right = -turn, turn
        elif self.phase == "side_step":
            target = self.lane_xs[self.lane]
            left, right = self._steer(o, 0.0, CLEAN_SPEED)
            if nose["edge"] or self.x >= target:
                left = right = 0.0
                self.going_down = not self.going_down
                self.turn_target = -math.pi / 2 if self.going_down else math.pi / 2
                self.after_turn = "clean"
                self._set("turn", t)
        elif self.phase == "finished":
            done = 1.0

        if o["battery_volts"] < BATTERY_LOW_V and self.phase != "finished":
            self._set("hold", t)

        cap = min(suction, min(1.0, o["battery_volts"] / DESIGN_V_FULL))
        self.last_cap = cap
        self.speed_est += (cap - self.speed_est) * min(1.0, 0.05 / DESIGN_SPEED_LAG_S)
        reported = min(1.0, self.clean_m / self.plan_m) if self.plan_m > 0 else 0.0
        return [left, right, suction, self._tether(o), done, reported]

    def _begin_side_step_from_stop(self, t):
        """Gives up the rest of this lane and moves to the next one."""
        self._begin_side_step(t)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi
