"""The pack's editable controller. RouteFollower is ours: small and yours to change. WalkPolicy runs upstream's trained policy and has no route logic.

RouteFollower turns a pose into a velocity command (forward m/s, sideways m/s, turn rad/s). It knows the route and its own pose. It does not see objects.
WalkPolicy turns that command into 12 joint targets. It is blind too: it reads only the robot's own state.
Simulated. The policy is upstream's and nobody has checked it against a real robot.
"""
import math

import numpy as np
import warp as wp
from warp_nn.runtime import OnnxRuntime

SPEED_MPS = 0.8  # the policy barely moves below 0.5: a 0.3 command gave 0.00 to 0.04 m/s in our trials
TURN_RADPS = 1.0
HEADING_GAIN = 2.0  # turn rad/s per radian of heading error
TURN_IN_PLACE_DEG = 40.0  # stop walking and turn when the heading is off by more than this
LOOKAHEAD_M = 1.2  # steer at a point this far along the route, so the robot returns to the line
ARRIVE_M = 0.5  # a waypoint counts as passed inside this distance


def _closest_on_leg(p, a, b):
    ax, ay, bx, by = *a, *b
    dx, dy = bx - ax, by - ay
    along = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return along, math.hypot(dx, dy)


class RouteFollower:
    def __init__(self, waypoints):
        self.points = [(0.0, 0.0)] + [(p["x"], p["y"]) for p in waypoints]
        self.next = 1  # index of the waypoint it walks to

    @property
    def done(self):
        return self.next >= len(self.points)

    def command(self, x, y, yaw):
        while not self.done and math.dist((x, y), self.points[self.next]) < ARRIVE_M:
            self.next += 1
        if self.done:
            return (0.0, 0.0, 0.0)
        a, b = self.points[self.next - 1], self.points[self.next]
        along, length = _closest_on_leg((x, y), a, b)
        aim = min(1.0, along + LOOKAHEAD_M / length)
        tx, ty = a[0] + aim * (b[0] - a[0]), a[1] + aim * (b[1] - a[1])
        error = math.atan2(math.sin(math.atan2(ty - y, tx - x) - yaw), math.cos(math.atan2(ty - y, tx - x) - yaw))
        turn = max(-TURN_RADPS, min(TURN_RADPS, HEADING_GAIN * error))
        if abs(error) > math.radians(TURN_IN_PLACE_DEG):
            return (0.0, 0.0, turn)
        return (SPEED_MPS, 0.0, turn)


def _rotate_inv(q, v):
    u = -q[:3]
    t = 2.0 * np.cross(u, v)
    return v + q[3] * t + np.cross(u, t)


class WalkPolicy:
    """Upstream's ONNX policy with upstream's observation layout. The gravity input is a unit vector, so set_gravity does not reach it."""

    def __init__(self, path, q0, action_scale):
        self.net = OnnxRuntime(path, device=wp.get_device())
        self.in_name = self.net.inputs[0].name
        self.out_name = self.net.outputs[0].name
        self.q0 = q0
        self.scale = float(action_scale)
        self.prev = np.zeros(len(q0), dtype=np.float32)
        self.obs = wp.zeros((1, 12 + 3 * len(q0)), dtype=wp.float32)
        self.net.prepare({self.in_name: self.obs})

    def targets(self, q, qd, command):
        rot = q[3:7]
        down = np.array([0.0, 0.0, -1.0], dtype=np.float32)
        obs = np.concatenate([_rotate_inv(rot, qd[:3]), _rotate_inv(rot, qd[3:6]), _rotate_inv(rot, down), np.array(command, dtype=np.float32), q[7:] - self.q0, qd[6:], self.prev])
        self.obs.assign(obs.astype(np.float32)[None])
        act = self.net({self.in_name: self.obs})[self.out_name].numpy()[0].copy()
        self.prev = act
        return self.q0 + self.scale * act
