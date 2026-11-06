"""Runs one hull world and records it: MuJoCo at 500 Hz, control at 50 Hz, fouling at 20 Hz. All randomness comes from the seed.

MuJoCo does contacts, fluid drag (density, viscosity, wind as the current) and rigid bodies. This file adds what it cannot: magnet force with an air gap,
buoyancy, bristle preload, tether pull and the fouling grid. PARAMETERS.md lists every value. Results are simulated and not calibrated.
"""
import hashlib
import json
import math
import pathlib
import time

import mujoco
import numpy as np

from . import controller as C
from . import model as M
from . import world as W

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ("world.py", "model.py", "controller.py", "sim.py", "judge.py")
NOTE = "Simulated. Simplified physics. Every value is an assumption, and nothing is checked against a real ship or robot."
CONTROL_EVERY = 10
FOUL_EVERY = 25
GRID_EVERY = 5  # fouling frames per delta: 10 Hz
CELL_M = 0.02
GRID_X = W.PLATE_X
GRID_Y = W.PLATE_Y
# Friction, track shoe on steel.
MU_PAINT = 0.55
MU_SLIME = 0.25
MU_BARNACLE = 0.40
# Fouling thickness added to the magnet gap.
SLIME_GAP_M = 0.001
BARNACLE_GAP_M = 0.005
# Bristles on the drum.
BRISTLE_K = 8000.0  # N/m of tip compression, over the drum's width
BRISTLE_MU = 0.25
BRISTLE_LOAD_NM = (1.0, 3.0)  # dry-running torque and extra at full fouling
SLIME_RATE = 16.0  # 1/s, exponential
BARNACLE_RATE = 7.0  # level/s, linear
NOMINAL_COMPRESSION_M = 0.012
CLEAN_LEVEL = 0.15
# Tether.
TETHER_PRELOAD_N = 8.0
TETHER_EXPOSED_M = 6.0
TETHER_D_M = 0.016
TETHER_CD = 1.2
TETHER_ANCHOR = (3.0, -25.0, -6.0)
TETHER_LOCAL = (-0.31, 0.0, -0.03)
# Sensors.
FIX_HZ = 5
FIX_NOISE_M = 0.02
HEADING_NOISE_RAD = 0.005
# Detach: every contact point this far from the plate, held.
DETACH_GAP_M = 0.04
DETACH_HOLD_S = 0.2
AFTER_DETACH_S = 3.0
GRAVITY = 9.81


def code_label():
    digest = hashlib.sha256(b"".join((HERE / name).read_bytes() for name in SOURCES)).hexdigest()
    return f"sim packs/hull {digest[:12]}"


def _fbm(shape, cells, rng):
    """Band-limited noise from the FFT, about -1..1."""
    ny, nx = shape
    fy, fx = np.meshgrid(np.fft.fftfreq(ny) * max(nx, ny), np.fft.rfftfreq(nx) * max(nx, ny), indexing="ij")
    r = np.hypot(fx, fy)
    spec = (rng.normal(size=r.shape) + 1j * rng.normal(size=r.shape)) * np.exp(-(r / cells) ** 2) * (r > 0.5)
    a = np.fft.irfft2(spec, s=shape)
    return a / (a.std() * 2.5)


def grid_shape():
    return round((GRID_Y[1] - GRID_Y[0]) / CELL_M), round((GRID_X[1] - GRID_X[0]) / CELL_M)


def cell_centres():
    ny, nx = grid_shape()
    return GRID_X[0] + (np.arange(nx) + 0.5) * CELL_M, GRID_Y[0] + (np.arange(ny) + 0.5) * CELL_M


def seam_height_map(world):
    """How far the steel stands below the plate at each cell: the bead's circular section."""
    xs, ys = cell_centres()
    h = np.zeros(grid_shape())
    bead = world["seam"]["height_m"]
    if bead <= 0:
        return h
    half = math.sqrt(max(0.0, M.SEAM_R ** 2 - (M.SEAM_R - bead) ** 2))
    prof = lambda d: np.where(np.abs(d) < half, np.sqrt(np.maximum(M.SEAM_R ** 2 - d ** 2, 0)) - (M.SEAM_R - bead), 0.0)
    for x in W.TRANSVERSE_SEAMS_X:
        h = np.maximum(h, prof(xs - x)[None, :])
    for y in W.LONGITUDINAL_SEAMS_Y:
        h = np.maximum(h, prof(ys - y)[:, None])
    return h


def initial_fouling(world, seed):
    """Slime and barnacle levels, 0..1, from the seed. Barnacles gather in patches and along weld beads."""
    rng = np.random.default_rng(seed + 1000)
    shape = grid_shape()
    f = world["fouling"]
    slime = np.clip(f["slime"] * (1.0 + 0.35 * _fbm(shape, 14, rng) + 0.12 * _fbm(shape, 60, rng)), 0, 1)
    patches = _fbm(shape, 22, rng) + 0.35 * _fbm(shape, 70, rng)
    xs, ys = cell_centres()
    d = np.min([np.abs(xs - x) for x in W.TRANSVERSE_SEAMS_X], axis=0)[None, :]
    d = np.minimum(d, np.min([np.abs(ys - y) for y in W.LONGITUDINAL_SEAMS_Y], axis=0)[:, None])
    near_seam = np.exp(-d / 0.08)
    barn = np.clip(f["barnacle"] * (1.0 + 1.6 * patches + 0.8 * near_seam), 0, 1)
    return slime.astype(np.float32), barn.astype(np.float32)


class Sim:
    def __init__(self, world, seed):
        self.world, self.seed = world, seed
        self.m = M.load_model(world)
        self.d = mujoco.MjData(self.m)
        self.rng = np.random.default_rng(seed)
        self.slime, self.barn = initial_fouling(world, seed)
        self.slime0, self.barn0 = self.slime.copy(), self.barn.copy()
        self.seam_h = seam_height_map(world)
        self.xs, self.ys = cell_centres()
        body = lambda n: mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, n)
        geom = lambda n: mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, n)
        joint = lambda n: mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_JOINT, n)
        self.chassis = body("chassis")
        self.rollers = [body(n) for n in (*M.LEFT, *M.RIGHT)]
        self.roller_geoms = [geom(n) for n in (*M.LEFT, *M.RIGHT)]
        self.drum = body(M.DRUM)
        self.bodies = [body(n) for n in M.BODIES]
        self.roller_dof = [self.m.jnt_dofadr[joint(n)] for n in (*M.LEFT, *M.RIGHT)]
        self.roller_qpos = [self.m.jnt_qposadr[joint(n)] for n in (*M.LEFT, *M.RIGHT)]
        self.spring_qpos = [self.m.jnt_qposadr[joint(n + "_s")] for n in (*M.LEFT, *M.RIGHT)]
        self.drum_dof = self.m.jnt_dofadr[joint(M.DRUM)]
        self.buoyancy = world["water"]["density"] * M.VOLUME_M3 * GRAVITY
        c = world["current"]
        a = math.radians(c["dir_deg"])
        self.current_speed = c["speed_ms"]
        self.current_dir = np.array((math.cos(a), math.sin(a), 0.0))
        self.tether_q = 0.5 * world["water"]["density"] * TETHER_CD * TETHER_D_M * TETHER_EXPOSED_M
        self.mag = world["magnet"]
        self.controller = C.Lawnmower(world["patch"], M.start_pose(world))
        n = len(self.rollers)
        self.gaps = np.zeros(n)
        self.mag_n = np.zeros(n)
        self.mu = np.full(n, MU_PAINT)
        self.touch = 0.0
        self.removed = 0.0
        self.fix = None
        self.steps = 0
        self.cmd = (0.0, 0.0, 0.0)
        mujoco.mj_forward(self.m, self.d)

    def _cell(self, x, y):
        ny, nx = self.slime.shape
        return min(max(int((y - GRID_Y[0]) / CELL_M), 0), ny - 1), min(max(int((x - GRID_X[0]) / CELL_M), 0), nx - 1)

    def _forces(self):
        d = self.d
        d.xfrc_applied[:] = 0.0
        d.qfrc_applied[:] = 0.0
        # Magnets: each track's force shared along its contact points, with an air-gap falloff and the fouling under the point in the gap.
        share = self.mag["force_n"] / M.ROLLERS
        for i, b in enumerate(self.rollers):
            p = d.xpos[b]
            iy, ix = self._cell(p[0], p[1])
            s, br = float(self.slime[iy, ix]), float(self.barn[iy, ix])
            gap = max(0.0, -(p[2] + M.ROLLER_R))
            total = gap + SLIME_GAP_M * s + BARNACLE_GAP_M * br
            f = share / (1.0 + total / self.mag["gap_scale_m"]) ** 2
            self.gaps[i], self.mag_n[i] = gap, f
            d.xfrc_applied[b, 2] += f
            mu = (MU_PAINT * (1 - s) + MU_SLIME * s) * (1 - br) + MU_BARNACLE * br
            self.mu[i] = mu
            self.m.geom_friction[self.roller_geoms[i], 0] = mu
        # Bristle preload and drag, from the tip circle's reach at three points along the drum.
        p, R_d = d.xpos[self.drum], d.xmat[self.chassis].reshape(3, 3)
        comp_sum, level = 0.0, 0.0
        for off in (-0.16, 0.0, 0.16):
            q = p + R_d[:, 1] * off
            iy, ix = self._cell(q[0], q[1])
            comp_sum += max(0.0, q[2] + M.DRUM_TIP_R + float(self.seam_h[iy, ix]))
            level += 0.5 * float(self.slime[iy, ix]) + 0.5 * float(self.barn[iy, ix])
        comp = comp_sum / 3.0
        f = BRISTLE_K * comp
        self.touch = comp
        d.xfrc_applied[self.drum, 2] -= f
        w = d.qvel[self.drum_dof]
        # The rim runs faster than the robot, so bristle friction on the plate pulls against the rim's direction.
        drag = BRISTLE_MU * f * min(1.0, abs(w) / 2.0)
        sign = math.copysign(1.0, w)
        d.xfrc_applied[self.drum, 0] -= sign * drag * R_d[0, 0]
        d.xfrc_applied[self.drum, 1] -= sign * drag * R_d[1, 0]
        load = BRISTLE_LOAD_NM[0] + BRISTLE_LOAD_NM[1] * level / 3.0 + drag * M.DRUM_TIP_R if comp > 0 else 0.0
        d.qfrc_applied[self.drum_dof] = -math.copysign(min(1.0, abs(w) / 0.5) * load, w)
        # Buoyancy at the centre of buoyancy; tether pull at the rear boot.
        R = d.xmat[self.chassis].reshape(3, 3)
        cob = d.xpos[self.chassis] + R @ np.array(M.BUOY_LOCAL)
        mujoco.mj_applyFT(self.m, d, np.array((0, 0, self.buoyancy)), np.zeros(3), cob, self.chassis, d.qfrc_applied)
        boot = d.xpos[self.chassis] + R @ np.array(TETHER_LOCAL)
        u = np.array(TETHER_ANCHOR) - boot
        # The exposed tether drags on the water it moves relative to, so its pull fades once the robot moves with the current.
        relative = max(0.0, self.current_speed - float(d.qvel[:3] @ self.current_dir))
        pull = TETHER_PRELOAD_N * u / np.linalg.norm(u) + self.tether_q * relative * relative * self.current_dir
        mujoco.mj_applyFT(self.m, d, pull, np.zeros(3), boot, self.chassis, d.qfrc_applied)

    def _clean(self, dt):
        """Removes fouling only at cells inside the drum's rectangle where the bristle circle reaches the steel."""
        d = self.d
        p, R_d = d.xpos[self.drum], d.xmat[self.chassis].reshape(3, 3)
        fwd, axis, up = R_d[:, 0], R_d[:, 1], R_d[:, 2]
        reach = math.hypot(M.DRUM_HALF_W, M.DRUM_TIP_R) + CELL_M
        ix0, ix1 = np.searchsorted(self.xs, p[0] - reach), np.searchsorted(self.xs, p[0] + reach)
        iy0, iy1 = np.searchsorted(self.ys, p[1] - reach), np.searchsorted(self.ys, p[1] + reach)
        self.removed = 0.0
        if ix1 <= ix0 or iy1 <= iy0:
            return
        h = self.seam_h[iy0:iy1, ix0:ix1]
        dx = self.xs[ix0:ix1][None, :] - p[0]
        dy = self.ys[iy0:iy1][:, None] - p[1]
        dz = -h - p[2]
        xd = fwd[0] * dx + fwd[1] * dy + fwd[2] * dz
        yd = axis[0] * dx + axis[1] * dy + axis[2] * dz
        zd = up[0] * dx + up[1] * dy + up[2] * dz
        comp = M.DRUM_TIP_R - np.sqrt(xd * xd + zd * zd)
        rate = np.clip(comp / NOMINAL_COMPRESSION_M, 0, 1) * (np.abs(yd) <= M.DRUM_HALF_W) * min(1.0, abs(d.qvel[self.drum_dof]) / C.BRUSH_RATE)
        s, br = self.slime[iy0:iy1, ix0:ix1], self.barn[iy0:iy1, ix0:ix1]
        ds = s * (1.0 - np.exp(-SLIME_RATE * rate * dt))
        db = np.minimum(br, BARNACLE_RATE * rate * dt)
        self.removed = float(ds.sum() + db.sum())
        s -= ds.astype(np.float32)
        br -= db.astype(np.float32)

    def _obs(self):
        d = self.d
        R = d.xmat[self.chassis].reshape(3, 3)
        heading = math.atan2(R[1, 0], R[0, 0]) + float(self.rng.normal(0, HEADING_NOISE_RAD))
        fix = None
        if self.steps % int(1 / (M.TIMESTEP * FIX_HZ)) == 0:
            fix = (d.xpos[self.chassis][0] + float(self.rng.normal(0, FIX_NOISE_M)), d.xpos[self.chassis][1] + float(self.rng.normal(0, FIX_NOISE_M)))
        return {"heading": heading, "fix": fix, "track_rate": [float(np.mean([d.qvel[a] for a in self.roller_dof[:M.ROLLERS]])), float(np.mean([d.qvel[a] for a in self.roller_dof[M.ROLLERS:]]))]}

    def control(self):
        dt = M.TIMESTEP * CONTROL_EVERY
        vl, vr, brush = self.controller.command(self._obs(), dt)
        self.cmd = (vl, vr, brush)
        self.d.ctrl[:M.ROLLERS] = vl / M.ROLLER_R
        self.d.ctrl[M.ROLLERS:2 * M.ROLLERS] = vr / M.ROLLER_R
        self.d.ctrl[2 * M.ROLLERS] = brush

    def step(self):
        if self.steps % CONTROL_EVERY == 0:
            self.control()
        self._forces()
        mujoco.mj_step(self.m, self.d)
        self.steps += 1

    @property
    def t(self):
        return self.steps * M.TIMESTEP


def run(world, *, seed=0, out=None):
    world = W.validate(world)
    sim = Sim(world, seed)
    d = sim.d
    log = {k: [] for k in ("t", "body_q", "track_speed", "track_travel", "spring", "drum_rate", "gap", "magnet_n", "mu", "chassis_vel", "touch", "removed")}
    q8 = lambda a: np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    last_s, last_b = q8(sim.slime), q8(sim.barn)
    delta_frame, delta_cell, delta_s, delta_b, delta_t = [], [], [], [], []
    detached_t = None
    held_from = None
    sim_failed = False
    max_steps = round(world["time_limit_s"] / M.TIMESTEP)
    started = time.perf_counter()
    n_foul = 0
    while sim.steps < max_steps:
        sim.step()
        if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all():
            sim_failed = True
            break
        if sim.steps % FOUL_EVERY == 0:
            sim._clean(FOUL_EVERY * M.TIMESTEP)
            n_foul += 1
            if n_foul % GRID_EVERY == 0:
                ns, nb = q8(sim.slime), q8(sim.barn)
                changed = np.flatnonzero((ns != last_s).ravel() | (nb != last_b).ravel())
                if len(changed):
                    delta_frame.append(np.full(len(changed), len(delta_t), np.int32))
                    delta_cell.append(changed.astype(np.int32))
                    delta_s.append(ns.ravel()[changed])
                    delta_b.append(nb.ravel()[changed])
                    last_s, last_b = ns, nb
                delta_t.append(sim.t)
        if sim.steps % CONTROL_EVERY == 0:
            log["t"].append(sim.t)
            q = np.zeros((len(sim.bodies), 7))
            q[:, :3] = d.xpos[sim.bodies]
            q[:, 3:6], q[:, 6] = d.xquat[sim.bodies][:, 1:], d.xquat[sim.bodies][:, 0]
            log["body_q"].append(q)
            rates = np.array([d.qvel[a] for a in sim.roller_dof]) * M.ROLLER_R
            angles = np.array([d.qpos[a] for a in sim.roller_qpos]) * M.ROLLER_R
            log["track_speed"].append((rates[:M.ROLLERS].mean(), rates[M.ROLLERS:].mean()))
            log["track_travel"].append((angles[:M.ROLLERS].mean(), angles[M.ROLLERS:].mean()))
            log["spring"].append([d.qpos[a] for a in sim.spring_qpos])
            log["drum_rate"].append(d.qvel[sim.drum_dof])
            log["gap"].append(sim.gaps.copy())
            log["magnet_n"].append(sim.mag_n.copy())
            log["mu"].append(sim.mu.copy())
            log["chassis_vel"].append(d.qvel[:6].copy())
            log["touch"].append(sim.touch)
            log["removed"].append(sim.removed)
        if (sim.gaps > DETACH_GAP_M).all():
            held_from = sim.t if held_from is None else held_from
            if detached_t is None and sim.t - held_from >= DETACH_HOLD_S:
                detached_t = held_from
        else:
            held_from = None
        if detached_t is not None and sim.t - detached_t >= AFTER_DETACH_S:
            break
        if sim.controller.done:
            break
    wall = time.perf_counter() - started
    rec = {
        "t": np.asarray(log["t"], np.float64),
        "track_travel": np.asarray(log["track_travel"], np.float64),
        "body_q": np.asarray(log["body_q"], np.float32),
        "sim_failed": np.array(sim_failed),
        "fouling0_slime": q8(sim.slime0),
        "fouling0_barnacle": q8(sim.barn0),
        "grid_t": np.asarray(delta_t, np.float64),
        "delta_frame": np.concatenate(delta_frame) if delta_frame else np.zeros(0, np.int32),
        "delta_cell": np.concatenate(delta_cell) if delta_cell else np.zeros(0, np.int32),
        "delta_slime": np.concatenate(delta_s) if delta_s else np.zeros(0, np.uint8),
        "delta_barnacle": np.concatenate(delta_b) if delta_b else np.zeros(0, np.uint8),
        **{k: np.asarray(log[k], np.float32) for k in ("track_speed", "spring", "drum_rate", "gap", "magnet_n", "mu", "chassis_vel", "touch", "removed")},
    }
    meta = {
        "label": code_label(), "note": NOTE, "robot": "hull_crawler", "world": world, "physics_hash": W.physics_hash(world), "seed": seed, "sim_failed": sim_failed, "body_labels": list(M.BODIES),
        "cell_m": CELL_M, "grid_x": list(GRID_X), "grid_y": list(GRID_Y), "clean_level": CLEAN_LEVEL, "control_dt_s": M.TIMESTEP * CONTROL_EVERY, "physics_hz": round(1 / M.TIMESTEP),
        "wall_s": wall, "rtf": sim.t / wall, "total_mass_kg": float(sim.m.body_mass.sum()), "buoyancy_n": sim.buoyancy,
    }
    rec["meta"] = np.array(json.dumps(meta))
    if out is not None:
        out = pathlib.Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, **rec)
    return rec, meta


def load(path):
    with np.load(path, allow_pickle=False) as data:
        rec = {k: data[k] for k in data.files}
    return rec, json.loads(str(rec["meta"]))


def final_fouling(rec):
    """The recorded grid at the record's end, from the start grid and its changes."""
    s, b = rec["fouling0_slime"].copy(), rec["fouling0_barnacle"].copy()
    s.ravel()[rec["delta_cell"]] = rec["delta_slime"]
    b.ravel()[rec["delta_cell"]] = rec["delta_barnacle"]
    return s / 255.0, b / 255.0


def record_hash(rec):
    h = hashlib.sha256()
    for k in sorted(rec):
        if k != "meta":
            h.update(k.encode())
            h.update(np.asarray(rec[k]).tobytes())
    return h.hexdigest()


def replay(rec, meta, result=None):
    """JSON-ready. A frame is every body's x, y, z, qx, qy, qz, qw in a flat list. Stride 5 of the 50 Hz log."""
    world = meta["world"]
    frames = [{"t": round(float(rec["t"][i]), 3), "q": np.round(rec["body_q"][i].astype(np.float64).ravel(), 4).tolist()} for i in range(0, len(rec["t"]), 5)]
    solids = [{"name": n, "type": "capsule", "pos": list(c), "axis": axis, "size": [M.SEAM_R, half], "material": "weld"} for n, c, half, axis in M.seams(world)]
    return {
        "format": "robot-pack-replay/1", "pack": "hull", "robot": meta["robot"], "label": meta["label"], "note": meta["note"], "simulated": True, "fps": 10, "body_labels": meta["body_labels"],
        "pose_layout": ["x", "y", "z", "qx", "qy", "qz", "qw"], "patch": world["patch"], "solids": solids, "scenery": [], "result": result, "frames": frames,
    }
