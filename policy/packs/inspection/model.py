"""Model loader: ANYmal C from Newton's asset repo, with the world's solids, as a Newton model.

The setup copies newton/examples/robot/example_robot_policy.py (--robot anymal), with these differences, each on purpose:
- The robot starts at yaw 0 and z 0.62 instead of yaw 90 and a drop from z 0.76.
- The floor and objects carry geom priority 1. MuJoCo otherwise takes the larger friction of two geoms, and a slippery floor under 0.75 feet changes nothing.
- A payload is a box with no collision on the robot's base. It adds mass and inertia only.
The robot model and the policy are upstream's, and nothing here is calibrated to a real robot.
"""
import warp as wp
import yaml

import newton
import newton.utils
from newton import JointTargetMode

from . import world as W

ASSET = "anybotics_anymal_c"
USD = "usd/anymal_c.usda"
CONFIG = "rl_policies/anymal.yaml"
POLICY = "rl_policies/mjw_anymal.onnx"
FEET = ("LF_FOOT", "LH_FOOT", "RF_FOOT", "RH_FOOT")
BASE = "base"
START_Z_M = 0.62
PAYLOAD_HALF_M = (0.2, 0.12, 0.05)
PAYLOAD_Z_M = 0.17


def asset_dir():
    return str(newton.utils.download_asset(ASSET))


def policy_path():
    return f"{asset_dir()}/{POLICY}"


def _robot_builder():
    asset = asset_dir()
    with open(f"{asset}/{CONFIG}", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    b = newton.ModelBuilder(up_axis=newton.Axis.Z)
    newton.solvers.SolverMuJoCo.register_custom_attributes(b)
    b.default_joint_cfg = newton.ModelBuilder.JointDofConfig(armature=0.1, limit_ke=1.0e2, limit_kd=1.0e0)
    b.default_shape_cfg.ke = 5.0e4
    b.default_shape_cfg.kd = 5.0e2
    b.default_shape_cfg.kf = 1.0e3
    b.default_shape_cfg.mu = W.DEFAULT_FRICTION
    b.rigid_gap = 0.0
    b.add_usd(f"{asset}/{USD}", xform=wp.transform(wp.vec3(0, 0, 0.8)), collapse_fixed_joints=False, enable_self_collisions=False,
              joint_ordering="dfs", hide_collision_shapes=True)
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


def _shape_cfg(b, friction):
    return newton.ModelBuilder.ShapeConfig(ke=b.default_shape_cfg.ke, kd=b.default_shape_cfg.kd, kf=b.default_shape_cfg.kf, mu=friction)


def _add_prim(b, prim, cfg, label, attrs):
    xform = wp.transform(wp.vec3(*prim["pos"]), wp.quat(*prim["quat"]))
    size = prim["size"]
    color = tuple(prim["colour"])
    if prim["type"] == "hull":
        mesh = newton.Mesh(prim["verts"], [i for face in prim["faces"] for i in face], compute_inertia=False)
        b.add_shape_convex_hull(-1, xform=xform, mesh=mesh, cfg=cfg, label=label, color=color, custom_attributes=attrs)
    elif prim["type"] == "box":
        b.add_shape_box(-1, xform=xform, hx=size[0], hy=size[1], hz=size[2], cfg=cfg, label=label, color=color, custom_attributes=attrs)
    elif prim["type"] == "capsule":
        b.add_shape_capsule(-1, xform=xform, radius=size[0], half_height=size[1], cfg=cfg, label=label, color=color, custom_attributes=attrs)
    else:
        b.add_shape_cylinder(-1, xform=xform, radius=size[0], half_height=size[1], cfg=cfg, label=label, color=color, custom_attributes=attrs)


def _label(prefix, prim):
    """The renderer reads the material from the label. The physics reads only the prefix."""
    return f"{prefix}:{prim['name']}#{prim['material']}"


def load_model(world, *, picture=False):
    """A finalized Newton model and the upstream config. With picture=True it also holds scenery that collides with nothing, for the renderer only."""
    world = W.validate(world)
    b, cfg = _robot_builder()
    priority = {"mujoco:geom_priority": 1}
    mass = world["payload"]["mass_kg"]
    if mass > 0.0:
        hx, hy, hz = PAYLOAD_HALF_M
        carried = newton.ModelBuilder.ShapeConfig(density=mass / (8.0 * hx * hy * hz), has_shape_collision=False, has_particle_collision=False)
        b.add_shape_box(0, xform=wp.transform(wp.vec3(0.0, 0.0, PAYLOAD_Z_M), wp.quat_identity()), hx=hx, hy=hy, hz=hz, cfg=carried, label="payload", color=(0.1, 0.11, 0.12))
    b.add_shape_plane(plane=(0.0, 0.0, 1.0, 0.0), width=0.0, length=0.0, cfg=_shape_cfg(b, world["floor"]["friction"]), label="ground", color=(0.46, 0.45, 0.43), custom_attributes=priority)
    for prim in W.primitives(world):
        _add_prim(b, prim, _shape_cfg(b, prim["friction"]), _label("obj", prim), priority)
    if picture:
        ghost = newton.ModelBuilder.ShapeConfig(has_shape_collision=False, has_particle_collision=False)
        for prim in W.scenery_primitives(world):
            if prim["type"] != "glb":  # a picture-only model has no shape. The browser and Blender draw its GLB.
                _add_prim(b, prim, ghost, _label("scenery", prim), priority)
        for i, point in enumerate(world["route"]["waypoints"]):
            marker = {"type": "cylinder", "pos": [point["x"], point["y"], 0.001], "quat": [0.0, 0.0, 0.0, 1.0], "size": [0.1, 0.001], "colour": list(W.MATERIALS["route_mark"]), "name": f"waypoint_{i}", "material": "route_mark"}
            _add_prim(b, marker, ghost, _label("scenery", marker), priority)
    model = b.finalize()
    model.set_gravity((0.0, 0.0, -world["gravity"]["g"]))
    return model, cfg
