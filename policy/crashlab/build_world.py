"""Builds a LIBERO world from a validated v2 spec: BDDL, env, seeded layout, settle check, still.

build_world.py SPEC.json [SPEC.json ...] --out DIR [--seed N ...]
Specs are validated before this file imports the sim, so a bad spec never starts an env.
Exit code is the number of rejected worlds and bad specs, capped at 125.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as schema

MAX_ATTEMPTS = 12
MAX_DRAWS = 200  # per item, for the footprint check before any physics
FOOTPRINT_GAP_M = 0.005
SPAWN_LIFT_M = 0.3
DROP_CLEARANCE_M = 0.003
STILL_SIZE = 1080
CAMERAS = {"": "agentview", "_front": "frontview"}


def _bddl_path(world, out):
    text = schema.write_bddl(world)
    path = Path(out) / f"{world['arena']}_{schema.world_hash(world)[:12]}.bddl"
    path.write_text(text)
    return path


class Builder:
    """One env per world. It never calls ControlEnv.reset: that loop swallows every exception and retries forever."""

    def __init__(self, world, bddl_path, image_size):
        import numpy as np
        import mujoco
        import sim as sim_v1
        from libero.libero.envs import OffScreenRenderEnv

        self.np, self.mujoco, self.v1 = np, mujoco, sim_v1
        self.world = world
        arena = schema.ARENAS[world["arena"]]
        self.arena = arena
        np.random.seed(world["seed"])
        self.env = OffScreenRenderEnv(
            bddl_file_name=str(bddl_path),
            camera_heights=image_size,
            camera_widths=image_size,
            control_freq=sim_v1.CONTROL_HZ,
            hard_reset=False,
            scene_xml=f"scenes/{arena['styles'][world['style']]}.xml",
        )
        self.inner = self.env.env
        self.inner.deterministic_reset = True  # LIBERO's sampler must not undo our layout
        if world["clutter"]:
            self._add_clutter()
        if world["light"] != 1.0:
            sim_v1._set_light(self.inner.sim, world["light"])
        self.movable = [e["name"] for e in world["objects"]]
        self.fixtures = [e["name"] for e in world["fixtures"]]
        self.clutter = [f"crashlab_clutter_{i}" for i in range(len(world["clutter"]))]
        self._index_geoms()

    def _add_clutter(self):
        """Only numbers from the validated spec reach the XML."""
        import xml.etree.ElementTree as ET
        ox, oy = self.inner.workspace_offset[:2]
        for i, box in enumerate(self.world["clutter"]):
            half = box["half_size"]
            z = self.arena["surface_z"] + half + 0.002
            body = ET.Element("body", name=f"crashlab_clutter_{i}", pos=f"{ox + box['x']!r} {oy + box['y']!r} {z!r}",
                              euler=f"0 0 {box['yaw']!r}")
            ET.SubElement(body, "freejoint", name=f"crashlab_clutter_{i}_joint")
            size = f"{half!r} {half!r} {half!r}"
            r, g, b = box["rgb"]
            ET.SubElement(body, "geom", type="box", size=size, density="500", group="0")
            ET.SubElement(body, "geom", type="box", size=size, rgba=f"{r!r} {g!r} {b!r} 1", group="1",
                          contype="0", conaffinity="0", mass="0")
            self.inner.model.worldbody.append(body)
        self.inner.reset_from_xml_string(self.inner.model.get_xml())
        self.inner.deterministic_reset = True

    def _index_geoms(self):
        m = self.inner.sim.model._model
        parent = m.body_parentid
        self.body_owner = {}
        roots = {self._root(n): n for n in self.movable + self.fixtures + self.clutter}
        for b in range(m.nbody):
            walk = b
            while walk and walk not in roots:
                walk = parent[walk]
            if walk in roots:
                self.body_owner[b] = roots[walk]
        self.robot_bodies = {b for b in range(m.nbody)
                             if (m.body(b).name or "").startswith(("robot0_", "gripper0_"))}

    def _root(self, name):
        m = self.inner.sim.model._model
        if name.startswith("crashlab"):
            return m.body(name).id
        return m.body(self.inner.get_object(name).root_body).id

    def _draw(self, attempt):
        """Numeric layout for one attempt, or None when the footprints do not fit."""
        rng = self.np.random.default_rng([self.world["seed"], attempt])
        placed = [(self.world_xy(c["x"], c["y"]), c["half_size"] * math.sqrt(2)) for c in self.world["clutter"]]
        layout = {}
        for e in self.world["fixtures"] + self.world["objects"]:
            radius = float(self.inner.get_object(e["name"]).horizontal_radius)
            for _ in range(MAX_DRAWS):
                x0, y0, x1, y1 = e["region"]
                xy = self.world_xy(rng.uniform(x0, x1), rng.uniform(y0, y1))
                if all(math.dist(xy, p) > radius + r + FOOTPRINT_GAP_M for p, r in placed):
                    break
            else:
                return None
            placed.append((xy, radius))
            layout[e["name"]] = {"xy": [float(v) for v in xy], "yaw": float(rng.uniform(*e["yaw"]))}
        return layout

    def world_xy(self, x, y):
        ox, oy = self.inner.workspace_offset[:2]
        return (ox + x, oy + y)

    def _base_pose(self, name, is_fixture):
        """LIBERO's own z and upright quaternion for this asset. Sampling is seeded, so it repeats."""
        key = f"{name}_sampler" if is_fixture else name
        self.np.random.seed(int(hashlib.sha256(f"{self.world['seed']}:{name}".encode()).hexdigest()[:8], 16) % 2**31)
        pos, quat, _ = self.inner.placement_initializer.samplers[key].sample()[name]
        return pos, quat

    def _apply(self, layout):
        np, mujoco, inner = self.np, self.mujoco, self.inner
        inner.reset()
        sim = inner.sim
        for prop in inner.object_property_initializers:
            inner.object_states_dict[prop.name].set_joint(prop.sample())
        for name, pose in layout.items():
            is_fixture = name in self.fixtures
            pos, quat = self._base_pose(name, is_fixture)
            half = pose["yaw"] / 2
            q = np.zeros(4)
            mujoco.mju_mulQuat(q, np.array([math.cos(half), 0.0, 0.0, math.sin(half)]), np.array(quat, dtype=float))
            if is_fixture:
                b = sim.model.body_name2id(inner.get_object(name).root_body)
                sim.model.body_pos[b] = [pose["xy"][0], pose["xy"][1], float(pos[2])]
                sim.model.body_quat[b] = q
                pose["z"] = float(pos[2])
            else:
                sim.data.set_joint_qpos(inner.get_object(name).joints[-1],
                                        np.concatenate([[pose["xy"][0], pose["xy"][1], float(pos[2]) + SPAWN_LIFT_M], q]))
        sim.forward()
        self._rest_on_surface(layout)
        sim.forward()

    def _rest_on_surface(self, layout):
        """LIBERO's bottom_offset ignores the base rotation, so its z can sit 7 cm high or inside the table.
        This drops each object from just above the surface, using the bounding box of its collision geoms."""
        np, sim = self.np, self.inner.sim
        m = sim.model._model
        corners = np.array([[a, b, c] for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)], dtype=float)
        for name in self.movable:
            joint = self.inner.get_object(name).joints[-1]
            low = math.inf
            for g in range(m.ngeom):
                if self.body_owner.get(int(m.geom_bodyid[g])) != name or not (m.geom_contype[g] or m.geom_conaffinity[g]):
                    continue
                box = corners * m.geom_aabb[g][3:] + m.geom_aabb[g][:3]
                low = min(low, float((box @ sim.data.geom_xmat[g].reshape(3, 3).T + sim.data.geom_xpos[g])[:, 2].min()))
            qpos = sim.data.get_joint_qpos(joint).copy()
            qpos[2] += self.arena["surface_z"] + DROP_CLEARANCE_M - low
            layout[name]["z"] = float(qpos[2])
            sim.data.set_joint_qpos(joint, qpos)

    def _poses(self):
        sim = self.inner.sim
        out = {}
        for name in self.movable + self.clutter:
            b = self._root(name)
            z_axis = sim.data.body_xmat[b].reshape(3, 3)[:, 2]
            out[name] = {"pos": sim.data.body_xpos[b].copy(),
                         "tilt_deg": math.degrees(math.acos(float(self.np.clip(z_axis[2], -1, 1)))),
                         "speed": float(self.np.linalg.norm(sim.data.cvel[b][3:]))}
        return out

    def _contacts(self):
        """Deepest penetration that touches a movable item or clutter, and any robot contact with the scene."""
        sim = self.inner.sim
        m, d = sim.model._model, sim.data
        deepest, pair, robot = 0.0, None, None
        loose = set(self.movable + self.clutter)
        self.touching = set()
        for i in range(d.ncon):
            c = d.contact[i]
            b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
            o1, o2 = self.body_owner.get(b1), self.body_owner.get(b2)
            if (o1 and b2 in self.robot_bodies) or (o2 and b1 in self.robot_bodies):
                robot = o1 or o2
            if o1 == o2 or not ({o1, o2} & loose):
                continue
            self.touching.update({o1, o2})
            if -c.dist > deepest:
                deepest, pair = float(-c.dist), (o1 or m.body(b1).name, o2 or m.body(b2).name)
        return deepest, pair, robot

    def _settle(self):
        v1, np = self.v1, self.np
        placed = self._poses()
        dummy = np.array(v1.get_libero_dummy_action(), dtype=np.float64)
        steps = 0
        while steps < v1.MAX_SETTLE_STEPS:
            raw_obs, _, _, _ = self.env.step(dummy)
            steps += 1
            now = self._poses()
            if steps >= v1.MIN_SETTLE_STEPS and max(p["speed"] for p in now.values()) < v1.QUIET_SPEED:
                break
        objects = {n: {"pos": [float(x) for x in p["pos"]],
                       "xy_drift_m": float(np.linalg.norm(p["pos"][:2] - placed[n]["pos"][:2])),
                       "z_change_m": float(p["pos"][2] - placed[n]["pos"][2]),
                       "tilt_change_deg": abs(p["tilt_deg"] - placed[n]["tilt_deg"]),
                       "tilt_deg": p["tilt_deg"],
                       "speed": p["speed"]} for n, p in now.items()}
        return raw_obs, steps, objects

    def _problems(self, objects, deepest, pair, robot):
        v1 = self.v1
        out = []
        if robot:
            out.append(("robot_contact", robot))
        if deepest > v1.MAX_PENETRATION_M:
            out.append(("penetration", f"{pair[0]}/{pair[1]} {deepest:.4f}"))
        for name, o in objects.items():
            if o["xy_drift_m"] > v1.MAX_XY_DRIFT_M:
                out.append(("slid", f"{name} {o['xy_drift_m']:.4f}"))
            if o["z_change_m"] > v1.MAX_RISE_M:
                out.append(("rose", f"{name} {o['z_change_m']:.4f}"))
            if o["tilt_change_deg"] > v1.MAX_TILT_CHANGE_DEG:
                out.append(("tilted", f"{name} {o['tilt_change_deg']:.1f}"))
            if o["speed"] >= v1.QUIET_SPEED:
                out.append(("moving", f"{name} {o['speed']:.3f}"))
            if name not in self.touching:
                out.append(("floating", name))
        if self.env.check_success():
            out.append(("goal_true_at_start", ""))
        return out

    def prepare(self):
        """Re-samples bad placements, then accepts or rejects. Leaves the env on the accepted, settled layout."""
        rejects, log = {}, []
        for attempt in range(MAX_ATTEMPTS):
            layout = self._draw(attempt)
            if layout is None:
                rejects["no_room"] = rejects.get("no_room", 0) + 1
                continue
            self._apply(layout)
            raw_obs, steps, objects = self._settle()
            deepest, pair, robot = self._contacts()
            problems = self._problems(objects, deepest, pair, robot)
            if not problems:
                return raw_obs, {"valid": True, "attempts": attempt + 1, "rejects": rejects, "reject_log": log, "layout": layout,
                                 "settle_steps": steps, "objects": objects, "deepest_penetration_m": deepest,
                                 "state_sha": self.v1.state_sha(self.inner.sim), "model_sha": self.v1.model_sha(self.inner.sim)}
            for reason, _ in problems:
                rejects[reason] = rejects.get(reason, 0) + 1
            log.append(problems)
        return None, {"valid": False, "attempts": MAX_ATTEMPTS, "rejects": rejects, "reject_log": log}

    def still(self, path_stem, size=STILL_SIZE):
        """Sharp stills from a separate renderer, so the policy's camera size stays as it is."""
        from PIL import Image
        m = self.inner.sim.model._model
        m.vis.global_.offwidth = max(m.vis.global_.offwidth, size)
        m.vis.global_.offheight = max(m.vis.global_.offheight, size)
        m.vis.quality.offsamples = 8
        m.vis.quality.shadowsize = 8192
        renderer = self.mujoco.Renderer(m, size, size)
        visual_only = self.mujoco.MjvOption()
        visual_only.geomgroup[0] = 0  # group 0 is collision hulls, which robosuite also hides
        out = []
        for suffix, camera in CAMERAS.items():
            renderer.update_scene(self.inner.sim.data._data, camera=camera, scene_option=visual_only)
            path = f"{path_stem}{suffix}.png"
            Image.fromarray(renderer.render()).save(path)
            out.append(path)
        renderer.close()
        return out

    def close(self):
        self.env.close()


def build_one(world, out, image_size=128):
    t0 = time.perf_counter()
    bddl = _bddl_path(world, out)
    report = {"world_hash": schema.world_hash(world), "arena": world["arena"], "seed": world["seed"],
              "instruction": schema.instruction(world), "bddl": str(bddl),
              "bddl_sha256": hashlib.sha256(bddl.read_bytes()).hexdigest()}
    try:
        builder = Builder(world, bddl, image_size)
    except Exception as e:  # LIBERO's own first placement can fail on an impossible spec
        report.update(valid=False, build_error=f"{type(e).__name__}: {e}", seconds=time.perf_counter() - t0)
        return report
    t1 = time.perf_counter()
    _, result = builder.prepare()
    t2 = time.perf_counter()
    report.update(result)
    if result["valid"]:
        stem = str(Path(out) / f"{world['arena']}_{report['world_hash'][:12]}_s{world['seed']}")
        report["stills"] = builder.still(stem)
    builder.close()
    report.update(env_s=t1 - t0, settle_s=t2 - t1, render_s=time.perf_counter() - t2, seconds=time.perf_counter() - t0)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, action="append", help="build each spec with this seed in place of its own")
    args = ap.parse_args()

    worlds, failures = [], 0
    for path in args.specs:
        try:
            base = schema.load(path)
            raws = [base] if not args.seed else [{**json.loads(Path(path).read_text()), "seed": s} for s in args.seed]
            worlds += [(path, schema.validate(r) if r is not base else base) for r in raws]
        except schema.SceneError as e:
            print(f"BAD {path}: {e}")
            failures += 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "manifest.jsonl").open("a") as manifest:
        for path, world in worlds:
            report = build_one(world, out)
            report["source"] = path
            manifest.write(json.dumps(report, sort_keys=True) + "\n")
            manifest.flush()
            ok = report["valid"]
            failures += not ok
            print(("OK  " if ok else "REJ ") + f"{Path(path).name} seed={world['seed']} attempts={report.get('attempts')} "
                  f"{report.get('seconds', 0):.1f}s {report.get('rejects', {})} {report.get('build_error', '')}",
                  flush=True)
    return min(failures, 125)


if __name__ == "__main__":
    sys.exit(main())
