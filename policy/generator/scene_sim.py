"""Joins a gated scene to our robot, and teaches the sim where the generated solids are, with no edit to policy/highrise.

sim.py computes adhesion, leak, nose sensors and the dirt mask from world numbers, not from geoms. So SceneSim rebuilds those
inputs from the compiled geoms. See README.md for what this model still cannot do.
"""
import sys
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "highrise"))
import mujoco
import sim as S
import world as W

import gate as G

BASE_WORLD_PATH = HERE.parent / "highrise" / "worlds" / "nominal.json"
ROBOT_DEPTH_M = 0.13  # solids further out than this pass in front of the robot body
BLOCK_HEIGHT_M = W.RIDE_CLEARANCE
START_CLEAR_M = W.BODY_SIDE / 2 + W.START_CLEARANCE_M
REACH_CELL_M = 0.05
KEPT_MATERIALS = {"alu", "cream", "burgundy", "rubber", "tether"}  # the robot uses these
RECT_WINDOW_M = 12.0  # the sim tracks solids this near the assigned area


def base_world():
    return W.load(BASE_WORLD_PATH)


def merge(canonical, world):
    """canonical is gate output. Our template keeps the options, robot, tether and actuators; the scene replaces the rest."""
    root = ET.fromstring(W.build_xml(world))
    wb = root.find("worldbody")
    for child in list(wb):
        nm = child.get("name", "")
        if child.tag == "geom" or nm == "scenery":
            wb.remove(child)
    wb.find("light[@name='sun']").set("name", "base_sun")  # common names stay free for the scene
    robot = wb.find("body[@name='robot']")
    at = list(wb).index(robot)
    scene = ET.fromstring(canonical)
    asset = root.find("asset")
    for mat in list(asset):
        if mat.tag == "material" and mat.get("name") not in KEPT_MATERIALS:
            asset.remove(mat)
    scene_asset = scene.find("asset")
    if scene_asset is not None:
        if any(t.get("type") == "skybox" for t in scene_asset):
            asset.remove(asset.find("texture[@name='sky']"))
        elif asset.find("texture[@name='sky']") is not None:
            asset.find("texture[@name='sky']").set("name", "base_sky")
        asset.extend(list(scene_asset))
    kids = list(scene.find("worldbody"))
    glass = next(k for k in kids if k.tag == "geom" and k.get("name") == "glass")
    glass.set("contype", "0")
    glass.set("conaffinity", "1")
    glass.set("priority", "1")
    glass.set("friction", f"{W.friction(world)} 0.005 0.0001")
    wb[at:at] = kids
    return ET.tostring(root, encoding="unicode")


def robot_bodies(m):
    robot = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "robot")
    return {b for b in range(m.nbody) if b == robot or m.body_rootid[b] == robot}


def geom_table(m, d):
    """World boxes of all scene geoms. y0 is the outer face, y1 the inner one."""
    robot = robot_bodies(m)
    rows = []
    for g in range(m.ngeom):
        if int(m.geom_bodyid[g]) in robot:
            continue
        kind = int(m.geom_type[g])
        is_plane = kind == mujoco.mjtGeom.mjGEOM_PLANE
        R = d.geom_xmat[g].reshape(3, 3)
        c, half = m.geom_aabb[g][:3], m.geom_aabb[g][3:]
        centre = d.geom_xpos[g] + R @ c
        ext = np.abs(R) @ half
        mat = int(m.geom_matid[g])
        rgba = m.mat_rgba[mat] if mat >= 0 else m.geom_rgba[g]
        rows.append({"name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "",
                     "type": mujoco.mjtGeom(kind).name.replace("mjGEOM_", "").lower(), "solid": bool(m.geom_conaffinity[g]) and not is_plane,
                     "plane": bool(is_plane),
                     "x0": float(centre[0] - ext[0]), "x1": float(centre[0] + ext[0]), "y0": float(centre[1] - ext[1]), "y1": float(centre[1] + ext[1]),
                     "z0": float(centre[2] - ext[2]), "z1": float(centre[2] + ext[2]),
                     "rgba": [round(float(v), 3) for v in rgba]})
    return rows


def raised_rects(table, area):
    """Solids that stand off the glass within the robot's depth, as (x0, x1, z0, z1, height)."""
    out = []
    for r in table:
        if not r["solid"] or r["name"] == "glass":
            continue
        height = -r["y0"]
        if height <= 1e-4 or r["y1"] < -ROBOT_DEPTH_M:
            continue
        if r["z1"] < area["z0"] - RECT_WINDOW_M or r["z0"] > area["z1"] + RECT_WINDOW_M or r["x1"] < area["x0"] - RECT_WINDOW_M or r["x0"] > area["x1"] + RECT_WINDOW_M:
            continue
        out.append((r["x0"], r["x1"], r["z0"], r["z1"], height))
    return out


def glass_rect(table):
    g = next(r for r in table if r["name"] == "glass")
    return {"x0": g["x0"], "x1": g["x1"], "z0": g["z0"], "z1": g["z1"]}


class SceneSim(S.Sim):
    def __init__(self, world, seed):
        super().__init__(world, seed)
        table = geom_table(self.m, self.d)
        self.glass = glass_rect(table)
        self.mullions, self.transoms = [], []
        self.joint_depth, self.height = 0.0, W.MULLION_MIN_H
        self.ledge = (0.0, 0.0, 0.0, 0.0, 0.0)
        self.el_rects = raised_rects(table, self.area)
        self.el_vents, self.el_patches, self.el_cradle = [], [], None
        self.el_roller_ids = sorted(self.roller_geoms)
        self.has_elements = True
        a = self.area
        cx = a["x0"] + (np.arange(self.nx) + 0.5) * S.DIRT_CELL_M
        cz = a["z0"] + (np.arange(self.nz) + 0.5) * S.DIRT_CELL_M
        mask = np.ones((self.nz, self.nx), bool)
        g = self.glass
        mask[:, (cx < g["x0"]) | (cx > g["x1"])] = False
        mask[(cz < g["z0"]) | (cz > g["z1"]), :] = False
        for x0, x1, z0, z1, _ in self.el_rects:
            mask[np.ix_((cz > z0) & (cz < z1), (cx > x0) & (cx < x1))] = False
        if not mask.any():
            raise W.WorldError("no glass to clean")
        self.dirt_mask = mask


def install(scene_text):
    """Makes this process run the scene. Re-gates first: a worker trusts no file it did not check."""
    merged = merge(G.check(scene_text), base_world())
    W.build_xml = lambda _world: merged
    S.Sim = SceneSim
    return merged


def start_blocked(table, world):
    sx, sz = W.start_pose(world)
    for r in table:
        if r["solid"] and r["name"] != "glass" and r["y0"] < 0 and r["y1"] > -ROBOT_DEPTH_M:
            if r["x0"] < sx + START_CLEAR_M and r["x1"] > sx - START_CLEAR_M and r["z0"] < sz + START_CLEAR_M and r["z1"] > sz - START_CLEAR_M:
                return True
    return False


def reachable_share(rects, world):
    """Flood fill of body centres from the start, on a 5 cm grid. Share of the assigned area the centre can reach."""
    a = W.area(world)
    sx, sz = W.start_pose(world)
    x0, x1 = a["x0"] - 0.3, a["x1"] + 0.3
    z0, z1 = a["z0"] - 0.3, a["z1"] + 0.4
    nx, nz = int((x1 - x0) / REACH_CELL_M) + 1, int((z1 - z0) / REACH_CELL_M) + 1
    xs, zs = x0 + np.arange(nx) * REACH_CELL_M, z0 + np.arange(nz) * REACH_CELL_M
    free = np.ones((nz, nx), bool)
    half = W.BODY_SIDE / 2
    for rx0, rx1, rz0, rz1, h in rects:
        if h > BLOCK_HEIGHT_M:
            free[np.ix_((zs > rz0 - half) & (zs < rz1 + half), (xs > rx0 - half) & (xs < rx1 + half))] = False
    i0, k0 = int(np.argmin(np.abs(zs - sz))), int(np.argmin(np.abs(xs - sx)))
    if not free[i0, k0]:
        return 0.0
    seen = np.zeros_like(free)
    seen[i0, k0] = True
    queue = deque([(i0, k0)])
    while queue:
        i, k = queue.popleft()
        for di, dk in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nk = i + di, k + dk
            if 0 <= ni < nz and 0 <= nk < nx and free[ni, nk] and not seen[ni, nk]:
                seen[ni, nk] = True
                queue.append((ni, nk))
    inside = np.ix_((zs >= a["z0"]) & (zs <= a["z1"]), (xs >= a["x0"]) & (xs <= a["x1"]))
    return float(seen[inside].mean())
