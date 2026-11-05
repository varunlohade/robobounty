"""Builds a LIBERO episode from a validated scene. run_scene.py and replay.py share this path."""
import hashlib
import json
import math
import os
from pathlib import Path

_POLICY_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("LIBERO_CONFIG_PATH", str(_POLICY_DIR / ".libero"))
os.environ.setdefault("MUJOCO_GL", "cgl")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("WANDB_MODE", "disabled")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import xml.etree.ElementTree as ET

import mujoco
import numpy as np
from lerobot.envs.libero import LiberoEnv, get_libero_dummy_action
from libero.libero import benchmark

from scene import GOAL_OBJECT, OBJECTS, TARGET_OBJECT

SUITE = "libero_spatial"
IMAGE_SIZE = 360
CONTROL_HZ = 20
MIN_SETTLE_STEPS = 10  # the same as lerobot-eval, so a baseline matches its path
MAX_SETTLE_STEPS = 50
TABLE_TOP_Z = 0.90
QUIET_SPEED = 0.02  # m/s
MAX_XY_DRIFT_M = 0.015
MAX_RISE_M = 0.01  # stock init states hold objects up to ~7 cm above the table, so falling is normal
MAX_TILT_CHANGE_DEG = 10.0
MAX_PENETRATION_M = 0.005
LIFTED_M = 0.02
OFF_TABLE_MARGIN_M = 0.05


def build(scene):
    suite = benchmark.get_benchmark_dict()[SUITE]()
    wrapper = LiberoEnv(
        task_suite=suite,
        task_id=scene["task_id"],
        task_suite_name=SUITE,
        camera_name="agentview_image,robot0_eye_in_hand_image",
        obs_type="pixels_agent_pos",
        observation_height=IMAGE_SIZE,
        observation_width=IMAGE_SIZE,
        init_states=True,
        episode_index=scene["init_state"],
        num_steps_wait=0,
        control_freq=CONTROL_HZ,
        control_mode="relative",
        hard_reset=True,
    )
    wrapper.reset(seed=scene["seed"])
    return wrapper


def _inner(wrapper):
    return wrapper._env.env


def _add_clutter(inner, clutter):
    """Appends plain boxes to the MJCF. Only numbers from the validated scene reach the XML."""
    sim = inner.sim
    old = {
        "qpos": sim.data.qpos.copy(), "qvel": sim.data.qvel.copy(), "time": sim.data.time,
        "body_pos": sim.model.body_pos.copy(), "body_quat": sim.model.body_quat.copy(),
        "joints": [mujoco.mj_id2name(sim.model._model, mujoco.mjtObj.mjOBJ_JOINT, j)
                   for j in range(sim.model.njnt)],
    }
    for i, box in enumerate(clutter):
        half = box["half_size"]
        z = TABLE_TOP_Z + half + 0.001
        body = ET.Element("body", name=f"crashlab_clutter_{i}",
                          pos=f"{box['x']!r} {box['y']!r} {z!r}",
                          euler=f"0 0 {box['yaw']!r}")
        ET.SubElement(body, "freejoint", name=f"crashlab_clutter_{i}_joint")
        r, g, b = box["rgb"]
        size = f"{half!r} {half!r} {half!r}"
        # robosuite takes inertia from group 0 and renders only group 1, so the box needs both.
        ET.SubElement(body, "geom", type="box", size=size, density="500", group="0")
        ET.SubElement(body, "geom", type="box", size=size, rgba=f"{r!r} {g!r} {b!r} 1", group="1",
                      contype="0", conaffinity="0", mass="0")
        inner.model.worldbody.append(body)
    inner.reset_from_xml_string(inner.model.get_xml())

    sim = inner.sim
    joints = [mujoco.mj_id2name(sim.model._model, mujoco.mjtObj.mjOBJ_JOINT, j)
              for j in range(sim.model.njnt)]
    if joints[: len(old["joints"])] != old["joints"]:
        raise RuntimeError("clutter changed the joint order")
    n_body = len(old["body_pos"])
    sim.model.body_pos[:n_body] = old["body_pos"]  # keeps the fixture placement drawn at reset
    sim.model.body_quat[:n_body] = old["body_quat"]
    sim.data.time = old["time"]
    sim.data.qpos[: len(old["qpos"])] = old["qpos"]
    sim.data.qvel[: len(old["qvel"])] = old["qvel"]
    sim.forward()


def _set_light(sim, scale):
    m = sim.model._model
    m.light_diffuse *= scale
    m.light_specular *= scale
    m.light_ambient *= scale
    for name in ("ambient", "diffuse", "specular"):
        setattr(m.vis.headlight, name, np.asarray(getattr(m.vis.headlight, name)) * scale)


def _object_geoms(inner, name):
    m = inner.sim.model._model
    root = m.body(inner.get_object(name).root_body).id
    bodies = {root}
    for b in range(m.nbody):
        if m.body_parentid[b] in bodies:
            bodies.add(b)
    return [g for g in range(m.ngeom) if m.geom_bodyid[g] in bodies]


def _set_colour(inner, name, rgb):
    """Removes the material, because LIBERO textures multiply rgba and a black texture stays black."""
    m = inner.sim.model._model
    visual = [g for g in _object_geoms(inner, name) if m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0]
    if not visual:
        raise RuntimeError(f"{name} has no visual geoms")
    for g in visual:
        m.geom_matid[g] = -1
        m.geom_rgba[g] = [*rgb, 1.0]


def _move(inner, entry):
    sim = inner.sim
    adr = sim.model.get_joint_qpos_addr(inner.get_object(OBJECTS[entry["object"]]).joints[-1])[0]
    sim.data.qpos[adr] += entry["dx"]
    sim.data.qpos[adr + 1] += entry["dy"]
    half = entry["dyaw"] / 2
    q = np.zeros(4)
    mujoco.mju_mulQuat(q, np.array([math.cos(half), 0, 0, math.sin(half)]), sim.data.qpos[adr + 3:adr + 7].copy())
    sim.data.qpos[adr + 3:adr + 7] = q


def _poses(inner):
    sim = inner.sim
    out = {}
    names = list(OBJECTS) + [n for n in (f"crashlab_clutter_{i}" for i in range(3))
                             if mujoco.mj_name2id(sim.model._model, mujoco.mjtObj.mjOBJ_BODY, n) >= 0]
    for name in names:
        body = name if name.startswith("crashlab") else inner.get_object(name).root_body
        bid = sim.model.body_name2id(body)
        z_axis = sim.data.body_xmat[bid].reshape(3, 3)[:, 2]
        speed = float(np.linalg.norm(sim.data.cvel[bid][3:]))
        out[name] = {"pos": sim.data.body_xpos[bid].copy(),
                     "tilt_deg": math.degrees(math.acos(float(np.clip(z_axis[2], -1, 1)))),
                     "speed": speed}
    return out


def _deepest_penetration(sim):
    d = sim.data
    return float(-min((d.contact[i].dist for i in range(d.ncon)), default=0.0))


def state_sha(sim):
    d = sim.data
    h = hashlib.sha256()
    for a in (np.array([d.time]), d.qpos, d.qvel):
        h.update(np.asarray(a, dtype=np.float64).tobytes())
    return h.hexdigest()


def model_sha(sim):
    m = sim.model._model
    h = hashlib.sha256()
    for a in (m.body_pos, m.body_quat, m.geom_pos, m.geom_quat, m.geom_size, m.geom_rgba, m.geom_matid,
              m.geom_friction, m.light_diffuse, m.light_ambient, m.light_specular, m.opt.timestep):
        h.update(np.asarray(a).tobytes())
    return h.hexdigest()


def _settle(wrapper):
    """No-op steps until quiet. Measures what settling did to each object."""
    inner = _inner(wrapper)
    inner.sim.forward()
    placed = _poses(inner)
    dummy = np.array(get_libero_dummy_action(), dtype=np.float64)
    steps = 0
    while steps < MAX_SETTLE_STEPS:
        raw_obs, _, _, _ = wrapper._env.step(dummy)
        steps += 1
        now = _poses(inner)
        if steps >= MIN_SETTLE_STEPS and max(p["speed"] for p in now.values()) < QUIET_SPEED:
            break
    objects = {}
    for name, p in now.items():
        objects[name] = {
            "pos": [float(x) for x in p["pos"]],
            "xy_drift_m": float(np.linalg.norm(p["pos"][:2] - placed[name]["pos"][:2])),
            "z_change_m": float(p["pos"][2] - placed[name]["pos"][2]),
            "tilt_change_deg": abs(p["tilt_deg"] - placed[name]["tilt_deg"]),
            "speed": p["speed"],
        }
    return raw_obs, {"settle_steps": steps, "objects": objects,
                     "deepest_penetration_m": _deepest_penetration(inner.sim)}


def _problems(report, stock):
    """Compares with the same init state and seed without edits, because some stock states already slide."""
    base = stock["objects"]
    zero = {"xy_drift_m": 0.0, "z_change_m": 0.0, "tilt_change_deg": 0.0, "speed": 0.0}
    problems = []
    if report["deepest_penetration_m"] > max(MAX_PENETRATION_M, stock["deepest_penetration_m"]):
        problems.append(f"penetration {report['deepest_penetration_m']:.4f} m")
    for name, o in report["objects"].items():
        b = base.get(name, zero)
        if o["xy_drift_m"] - b["xy_drift_m"] > MAX_XY_DRIFT_M:
            problems.append(f"{name} slid {o['xy_drift_m']:.4f} m (stock {b['xy_drift_m']:.4f}) while settling")
        if o["z_change_m"] - b["z_change_m"] > MAX_RISE_M:
            problems.append(f"{name} rests {o['z_change_m'] - b['z_change_m']:.4f} m higher than stock")
        if o["tilt_change_deg"] - b["tilt_change_deg"] > MAX_TILT_CHANGE_DEG:
            problems.append(f"{name} tilted {o['tilt_change_deg']:.1f} deg (stock {b['tilt_change_deg']:.1f}) while settling")
        if o["speed"] >= QUIET_SPEED and b["speed"] < QUIET_SPEED:
            problems.append(f"{name} still moving at {o['speed']:.3f} m/s")
    return problems


def prepare(scene):
    """Reset, apply the variation, settle, check the scene is physically sane. Returns (wrapper, raw_obs, report)."""
    varied = scene["objects"] or scene["clutter"]  # light and colour cannot change the physics
    stock = None
    if varied:
        reference = build(scene)
        _, stock = _settle(reference)
        reference.close()

    wrapper = build(scene)
    inner = _inner(wrapper)
    if scene["clutter"]:
        _add_clutter(inner, scene["clutter"])
    if scene["light"] != 1.0:
        _set_light(inner.sim, scene["light"])
    for c in scene["colours"]:
        _set_colour(inner, OBJECTS[c["object"]], c["rgb"])
    for e in scene["objects"]:
        _move(inner, e)

    raw_obs, report = _settle(wrapper)
    report["problems"] = _problems(report, stock) if stock else []
    if stock:
        report["stock_xy_drift_m"] = {k: v["xy_drift_m"] for k, v in stock["objects"].items()}
    report["valid"] = not report["problems"]
    return wrapper, raw_obs, report


class Outcome:
    """Failure labels come only from sim state seen during the episode."""

    def __init__(self, wrapper):
        self.inner = _inner(wrapper)
        self.target = self.inner.get_object(OBJECTS[TARGET_OBJECT])
        self.start = _poses(self.inner)[OBJECTS[TARGET_OBJECT]]
        self.max_lift = 0.0
        self.touched = False

    def update(self):
        p = _poses(self.inner)[OBJECTS[TARGET_OBJECT]]
        self.max_lift = max(self.max_lift, float(p["pos"][2] - self.start["pos"][2]))
        if not self.touched:
            self.touched = bool(self.inner.check_contact(self.inner.robots[0].gripper, self.target))

    def finish(self, success, nan_action=False):
        poses = _poses(self.inner)
        p, goal = poses[OBJECTS[TARGET_OBJECT]], poses[OBJECTS[GOAL_OBJECT]]
        metrics = {
            "target_max_lift_m": self.max_lift,
            "target_moved_m": float(np.linalg.norm(p["pos"][:2] - self.start["pos"][:2])),
            "target_to_goal_xy_m": float(np.linalg.norm(p["pos"][:2] - goal["pos"][:2])),
            "target_final_tilt_deg": p["tilt_deg"],
            "gripper_touched_target": self.touched,
        }
        if nan_action:
            reason = "invalid_action"
        elif success:
            reason = "goal_reached"
        elif p["pos"][2] < TABLE_TOP_Z - OFF_TABLE_MARGIN_M:
            reason = "target_off_table"
        elif self.max_lift >= LIFTED_M:
            reason = "target_lifted_not_placed"
        elif self.touched:
            reason = "target_touched_not_lifted"
        else:
            reason = "target_never_touched"
        return reason, metrics


def final_state(sim):
    d = sim.data
    return {"time": float(d.time), "qpos": [float(x) for x in d.qpos], "qvel": [float(x) for x in d.qvel]}


def step_digest(prev, index, action, state):
    body = json.dumps({"i": index, "a": action, "s": state}, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def batched(tree):
    return {k: batched(v) if isinstance(v, dict) else v[None] for k, v in tree.items()}


def versions():
    import robosuite
    return {"mujoco": mujoco.__version__, "robosuite": robosuite.__version__}
