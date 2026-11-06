"""Runs a pretrained IsaacLab policy on a world from world.py, in Newton, on this Mac's CPU, and records the run.

Setup copies newton/examples/robot/example_robot_policy.py: same solver (SolverMuJoCo, mujoco_warp backend, Newton
constraint solver), 200 Hz physics, 50 Hz policy, same observation layout. Differences, each on purpose:
- The robot starts at yaw 0 and z 0.40 instead of yaw 90 and a drop from z 0.76.
- Ground and objects carry geom priority 1. MuJoCo takes the larger friction of two equal-priority geoms, so without
  priority a slippery floor under 0.75 feet changes nothing. check_lab.py measures that.
- Contact capacity is larger, and run() records the peak so an overflow shows.
- The seed sets a small start noise on the joints. The example has no randomness.

Results are simulated. The policy and the robot model are upstream assets; nothing here is calibrated to a real robot.
"""
import hashlib
import json
import math
import pathlib
import time

import numpy as np
import warp as wp
import yaml
from warp_nn.runtime import OnnxRuntime

import newton
import newton.utils
from newton import JointTargetMode

import world as W

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ("world.py", "sim.py", "judge.py")
PHYSICS_HZ = 200
DECIMATION = 4
POLICY_DT = DECIMATION / PHYSICS_HZ
START_Z_M = 0.40
SEED_JOINT_NOISE_RAD = 0.02
NCONMAX = 60
NJMAX = 240
FEET = ("FL_foot", "FR_foot", "RL_foot", "RR_foot")
ROBOTS = {"go2": ("unitree_go2", "usd/go2.usda", "rl_policies/go2.yaml", "rl_policies/mjw_go2.onnx")}


def code_label():
    digest = hashlib.sha256(b"".join((HERE / name).read_bytes() for name in SOURCES)).hexdigest()
    return f"sim newton_lab {digest[:12]}"


def _robot_builder(robot):
    folder, usd, cfg_path, _ = ROBOTS[robot]
    asset = str(newton.utils.download_asset(folder))
    with open(f"{asset}/{cfg_path}", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    b = newton.ModelBuilder(up_axis=newton.Axis.Z)
    newton.solvers.SolverMuJoCo.register_custom_attributes(b)
    b.default_joint_cfg = newton.ModelBuilder.JointDofConfig(armature=0.1, limit_ke=1.0e2, limit_kd=1.0e0)
    b.default_shape_cfg.ke = 5.0e4
    b.default_shape_cfg.kd = 5.0e2
    b.default_shape_cfg.kf = 1.0e3
    b.default_shape_cfg.mu = W.DEFAULT_MU
    b.rigid_gap = 0.0
    b.add_usd(f"{asset}/{usd}", xform=wp.transform(wp.vec3(0, 0, 0.8)), collapse_fixed_joints=False,
              enable_self_collisions=False, joint_ordering="dfs", hide_collision_shapes=True)
    b.approximate_meshes("convex_hull")
    b.joint_q[:3] = [0.0, 0.0, START_Z_M]
    b.joint_q[3:7] = [0.0, 0.0, 0.0, 1.0]
    b.joint_q[7:] = cfg["mjw_joint_pos"]
    for i in range(cfg["num_dofs"]):
        b.joint_target_ke[i + 6] = cfg["mjw_joint_stiffness"][i]
        b.joint_target_kd[i + 6] = cfg["mjw_joint_damping"][i]
        b.joint_armature[i + 6] = cfg["mjw_joint_armature"][i]
        b.joint_target_mode[i + 6] = int(JointTargetMode.POSITION)
    return b, cfg


def _cfg(b, mu):
    cfg = newton.ModelBuilder.ShapeConfig(ke=b.default_shape_cfg.ke, kd=b.default_shape_cfg.kd, kf=b.default_shape_cfg.kf, mu=mu)
    return cfg


def _box(b, name, center, half, q, mu, priority, color):
    b.add_shape_box(-1, xform=wp.transform(wp.vec3(*center), q), hx=half[0], hy=half[1], hz=half[2], cfg=_cfg(b, mu),
                    label=f"obj:{name}", color=color, custom_attributes={"mujoco:geom_priority": priority})


def _add_object(b, obj, priority):
    mu = obj.get("mu", W.DEFAULT_MU)
    name, x, y = obj["name"], obj["x"], obj["y"]
    if obj["kind"] == "box":
        q = wp.quat_from_axis_angle(wp.vec3(0, 0, 1), math.radians(obj.get("yaw_deg", 0.0)))
        _box(b, name, (x, y, obj["sz"] / 2), (obj["sx"] / 2, obj["sy"] / 2, obj["sz"] / 2), q, mu, priority, (0.85, 0.45, 0.15))
    elif obj["kind"] == "ramp":
        slope = math.atan2(obj["height"], obj["length"])
        thick = obj["height"] / math.cos(slope) + 0.02
        cx = x + obj["length"] / 2 + math.sin(slope) * thick / 2
        cz = obj["height"] / 2 - math.cos(slope) * thick / 2
        half_len = math.hypot(obj["length"], obj["height"]) / 2
        q = wp.quat_from_axis_angle(wp.vec3(0, 1, 0), -slope)
        _box(b, name, (cx, y, cz), (half_len, obj["width"] / 2, thick / 2), q, mu, priority, (0.25, 0.55, 0.75))
    else:
        for i in range(obj.get("count", 3)):
            top = obj["rise"] * (i + 1)
            cx = x + obj["depth"] * (i + 0.5)
            _box(b, f"{name}_{i}", (cx, y, top / 2), (obj["depth"] / 2, obj["width"] / 2, top / 2), wp.quat_identity(), mu, priority,
                 (0.45, 0.65, 0.35))


def build_model(world, *, robot="go2", worlds=1, surface_priority=1):
    world = W.validate(world)
    env, cfg = _robot_builder(robot)
    env.add_shape_plane(plane=(0.0, 0.0, 1.0, 0.0), width=0.0, length=0.0, cfg=_cfg(env, world["ground"]["mu"]), label="ground",
                        color=(0.55, 0.55, 0.55), custom_attributes={"mujoco:geom_priority": surface_priority})
    for obj in world["objects"]:
        _add_object(env, obj, surface_priority)
    top = newton.ModelBuilder(up_axis=newton.Axis.Z)
    newton.solvers.SolverMuJoCo.register_custom_attributes(top)
    top.replicate(env, worlds, spacing=(0.0, 0.0, 0.0))
    model = top.finalize()
    model.set_gravity((0.0, 0.0, -9.81))
    return model, cfg


def _rotate_inv(q, v):
    u = -q[..., :3]
    t = 2.0 * np.cross(u, v)
    return v + q[..., 3:4] * t + np.cross(u, t)


class Runner:
    def __init__(self, world, *, robot="go2", worlds=1, seed=0, command=(1.0, 0.0, 0.0), surface_priority=1, mujoco_cpu=False, need_contacts=True):
        self.world = W.validate(world)
        self.worlds = worlds
        self.seed = seed
        self.command = tuple(float(v) for v in command)
        self.model, self.cfg = build_model(self.world, robot=robot, worlds=worlds, surface_priority=surface_priority)
        self.solver = newton.solvers.SolverMuJoCo(self.model, use_mujoco_cpu=mujoco_cpu, solver="newton", nconmax=NCONMAX, njmax=NJMAX)
        self.state_0, self.state_1 = self.model.state(), self.model.state()
        self.control = self.model.control()
        self.contacts = None
        self.observables = None
        if need_contacts:
            pipeline = newton.CollisionPipeline(self.model, rigid_contact_max=self.solver.get_max_contact_count(), soft_contact_max=0)
            self.contacts = pipeline.contacts()
            self.observables = self.solver.observables(contacts=self.contacts, kinds={self.solver.ObservableKind.CONTACT_F})
        self.nq = self.model.joint_coord_count // worlds
        self.nv = self.model.joint_dof_count // worlds
        self.ndof = self.cfg["num_dofs"]

        q = self.state_0.joint_q.numpy().reshape(worlds, self.nq)
        self.q0 = q[:, 7:].copy()
        rng = np.random.default_rng(seed)
        q[:, 7:] += rng.uniform(-SEED_JOINT_NOISE_RAD, SEED_JOINT_NOISE_RAD, size=(worlds, self.ndof))
        self.state_0.joint_q.assign(q.ravel())
        newton.eval_fk(self.model, self.state_0.joint_q, self.state_0.joint_qd, self.state_0)

        self.policy = OnnxRuntime(f"{newton.utils.download_asset(ROBOTS[robot][0])}/{ROBOTS[robot][3]}", device=wp.get_device())
        self.in_name = self.policy.inputs[0].name
        self.out_name = self.policy.outputs[0].name
        self.obs = wp.zeros((worlds, 12 + 3 * self.ndof), dtype=wp.float32)
        self.prev = np.zeros((worlds, self.ndof), dtype=np.float32)
        self.policy.prepare({self.in_name: self.obs})

        labels = self.model.shape_label
        self.obstacle = np.array(["obj:" in lb for lb in labels])
        self.ground = np.array([lb.endswith("ground") for lb in labels])
        self.foot_shape = {i: f for i, lb in enumerate(labels) for f, name in enumerate(FEET) if f"{name}/collisions" in lb}
        self.body_labels = [lb.rsplit("/", 1)[-1] for lb in self.model.body_label]
        self.base = self.body_labels.index("base")
        self.foot_body = [self.body_labels.index(name) for name in FEET]

    def policy_step(self):
        q = self.state_0.joint_q.numpy().reshape(self.worlds, self.nq)
        qd = self.state_0.joint_qd.numpy().reshape(self.worlds, self.nv)
        rot = q[:, 3:7]
        obs = np.concatenate(
            [
                _rotate_inv(rot, qd[:, :3]),
                _rotate_inv(rot, qd[:, 3:6]),
                _rotate_inv(rot, np.broadcast_to(np.array([0.0, 0.0, -1.0], dtype=np.float32), (self.worlds, 3))),
                np.broadcast_to(np.array(self.command, dtype=np.float32), (self.worlds, 3)),
                q[:, 7:] - self.q0,
                qd[:, 6:],
                self.prev,
            ],
            axis=1,
        ).astype(np.float32)
        self.obs.assign(obs)
        act = self.policy({self.in_name: self.obs})[self.out_name].numpy().copy()
        self.prev = act
        target = np.zeros((self.worlds, self.nq), dtype=np.float32)
        target[:, 7:] = self.q0 + float(self.cfg["action_scale"]) * act
        self.control.joint_target_q.assign(target.ravel())
        for _ in range(DECIMATION):
            self.state_0.clear_forces()
            self.solver.step(self.state_0, self.state_1, self.control, self.contacts, 1.0 / PHYSICS_HZ, observables=self.observables)
            self.state_0, self.state_1 = self.state_1, self.state_0

    def contact_readout(self):
        count = int(self.contacts.rigid_contact_count.numpy()[0])
        s0 = self.contacts.rigid_contact_shape0.numpy()[:count]
        s1 = self.contacts.rigid_contact_shape1.numpy()[:count]
        f = np.linalg.norm(self.observables.contact_f.numpy()[:count, :3], axis=1)
        hit = self.obstacle[s0] | self.obstacle[s1]
        floor = self.ground[s0] | self.ground[s1]
        feet = np.zeros(len(FEET), dtype=bool)
        non_foot_ground = 0.0
        for a, b, force, on_floor in zip(s0, s1, f, floor):
            foot = self.foot_shape.get(int(a), self.foot_shape.get(int(b)))
            if foot is not None:
                feet[foot] = True
            elif on_floor:
                non_foot_ground += float(force)
        return {"obstacle_f": float(f[hit].sum()), "obstacle_n": int(hit.sum()), "ground_f": float(f[floor].sum()), "feet": feet,
                "body_on_ground_f": non_foot_ground, "n": count}


def run(world, *, seed=0, duration_s=10.0, command=(1.0, 0.0, 0.0), out=None, surface_priority=1):
    runner = Runner(world, seed=seed, command=command, surface_priority=surface_priority)
    steps = round(duration_s / POLICY_DT)
    log = {k: [] for k in ("t", "body_q", "body_qd", "joint_q", "obstacle_f", "obstacle_n", "ground_f", "body_on_ground_f", "feet", "n")}
    peak_nacon = peak_nefc = 0
    started = time.perf_counter()
    for k in range(steps):
        runner.policy_step()
        contact = runner.contact_readout()
        log["t"].append((k + 1) * POLICY_DT)
        log["body_q"].append(runner.state_0.body_q.numpy().copy())
        log["body_qd"].append(runner.state_0.body_qd.numpy().copy())
        log["joint_q"].append(runner.state_0.joint_q.numpy().copy())
        for key in ("obstacle_f", "obstacle_n", "ground_f", "body_on_ground_f", "feet", "n"):
            log[key].append(contact[key])
        peak_nacon = max(peak_nacon, int(runner.solver.mjw_data.nacon.numpy().max()))
        peak_nefc = max(peak_nefc, int(runner.solver.mjw_data.nefc.numpy().max()))
    wall = time.perf_counter() - started
    body_q = np.asarray(log["body_q"], dtype=np.float32)
    rec = {
        "t": np.asarray(log["t"], dtype=np.float32),
        "body_q": body_q,
        "body_qd": np.asarray(log["body_qd"], dtype=np.float32),
        "joint_q": np.asarray(log["joint_q"], dtype=np.float32),
        "base_q": body_q[:, runner.base],
        "foot_v_xy": np.linalg.norm(np.asarray(log["body_qd"], dtype=np.float32)[:, runner.foot_body, :2], axis=2),
        "feet": np.asarray(log["feet"], dtype=bool),
        **{k: np.asarray(log[k], dtype=np.float32) for k in ("obstacle_f", "obstacle_n", "ground_f", "body_on_ground_f", "n")},
    }
    meta = {
        "label": code_label(),
        "note": "Simulated. Not calibrated. Not a real-robot result.",
        "world": runner.world,
        "seed": seed,
        "command": list(runner.command),
        "policy_dt_s": POLICY_DT,
        "physics_hz": PHYSICS_HZ,
        "wall_s": wall,
        "rtf": steps * POLICY_DT / wall,
        "peak_nacon": peak_nacon,
        "peak_nefc": peak_nefc,
        "nconmax": NCONMAX,
        "njmax": NJMAX,
        "body_labels": runner.body_labels,
        "shapes": runner.model.shape_count,
    }
    rec["meta"] = np.array(json.dumps(meta))
    if out is not None:
        out = pathlib.Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, **rec)
    return rec, meta
