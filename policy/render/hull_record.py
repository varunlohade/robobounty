"""Reads one recorded hull run and holds the shot list. Numpy and stdlib only, so it runs inside Blender's Python too. It only reads.

The record is policy/packs/hull/out/<run>.npz: body poses at 50 Hz, wheel and brush speeds, and the fouling grid as a start plus changes at 10 Hz.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy" / "packs" / "hull" / "out"
# Copied from packs/hull/model.py so that Blender's Python need not import MuJoCo. hull_check.py compares them with the source.
ROLLER_R = 0.03
AXLE_Z = 0.06
TRACK_Y = 0.21
TRACK_X = (-0.25, 0.10)
ROLLERS = 7
ROLLER_XS = tuple(float(x) for x in np.linspace(TRACK_X[0], TRACK_X[1], ROLLERS))
SEAM_R = 0.04
DRUM_X = 0.235
DRUM_Z = 0.032
DRUM_TIP_R = 0.07
DRUM_HALF_W = 0.23
TETHER_LOCAL = (-0.31, 0.0, -0.03)
# The picture's track, built on those numbers. Art, except where hull_check.py says otherwise.
CONTACT_Z = AXLE_Z + ROLLER_R  # the shoe faces meet the plate here, as the physics capsules do
LOOP_R = 0.06  # outer radius round each end
IDLER_Z = CONTACT_Z - LOOP_R
SPROCKET_R = 0.036
DRAWN_ROLLER_R = 0.014
SHOES = 22
SHOE_W = 0.09
SHOE_LEN = 0.042
LAMP_LOCAL = (0.165, 0.10, -0.098)
SEAMS_X = (1.6, 4.0, 6.4)
SEAMS_Y = (1.0,)
PLATE_X = (-1.5, 9.0)
PLATE_Y = (-1.5, 3.4)
TETHER_ANCHOR = (3.0, -25.0, -6.0)
SIM_NOTE = "Simulated. Simplified physics."


def run_path(run):
    p = Path(run)
    return p if p.suffix == ".npz" else OUT / f"{run}.npz"


class Record:
    def __init__(self, run):
        path = run_path(run)
        if not path.exists():
            raise SystemExit(f"no recorded run at {path}. Run: policy/.venv/bin/python -m packs.hull.check_pack, from policy/")
        self.name = path.stem
        d = np.load(path)
        self.t = d["t"].astype(np.float64)
        self.body_q = d["body_q"].astype(np.float64)
        self.drum_rate = d["drum_rate"].astype(np.float64)
        self.track_speed = d["track_speed"].astype(np.float64)
        self.travel = d["track_travel"].astype(np.float64)
        self.spring = d["spring"].astype(np.float64)
        self.removed = d["removed"].astype(np.float64)
        self.meta = json.loads(str(d["meta"]))
        self.labels = self.meta["body_labels"]
        self.world = self.meta["world"]
        self.dt = float(self.t[1] - self.t[0])
        self.s0 = d["fouling0_slime"].astype(np.float32) / 255.0
        self.b0 = d["fouling0_barnacle"].astype(np.float32) / 255.0
        self.grid_t = d["grid_t"].astype(np.float64)
        frame, cell = d["delta_frame"], d["delta_cell"]
        order = np.argsort(frame, kind="stable")
        self.df, self.dc = frame[order], cell[order]
        self.ds, self.db = d["delta_slime"][order].astype(np.float32) / 255.0, d["delta_barnacle"][order].astype(np.float32) / 255.0
        self.cell_m = self.meta["cell_m"]
        self.grid_x, self.grid_y = self.meta["grid_x"], self.meta["grid_y"]
        self.shape = self.s0.shape
        self._root = self.body_q[:, 0, :3]
        self._k = -1
        self._s, self._b = self.s0.copy(), self.b0.copy()

    def pose(self, t):
        """All bodies at t. Linear position and normalised linear quaternion between 50 Hz samples. Time outside the record raises."""
        if not self.t[0] - 1e-6 <= t <= self.t[-1] + 1e-6:
            raise ValueError(f"t={t} is outside the record, {self.t[0]:.2f} to {self.t[-1]:.2f} s")
        f = np.clip((t - self.t[0]) / self.dt, 0, len(self.t) - 1)
        i = min(int(f), len(self.t) - 2)
        u = f - i
        a, b = self.body_q[i], self.body_q[i + 1]
        pos = a[:, :3] * (1 - u) + b[:, :3] * u
        qa, qb = a[:, 3:7], b[:, 3:7].copy()
        qb[(qa * qb).sum(axis=1) < 0] *= -1
        q = qa * (1 - u) + qb * u
        return pos, q / np.linalg.norm(q, axis=1, keepdims=True)

    def track_state(self, t):
        """Recorded track travel per side, in metres, and the seven spring offsets per side, at t."""
        f = np.clip((t - self.t[0]) / self.dt, 0, len(self.t) - 1)
        i = min(int(f), len(self.t) - 2)
        u = f - i
        tr = self.travel[i] * (1 - u) + self.travel[i + 1] * u
        sp = self.spring[i] * (1 - u) + self.spring[i + 1] * u
        return tr, (sp[:ROLLERS], sp[ROLLERS:])

    def smooth(self, t, sigma):
        """The recorded root path, smoothed by a Gaussian. The camera reads this and writes nothing back."""
        n = int(4 * sigma / self.dt)
        i = float(np.clip((t - self.t[0]) / self.dt, 0, len(self.t) - 1))
        idx = np.arange(int(i) - n, int(i) + n + 2)
        w = np.exp(-0.5 * ((idx - i) * self.dt / sigma) ** 2)
        p = self._root[np.clip(idx, 0, len(self.t) - 1)]
        return (p * w[:, None]).sum(axis=0) / w.sum()

    def _advance(self, k):
        """The grid after change frame k. Forward only is cheap; a step back replays from the start."""
        if k < self._k:
            self._s, self._b, self._k = self.s0.copy(), self.b0.copy(), -1
        if k > self._k:
            lo, hi = np.searchsorted(self.df, self._k + 1), np.searchsorted(self.df, k, side="right")
            self._s.ravel()[self.dc[lo:hi]] = self.ds[lo:hi]
            self._b.ravel()[self.dc[lo:hi]] = self.db[lo:hi]
            self._k = k

    def fouling(self, t):
        """Slime and barnacle levels at t, blended between the two nearest 10 Hz grids."""
        k = int(np.searchsorted(self.grid_t, t, side="right")) - 1
        if k < 0:
            return self.s0.copy(), self.b0.copy()
        self._advance(k)
        s, b = self._s.copy(), self._b.copy()
        if k + 1 < len(self.grid_t):
            u = (t - self.grid_t[k]) / (self.grid_t[k + 1] - self.grid_t[k])
            lo, hi = np.searchsorted(self.df, k + 1), np.searchsorted(self.df, k + 1, side="right")
            c = self.dc[lo:hi]
            s.ravel()[c] += (self.ds[lo:hi] - s.ravel()[c]) * u
            b.ravel()[c] += (self.db[lo:hi] - b.ravel()[c]) * u
        return s, b


# Art only: the camera reads a smoothed copy of the record and writes nothing back.
SHOTS = {
    "lane": {"run": "nominal", "t": 203.0, "t0": 196.0, "t1": 209.0, "kind": "follow", "offset0": [1.45, -0.80, -0.40], "offset1": [0.85, -1.05, -0.44], "at": [0.18, 0.05, 0.05], "lens": 28, "fstop": 3.5, "sigma": 1.6},
    "scan": {"run": "nominal", "t": 265.5, "kind": "orbit", "seconds": 16.0, "from_deg": -48.0, "to_deg": 48.0, "radius": 1.5, "eye_z": -1.2, "at": [-0.03, 0.0, -0.05], "lens": 30, "fstop": 16.0},
}


def camera(shot, rec, t, u=0.5):
    """(eye, target, up, focus point, lens, fstop). u runs 0..1 across the shot."""
    if shot["kind"] == "follow":
        root = rec.smooth(t, shot["sigma"])
        v = (t - shot["t0"]) / (shot["t1"] - shot["t0"])
        off = np.array(shot["offset0"]) * (1 - v) + np.array(shot["offset1"]) * v
        eye = np.array([root[0] + off[0], root[1] + off[1], off[2]])
        return eye, root + np.array(shot["at"]), np.array((0.0, 0.0, 1.0)), rec.pose(t)[0][0], shot["lens"], shot["fstop"]
    # A parked robot. The hull is the one flat surface, so the camera's up is away from it and the plate reads as a floor. The arc faces inboard, so the bilge stays out of frame.
    c = rec.pose(shot["t"])[0][0]
    a = np.radians(shot["from_deg"] + (shot["to_deg"] - shot["from_deg"]) * u)
    eye = np.array([c[0] + shot["radius"] * np.sin(a), c[1] + shot["radius"] * np.cos(a), shot["eye_z"]])
    return eye, c + np.array(shot["at"]), np.array((0.0, 0.0, -1.0)), c, shot["lens"], shot["fstop"]


def _loop(spring, n):
    """The track's outer face as a closed path in the chassis frame (x, z): hull-side run toward the rear, round the rear, belly run forward, round the front.

    Returns x, z and the normal's angle about y: 0 faces the hull, +90 degrees faces forward. The hull-side run lifts with the recorded springs."""
    x0, x1 = TRACK_X
    run = x1 - x0
    arc = np.pi * LOOP_R
    total = 2 * run + 2 * arc
    s = (np.arange(n) / n * total) % total
    return s, total, run, arc


def _place(s, total, run, arc, spring):
    x0, x1 = TRACK_X
    s = np.mod(s, total)
    x, z, th = np.zeros_like(s), np.zeros_like(s), np.zeros_like(s)
    a = s < run
    x[a] = x1 - s[a]
    z[a] = CONTACT_Z + np.interp(x[a], ROLLER_XS, spring)
    b = (s >= run) & (s < run + arc)
    ang = (s[b] - run) / LOOP_R
    x[b] = x0 - LOOP_R * np.sin(ang)
    z[b] = IDLER_Z + LOOP_R * np.cos(ang)
    th[b] = -ang
    c = (s >= run + arc) & (s < 2 * run + arc)
    x[c] = x0 + (s[c] - run - arc)
    z[c] = IDLER_Z - LOOP_R
    th[c] = -np.pi
    d = s >= 2 * run + arc
    ang = (s[d] - 2 * run - arc) / LOOP_R
    x[d] = x1 + LOOP_R * np.sin(ang)
    z[d] = IDLER_Z - LOOP_R * np.cos(ang)
    th[d] = np.pi - ang
    return x, z, th


def shoe_poses(travel, spring):
    """Each shoe's (x, z, angle) from the recorded track travel. Forward travel moves the hull-side run rearward relative to the chassis."""
    s, total, run, arc = _loop(spring, SHOES)
    return _place(s + travel, total, run, arc, spring)


def belt_path(spring):
    """The belt as a closed polyline of 72 points, from the same path."""
    s, total, run, arc = _loop(spring, 72)
    x, z, _ = _place(s, total, run, arc, spring)
    return x, z


def path_normals(x, z):
    tx, tz = np.roll(x, -1) - np.roll(x, 1), np.roll(z, -1) - np.roll(z, 1)
    L = np.maximum(np.hypot(tx, tz), 1e-9)
    # The path runs rearward along the hull side, so the outward normal is +z there.
    return tz / L * -1, tx / L * -1


def plume(rec, t, life=7.0, per_unit=1.1, cap=70):
    """Picture only: flakes the drum throws from its open front, from the recorded removal at each moment, drifting with the world's current. The physics never reads this. Same record, same flakes.

    Returns (positions, ages, sizes, source index)."""
    cur = rec.world["current"]
    a = np.radians(cur["dir_deg"])
    drift = np.array((np.cos(a), np.sin(a), 0.0)) * cur["speed_ms"] * 0.55
    step = 5  # 0.1 s of the 50 Hz log
    i1 = int(min(t / rec.dt, len(rec.t) - 1))
    i0 = max(0, i1 - int(life / rec.dt))
    k = rec.labels.index("drum")
    out_p, out_a, out_s = [], [], []
    for i in range(i0 - i0 % step, i1, step):
        n = min(cap, int(rec.removed[i] * per_unit))
        age = t - rec.t[i]
        if n <= 0 or age < 0:
            continue
        rng = np.random.default_rng(i // step)
        c = rec.body_q[i, k, :3]
        x, y, z, w = rec.body_q[i, 0, 3:7]
        fwd = np.array((1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 0.0))
        side = np.array((-fwd[1], fwd[0], 0.0))
        along = rng.uniform(-DRUM_HALF_W, DRUM_HALF_W, n)
        p0 = c + np.outer(along, side) + np.outer(rng.uniform(0.02, DRUM_TIP_R + 0.02, n), fwd) + np.array((0, 0, -c[2] - 0.012))
        v0 = np.outer(rng.uniform(0.25, 0.75, n), fwd) + np.outer(rng.normal(0, 0.14, n), side) + np.array((0, 0, -1.0)) * rng.uniform(0.04, 0.26, (n, 1))
        tau = 0.45
        travel = v0 * tau * (1 - np.exp(-age / tau))
        wob = np.column_stack([np.sin(age * rng.uniform(0.6, 1.8, n) + rng.uniform(0, 6, n)), np.sin(age * rng.uniform(0.6, 1.8, n) + rng.uniform(0, 6, n)), np.sin(age * rng.uniform(0.5, 1.4, n) + rng.uniform(0, 6, n))]) * 0.05 * age ** 0.7
        out_p.append(p0 + travel + drift * age + wob + np.array((0, 0, -0.012)) * age)
        out_a.append(np.full(n, age))
        out_s.append(rng.uniform(0.6, 1.0, n) * rng.choice((1.0, 1.0, 1.0, 2.2), n))
    if not out_p:
        return np.zeros((0, 3)), np.zeros(0), np.zeros(0), np.zeros(0, int)
    p = np.vstack(out_p)
    return p, np.concatenate(out_a), np.concatenate(out_s), np.zeros(len(p), int)
