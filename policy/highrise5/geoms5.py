"""What the physics model holds, for a check against what the browser draws: geoms5.py <world.json>. It prints JSON: the world-axis bounds of every solid outside the robot, the glass, the joints, and the view model."""
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile5 as C
import world5 as W


def bounds(m, d, i):
    """World-axis bounds from the geom's own axes and size, so they owe nothing to the view."""
    s, R, p, kind = m.geom_size[i], d.geom_xmat[i].reshape(3, 3), d.geom_xpos[i], m.geom_type[i]
    if kind == mujoco.mjtGeom.mjGEOM_BOX:
        half = np.abs(R) @ s
    elif kind == mujoco.mjtGeom.mjGEOM_SPHERE:
        half = np.full(3, s[0])
    elif kind == mujoco.mjtGeom.mjGEOM_CAPSULE:
        half = np.abs(R[:, 2]) * s[1] + s[0]
    else:
        half = np.abs(R[:, 2]) * s[1] + s[0] * np.sqrt(np.maximum(0.0, 1 - R[:, 2] ** 2))
    return [*(p - half).tolist(), *(p + half).tolist()]


def main():
    world = W.load(sys.argv[1])
    physics, view, _ = C.compile(world)
    m = mujoco.MjModel.from_xml_string(physics)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    robot = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "robot")
    solids = {}
    for i in range(m.ngeom):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
        if m.body_rootid[m.geom_bodyid[i]] == robot or not (m.geom_contype[i] or m.geom_conaffinity[i]):
            continue
        solids[name] = bounds(m, d, i)
    glass = solids.pop("glass")
    joints = {n: solids.pop(n) for n in list(solids) if n.startswith(("mullion", "transom"))}
    print(json.dumps({"solids": solids, "glass": glass, "mullions": [(joints[n][0] + joints[n][3]) / 2 for n in joints if n.startswith("mullion")],
                      "transoms": [(joints[n][2] + joints[n][5]) / 2 for n in joints if n.startswith("transom")], "view_xml": view}))


if __name__ == "__main__":
    main()
