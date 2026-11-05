"""Reads one exported trial: poses, the dirt grid and the sim's real geometry. Numpy and stdlib only,
so it runs inside Blender's Python. It reads, it never writes to the trial."""
import json
import math
from pathlib import Path

import numpy as np

# Constants copied from policy/highrise/world.py and sim.py. check.py asserts they still match.
BODY_SIDE = 0.36
BODY_HEIGHT = 0.08
RIDE_CLEARANCE = 0.02
TETHER_ATTACH_Z = 0.09
TETHER_DIAMETER_M = 0.006
MULLION_ROUND_R = 0.04
TRANSOM_SPACING = 3.6
ROOF_Z = 160.0
ANCHOR_Y = -0.30
DIRT_CELL_M = 0.05

PAD_CELLS = 6  # record-free ring around the grid, in cells
UPSAMPLE = 8


def catmull(a, k):
    """Separable Catmull-Rom upsample along axis 0. Interpolates the cell centres exactly."""
    n = a.shape[0]
    x = (np.arange(n * k) + 0.5) / k - 0.5
    i = np.floor(x).astype(int)
    t = (x - i)[(...,) + (None,) * (a.ndim - 1)]
    g = lambda j: a[np.clip(j, 0, n - 1)]
    p0, p1, p2, p3 = g(i - 1), g(i), g(i + 1), g(i + 2)
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t)


class Run:
    def __init__(self, trial_dir):
        d = Path(trial_dir)
        self.dir = d
        self.manifest = json.loads((d / "manifest.json").read_text())
        self.world = json.loads((d / "world.json").read_text())
        self.result = json.loads((d / "result.json").read_text())
        q = json.loads((d / "qpos.json").read_text())
        self.hz = q["hz"]
        self.q = np.array(q["frames"], dtype=np.float64)
        di = self.manifest["dirt"]
        self.nx, self.nz, self.every = di["nx"], di["nz"], di["every_steps"]
        self.dirt_rate = self.hz / self.every  # grids per second
        self.scale = di["scale"]
        self.dirt = np.frombuffer((d / "dirt.bin").read_bytes(), dtype=np.uint8).reshape(di["count"], self.nz, self.nx)

        w = self.world
        a = self.area = self.manifest["area"]
        self.mullion_spacing = w["mullion_spacing_m"]
        self.mullion_offset = w["mullion_offset_m"]
        self.mullion_depth = max(w["mullion_depth_m"], 0.0005)
        self.joint_gap = w["joint_gap_m"]
        self.transom_spacing = TRANSOM_SPACING
        self.cap_r = MULLION_ROUND_R
        self.roof_z = ROOF_Z
        self.body_side = BODY_SIDE
        self.body_height = BODY_HEIGHT
        self.ride_clear = RIDE_CLEARANCE
        self.tether_radius = TETHER_DIAMETER_M / 2
        self.frit_m = 0.055
        m = w["edge_margin_m"]
        gx0, gx1 = a["x0"] - m, a["x1"] + m
        self.glass_cx = (gx0 + gx1) / 2
        hw = (gx1 - gx0) / 2
        self.tower_x0, self.tower_x1 = self.glass_cx - hw - 12, self.glass_cx + hw + 12
        self.tower_depth = 28.2
        self.anchor = (self.glass_cx, ANCHOR_Y, ROOF_Z)
        self.film_gain = min(1.4, 0.55 + 0.75 * w["dirt_level"])

        # Cells the export masks to zero (joints). Recover them from the neighbours.
        self.mask = self.dirt[0] == 0
        self.level_ref = max(float(self.dirt[0][~self.mask].mean()) / self.scale, 1e-3)
        p = PAD_CELLS
        self.tex_x0 = a["x0"] - p * DIRT_CELL_M
        self.tex_z0 = a["z0"] - p * DIRT_CELL_M
        self.tex_w = (self.nx + 2 * p) * DIRT_CELL_M
        self.tex_h = (self.nz + 2 * p) * DIRT_CELL_M
        self.tex_px_w = (self.nx + 2 * p) * UPSAMPLE
        self.tex_px_h = (self.nz + 2 * p) * UPSAMPLE
        self._cache = {}
        wind_file = d / "wind.json"
        self.wind = np.array(json.loads(wind_file.read_text())) if wind_file.exists() else None

    # ---- recorded wind, used only to move scenery haze

    def wind_run(self, t0, t):
        """Metres of air that passed between t0 and t, from the recorded wind speed at the sim's rate."""
        if self.wind is None:
            return max(self.world["steady_wind_ms"], 1.0) * (t - t0)
        i0, i1 = int(np.clip(t0 * self.hz, 0, len(self.wind))), int(np.clip(t * self.hz, 0, len(self.wind)))
        return float(self.wind[i0:i1].sum()) / self.hz

    # ---- poses

    def pose(self, t):
        """Recorded pose at time t. Between 20 Hz samples: linear position, normalised linear quaternion."""
        f = float(np.clip(t * self.hz, 0, len(self.q) - 1))
        i = min(int(f), len(self.q) - 2)
        u = f - i
        a, b = self.q[i], self.q[i + 1]
        pos = a[:3] * (1 - u) + b[:3] * u
        qa, qb = a[3:7], b[3:7]
        if np.dot(qa, qb) < 0:
            qb = -qb
        quat = qa * (1 - u) + qb * u
        quat = quat / np.linalg.norm(quat)
        return tuple(float(x) for x in pos), tuple(float(x) for x in quat)

    # ---- dirt

    def _grid(self, k):
        """One recorded grid as level relative to the run's mean start level, with masked cells filled."""
        k = int(np.clip(k, 0, len(self.dirt) - 1))
        if k in self._cache:
            return self._cache[k]
        g = self.dirt[k].astype(np.float32) / self.scale / self.level_ref
        # The mask stays zero in the export, so fill each masked cell along rows, then along columns.
        m = self.mask
        for axis in (1, 0):
            h = np.moveaxis(g, axis, 1)
            mm = np.moveaxis(m, axis, 1)
            cols = np.where(mm.all(axis=0))[0]
            good = np.where(~mm.all(axis=0))[0]
            for c in cols:
                lo = good[good < c]
                hi = good[good > c]
                if len(lo) and len(hi):
                    a, b = lo[-1], hi[0]
                    u = (c - a) / (b - a)
                    h[:, c] = h[:, a] * (1 - u) + h[:, b] * u
                elif len(lo):
                    h[:, c] = h[:, lo[-1]]
                elif len(hi):
                    h[:, c] = h[:, hi[0]]
        # Ring outside the assigned area. The record stops here, so it returns to a full film.
        p = PAD_CELLS
        out = np.ones((self.nz + 2 * p, self.nx + 2 * p), np.float32)
        out[p:-p, p:-p] = g
        for layer in range(p):
            fade = (layer + 1) / p
            def edge(v):
                # A wiped edge cell stays a wiped edge: the first outside cell is at full film.
                return np.where(v < 0.5, 1.0, v * (1 - fade) + fade)
            out[p - 1 - layer, p:-p] = edge(g[0, :])
            out[-p + layer, p:-p] = edge(g[-1, :])
            out[p:-p, p - 1 - layer] = edge(g[:, 0])
            out[p:-p, -p + layer] = edge(g[:, -1])
        up = catmull(out, UPSAMPLE)
        up = np.moveaxis(catmull(np.moveaxis(up, 1, 0), UPSAMPLE), 0, 1)
        up = np.clip(up, 0, 3).astype(np.float32)
        if len(self._cache) > 4:
            self._cache.pop(next(iter(self._cache)))
        self._cache[k] = up
        return up

    def dirt_image(self, t):
        """Blend of the two recorded grids around t, as a texture. Grids are one second apart."""
        f = max(t * self.dirt_rate, 0.0)
        k = int(f)
        u = f - k
        a, b = self._grid(k), self._grid(k + 1)
        return a * (1 - u) + b * u

    def coverage(self, t):
        k = int(np.clip(t * self.dirt_rate, 0, len(self.dirt) - 1))
        g = self.dirt[k]
        thr = self.manifest["dirt"]["clean_below"] * self.scale
        return float((g[~self.mask] <= thr).mean())
