"""Reads one recorded inspection run and holds the shot list. Numpy and stdlib only, so it runs inside Blender's Python too. It only reads.

The record is policy/packs/inspection/out/<run>.npz (body poses at 50 Hz, the world) and <run>.replay.json.gz (the solids and scenery lists).
"""
import gzip
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "policy" / "packs" / "inspection" / "out"
ROBOT = ROOT / "public" / "robots" / "anymal_c"


def run_path(run):
    p = Path(run)
    return p if p.suffix == ".npz" else OUT / f"{run}.npz"


class Record:
    def __init__(self, run):
        path = run_path(run)
        if not path.exists():
            raise SystemExit(f"no recorded run at {path}")
        self.name = path.stem
        d = np.load(path)
        self.t = d["t"].astype(np.float64)
        self.body_q = d["body_q"].astype(np.float64)
        self.meta = json.loads(str(d["meta"]))
        self.labels = self.meta["body_labels"]
        with gzip.open(path.parent / f"{path.stem}.replay.json.gz") as f:
            replay = json.load(f)
        self.solids = replay["solids"]
        self.scenery = replay["scenery"]
        self.result = replay["result"]
        self.world = self.meta["world"]
        self.dt = float(np.median(np.diff(self.t)))
        self._root = self.body_q[:, 0, :3]

    def pose(self, t):
        """All bodies at time t. Between 50 Hz samples: linear position, normalised linear quaternion. Time outside the record raises: nothing is invented after it ends."""
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

    def smooth(self, t, sigma):
        """The recorded root path, smoothed by a Gaussian. The camera reads this and writes nothing back."""
        n = int(4 * sigma / self.dt)
        i = float(np.clip((t - self.t[0]) / self.dt, 0, len(self.t) - 1))
        idx = np.arange(int(i) - n, int(i) + n + 2)
        w = np.exp(-0.5 * ((idx - i) * self.dt / sigma) ** 2)
        p = self._root[np.clip(idx, 0, len(self.t) - 1)]
        return (p * w[:, None]).sum(axis=0) / w.sum()


# eye: fixed world point, or offset from the smoothed root ("follow"), keyed in time. at: offset from the smoothed root. Art only.
SHOTS = {
    "plant": {"run": "plant", "t": 17.6, "eye": [4.3, 2.72, 1.2], "at": [0.7, 0.45, 0.55], "lens": 30, "fstop": 2.8, "sigma": 0.35},
    "low_pipe": {"run": "low_pipe", "t": 5.0, "eye": [5.5, -1.35, 0.8], "at": [-0.2, 0.15, 0.1], "lens": 35, "fstop": 2.8, "sigma": 0.2},
    "leak_corner": {"run": "leak_corner", "t": 7.3, "eye": [6.45, -1.35, 0.6], "at": [0.0, 0.0, 0.05], "lens": 35, "fstop": 4.5, "sigma": 0.2},
    "dropped_tray": {"run": "dropped_tray", "t": 17.6, "eye": [5.1, 1.15, 1.3], "at": [-0.15, 0.1, 0.0], "lens": 35, "fstop": 2.8, "sigma": 0.25},
    # Clips: t0..t1 of the record. A rear three-quarter chase that keeps inside the walkway.
    "plant_route": {"run": "plant", "t0": 0.1, "t1": 21.0, "follow": [[0.0, -2.9, -1.25, 1.05], [5.0, -2.8, -1.25, 1.0], [8.0, -1.25, -2.9, 1.0], [12.0, -1.1, -3.0, 1.0], [15.5, -2.9, -1.3, 1.0], [21.0, -2.9, -1.3, 1.0]],
                    "follow_sigma": 1.0, "at": [0.25, 0.05, -0.1], "lens": 32, "fstop": 2.8, "sigma": 1.0},
    "fall": {"run": "low_pipe", "t0": 2.2, "t1": 8.2, "eye": [5.5, -1.35, 0.8], "at": [-0.2, 0.15, 0.1], "lens": 35, "fstop": 2.8, "sigma": 0.45},
}


def camera(shot, rec, t):
    """(eye, target, focus point, lens, fstop) at t, from the smoothed recorded root."""
    root = rec.smooth(t, shot["sigma"])
    target = root + np.array(shot["at"])
    if "follow" in shot:
        keys = np.array(shot["follow"])
        s = shot["follow_sigma"]
        ts = np.linspace(t - 3 * s, t + 3 * s, 61)
        w = np.exp(-0.5 * ((ts - t) / s) ** 2)
        off = np.array([(np.interp(ts, keys[:, 0], keys[:, k]) * w).sum() / w.sum() for k in (1, 2, 3)])
        eye = np.array([root[0] + off[0], root[1] + off[1], off[2]])
    else:
        eye = np.array(shot["eye"], dtype=float)
    return eye, target, root, shot["lens"], shot["fstop"]
