"""Runs one world and records it: 200 Hz physics, 50 Hz control, on this Mac's CPU. replay() turns a record into JSON that a browser can play.

The same solver and rates as newton/examples/robot/example_robot_policy.py. The seed sets a small start noise on the joints. Results are simulated.
"""
import hashlib
import json
import math
import pathlib
import time

import numpy as np

import newton

from . import controller as C
from . import model as M
from . import world as W

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ("world.py", "model.py", "controller.py", "sim.py", "judge.py")
NOTE = "Simulated. The policy is upstream's and unchecked against a real robot. Not calibrated."
PHYSICS_HZ = 200
DECIMATION = 4
POLICY_DT = DECIMATION / PHYSICS_HZ
SEED_JOINT_NOISE_RAD = 0.02
NCONMAX = 80
NJMAX = 320
SETTLE_AFTER_DONE_S = 2.0
REPLAY_STRIDE = 2


def code_label():
    digest = hashlib.sha256(b"".join((HERE / name).read_bytes() for name in SOURCES)).hexdigest()
    return f"sim packs/inspection {digest[:12]}"


def _yaw(q):
    return math.atan2(2.0 * (q[6] * q[5] + q[3] * q[4]), 1.0 - 2.0 * (q[4] * q[4] + q[5] * q[5]))


def run(world, *, seed=0, out=None):
    world = W.validate(world)
    model, cfg = M.load_model(world)
    solver = newton.solvers.SolverMuJoCo(model, use_mujoco_cpu=False, solver="newton", nconmax=NCONMAX, njmax=NJMAX)
    s0, s1 = model.state(), model.state()
    control = model.control()
    pipeline = newton.CollisionPipeline(model, rigid_contact_max=solver.get_max_contact_count(), soft_contact_max=0)
    contacts = pipeline.contacts()
    observables = solver.observables(contacts=contacts, kinds={solver.ObservableKind.CONTACT_F})

    q = s0.joint_q.numpy().copy()
    q0 = q[7:].copy()
    q[7:] += np.random.default_rng(seed).uniform(-SEED_JOINT_NOISE_RAD, SEED_JOINT_NOISE_RAD, size=len(q0))
    s0.joint_q.assign(q)
    newton.eval_fk(model, s0.joint_q, s0.joint_qd, s0)

    follower = C.RouteFollower(world["route"]["waypoints"])
    policy = C.WalkPolicy(M.policy_path(), q0, cfg["action_scale"])

    labels = model.shape_label
    obstacle = np.array(["obj:" in lb for lb in labels])
    ground = np.array([lb.endswith("ground") for lb in labels])
    foot_shape = {i: f for i, lb in enumerate(labels) for f, name in enumerate(M.FEET) if f"{name}/collisions" in lb}
    body_labels = [lb.rsplit("/", 1)[-1] for lb in model.body_label]
    base = body_labels.index(M.BASE)
    foot_body = [body_labels.index(name) for name in M.FEET]

    log = {k: [] for k in ("t", "body_q", "body_qd", "joint_q", "command", "object_f", "ground_f", "body_on_ground_f", "feet")}
    peak_nacon = peak_nefc = 0
    steps = round(world["route"]["time_limit_s"] / POLICY_DT)
    done_at = None
    sim_failed = False
    started = time.perf_counter()
    for k in range(steps):
        q, qd = s0.joint_q.numpy(), s0.joint_qd.numpy()
        command = follower.command(float(q[0]), float(q[1]), _yaw(q))
        target = np.zeros(model.joint_coord_count, dtype=np.float32)
        target[7:] = policy.targets(q, qd, command)
        control.joint_target_q.assign(target)
        for _ in range(DECIMATION):
            s0.clear_forces()
            solver.step(s0, s1, control, contacts, 1.0 / PHYSICS_HZ, observables=observables)
            s0, s1 = s1, s0
        body_q = s0.body_q.numpy().copy()
        if not np.isfinite(body_q).all():
            sim_failed = True
            break

        count = int(contacts.rigid_contact_count.numpy()[0])
        a, b = contacts.rigid_contact_shape0.numpy()[:count], contacts.rigid_contact_shape1.numpy()[:count]
        force = np.linalg.norm(observables.contact_f.numpy()[:count, :3], axis=1)
        hit, floor = obstacle[a] | obstacle[b], ground[a] | ground[b]
        feet = np.zeros(len(M.FEET), dtype=bool)
        off_feet = 0.0
        for i, j, f, on_floor in zip(a, b, force, floor):
            foot = foot_shape.get(int(i), foot_shape.get(int(j)))
            if foot is not None:
                feet[foot] = True
            elif on_floor:
                off_feet += float(f)
        log["t"].append((k + 1) * POLICY_DT)
        log["body_q"].append(body_q)
        log["body_qd"].append(s0.body_qd.numpy().copy())
        log["joint_q"].append(s0.joint_q.numpy().copy())
        log["command"].append(command)
        log["object_f"].append(float(force[hit].sum()))
        log["ground_f"].append(float(force[floor].sum()))
        log["body_on_ground_f"].append(off_feet)
        log["feet"].append(feet)
        peak_nacon = max(peak_nacon, int(solver.mjw_data.nacon.numpy().max()))
        peak_nefc = max(peak_nefc, int(solver.mjw_data.nefc.numpy().max()))
        if follower.done and done_at is None:
            done_at = k
        if done_at is not None and (k - done_at) * POLICY_DT >= SETTLE_AFTER_DONE_S:
            break
    wall = time.perf_counter() - started
    body_q = np.asarray(log["body_q"], dtype=np.float32)
    body_qd = np.asarray(log["body_qd"], dtype=np.float32)
    rec = {
        "t": np.asarray(log["t"], dtype=np.float32),
        "body_q": body_q,
        "body_qd": body_qd,
        "joint_q": np.asarray(log["joint_q"], dtype=np.float32),
        "base_q": body_q[:, base],
        "command": np.asarray(log["command"], dtype=np.float32),
        "foot_v_xy": np.linalg.norm(body_qd[:, foot_body, :2], axis=2),
        "feet": np.asarray(log["feet"], dtype=bool),
        "sim_failed": np.array(sim_failed),
        **{k: np.asarray(log[k], dtype=np.float32) for k in ("object_f", "ground_f", "body_on_ground_f")},
    }
    meta = {
        "label": code_label(), "note": NOTE, "robot": "anymal_c", "world": world, "physics_hash": W.physics_hash(world), "seed": seed, "sim_failed": sim_failed,
        "policy_dt_s": POLICY_DT, "physics_hz": PHYSICS_HZ, "wall_s": wall, "rtf": len(log["t"]) * POLICY_DT / wall, "peak_nacon": peak_nacon, "peak_nefc": peak_nefc,
        "nconmax": NCONMAX, "njmax": NJMAX, "body_labels": body_labels, "body_parents": _body_parents(model), "total_mass_kg": float(model.body_mass.numpy().sum()), "shapes": model.shape_count,
    }
    rec["meta"] = np.array(json.dumps(meta))
    if out is not None:
        out = pathlib.Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, **rec)
    return rec, meta


def _body_parents(model):
    parents = [-1] * model.body_count
    for parent, child in zip(model.joint_parent.numpy(), model.joint_child.numpy()):
        parents[int(child)] = int(parent)
    return parents


def load(path):
    with np.load(path, allow_pickle=False) as data:
        rec = {k: data[k] for k in data.files}
    return rec, json.loads(str(rec["meta"]))


def replay(rec, meta, result=None):
    """JSON-ready. A frame is every body's x, y, z, qx, qy, qz, qw in a flat list, rounded to 0.1 mm and 0.0001. body_parents gives the skeleton."""
    world = meta["world"]
    frames = [{"t": round(float(rec["t"][i]), 3), "q": np.round(rec["body_q"][i].astype(np.float64).ravel(), 4).tolist()} for i in range(0, len(rec["t"]), REPLAY_STRIDE)]
    return {
        "format": "robot-pack-replay/1", "pack": "inspection", "robot": meta["robot"], "label": meta["label"], "note": meta["note"], "simulated": True,
        "fps": round(1.0 / (REPLAY_STRIDE * meta["policy_dt_s"])), "body_labels": meta["body_labels"], "body_parents": meta["body_parents"], "pose_layout": ["x", "y", "z", "qx", "qy", "qz", "qw"],
        "route": [{"x": 0.0, "y": 0.0}] + world["route"]["waypoints"], "floor_friction": world["floor"]["friction"],
        "solids": W.primitives(world), "scenery": W.scenery_primitives(world), "result": result, "frames": frames,
    }
