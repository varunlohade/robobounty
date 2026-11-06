"""A scripted lawnmower for the crawler. It sees Sim.obs only: a noisy position fix, a noisy heading and wheel encoders. It never sees the fouling.

Lanes run along x. At a lane's end the robot pivots, shifts one lane spacing, pivots, backs up so that the brushes start at the patch edge, then cleans.
"""
import math

from . import model as M

LANE_SPACING = 0.40
CLEAN_SPEED = 0.25  # m/s
SHIFT_SPEED = 0.12
BACKUP_SPEED = 0.15
PIVOT_RATE = 0.35  # rad/s
OVERRUN_M = 0.05
HEADING_GAIN = 2.0
LANE_GAIN = 2.5  # radians of heading per metre off the lane
LANE_STEER_LIMIT = 0.35
ACCEL = 0.3  # m/s2
POS_BLEND = 0.15  # weight of each position fix against odometry
ARRIVE_M = 0.015
PIVOT_DONE_RAD = 0.02
BRUSH_RATE = 18.85  # rad/s, 180 rpm
SETTLE_S = 2.0


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Lawnmower:
    def __init__(self, patch, start):
        self.reach = M.BRUSH_X + OVERRUN_M
        n = max(1, math.ceil((patch["y1"] - patch["y0"]) / LANE_SPACING - 1e-9))
        self.lanes = [patch["y0"] + 0.2 + i * LANE_SPACING for i in range(n)]
        self.x0, self.x1 = patch["x0"], patch["x1"]
        self.k = 0
        self.state = "clean"
        self.est = list(start)
        self.heading_ref = 0.0
        self.v = 0.0
        self.t = 0.0
        self.done_t = None

    def _direction(self):
        return 1 if self.k % 2 == 0 else -1

    def _odometry(self, obs, dt):
        v = sum(obs["wheel_rate"]) / 2 * M.WHEEL_R
        self.est[0] += v * math.cos(obs["heading"]) * dt
        self.est[1] += v * math.sin(obs["heading"]) * dt
        if obs["fix"] is not None:
            self.est[0] += POS_BLEND * (obs["fix"][0] - self.est[0])
            self.est[1] += POS_BLEND * (obs["fix"][1] - self.est[1])

    def _ramp(self, target, dt):
        step = ACCEL * dt
        self.v += max(-step, min(step, target - self.v))
        return self.v

    def _hold_line(self, heading, along, off, sign):
        """Yaw rate to hold a line. off is the signed distance to the line's left, in the direction of travel."""
        steer = max(-LANE_STEER_LIMIT, min(LANE_STEER_LIMIT, LANE_GAIN * off))
        return HEADING_GAIN * wrap(self.heading_ref + sign * steer - heading)

    def command(self, obs, dt):
        """Returns (left wheel speed, right wheel speed, brush rate), speeds in m/s at the rim."""
        self.t += dt
        self._odometry(obs, dt)
        h = obs["heading"]
        x, y = self.est
        v, w = 0.0, 0.0
        brush = BRUSH_RATE
        d = self._direction()
        if self.state == "clean":
            self.heading_ref = 0.0 if d > 0 else math.pi
            lane = self.lanes[self.k]
            end = self.x1 - M.BRUSH_X + OVERRUN_M + M.BRUSH_R if d > 0 else self.x0 + M.BRUSH_X - OVERRUN_M - M.BRUSH_R
            left = (end - x) * d
            target = min(CLEAN_SPEED, max(0.03, left * 1.2))
            v = self._ramp(target, dt)
            w = self._hold_line(h, x, (lane - y) * d, 1)
            if left < ARRIVE_M:
                self.v = 0.0
                if self.k + 1 >= len(self.lanes):
                    self.state = "park"
                    self.done_t = self.t
                else:
                    self.state = "pivot1"
                    self.heading_ref = math.pi / 2
        elif self.state == "pivot1":
            e = wrap(self.heading_ref - h)
            w = max(-PIVOT_RATE, min(PIVOT_RATE, 2.0 * e))
            if abs(e) < PIVOT_DONE_RAD:
                self.state = "shift"
        elif self.state == "shift":
            lane = self.lanes[self.k + 1]
            left = lane - y
            v = self._ramp(min(SHIFT_SPEED, max(0.03, left * 1.2)), dt)
            w = HEADING_GAIN * wrap(self.heading_ref - h)
            if left < ARRIVE_M:
                self.v = 0.0
                self.k += 1
                self.state = "pivot2"
                self.heading_ref = 0.0 if self._direction() > 0 else math.pi
        elif self.state == "pivot2":
            e = wrap(self.heading_ref - h)
            w = max(-PIVOT_RATE, min(PIVOT_RATE, 2.0 * e))
            if abs(e) < PIVOT_DONE_RAD:
                self.state = "backup"
        elif self.state == "backup":
            lane = self.lanes[self.k]
            back_to = self.x0 - self.reach - M.BRUSH_R if d > 0 else self.x1 + self.reach + M.BRUSH_R
            left = (x - back_to) * d
            v = -self._ramp(min(BACKUP_SPEED, max(0.03, left * 1.2)), dt)
            w = self._hold_line(h, x, (lane - y) * -d, -1)
            if left < ARRIVE_M:
                self.v = 0.0
                self.state = "clean"
        else:
            brush = 0.0
        half = M.WHEEL_Y
        return v - w * half, v + w * half, brush

    @property
    def done(self):
        return self.state == "park" and self.t - self.done_t > SETTLE_S
