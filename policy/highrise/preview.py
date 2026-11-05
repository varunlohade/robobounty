"""One readable preview: preview.py <run dir> <out.png> [--times t1 t2 ...]. Graphics stay simple; a later worker owns final renders.

Frames come from replaying the stored actions, so they show recorded physics and the real dirt grid.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "cgl")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mujoco
import numpy as np
from PIL import Image, ImageDraw

import replay
import sim as S
import world as W

W_PX, H_PX = 960, 540


def add_dirt(scene, sim):
    a = sim.area
    h = S.DIRT_CELL_M / 2
    mat = np.eye(3).flatten()
    for iz in range(sim.nz):
        for ix in range(sim.nx):
            if not sim.dirt_mask[iz, ix] or scene.ngeom >= scene.maxgeom - 1:
                continue
            level = sim.dirt[iz, ix]
            if level <= S.CLEAN_THRESHOLD:
                continue
            pos = np.array([a["x0"] + (ix + 0.5) * S.DIRT_CELL_M, -0.002, a["z0"] + (iz + 0.5) * S.DIRT_CELL_M])
            alpha = min(0.85, 0.45 + 0.4 * level)
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom], mujoco.mjtGeom.mjGEOM_BOX, np.array([h, 0.001, h]), pos, mat,
                                np.array([0.55, 0.47, 0.34, alpha], np.float32))
            scene.ngeom += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("out")
    ap.add_argument("--times", type=float, nargs="*")
    a = ap.parse_args()
    run = Path(a.run_dir)
    stored = json.loads((run / "result.json").read_text())
    end = stored["time_s"]
    first = min([v["t"] for v in stored["fired"].values()], default=None)
    times = a.times or ([end * 0.02, end * 0.3, max(first - 2, 0), first, min(first + 3, end), end] if first and first < end
                        else [end * f for f in (0.02, 0.2, 0.4, 0.6, 0.8, 1.0)])
    ticks = sorted({max(0, round(t * S.CONTROL_HZ) - 1) for t in times})
    frames = {}

    def keep(sim, i):
        if i not in ticks:
            return
        if "r" not in frames:
            m = sim.m
            m.vis.global_.offwidth, m.vis.global_.offheight = W_PX, H_PX
            frames["r"] = mujoco.Renderer(m, H_PX, W_PX, max_geom=6000)
            frames["r"].scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 1
            frames["r"].scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = 1
            frames["r"].scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = 1
            opt = mujoco.MjvOption()
            opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = 1
            frames["opt"] = opt
        x, z = sim.body_xz()
        out = []
        for view in ("close", "wide"):
            cam = mujoco.MjvCamera()
            cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            a_ = sim.area
            if view == "close":
                cam.lookat[:] = ((a_["x0"] + a_["x1"]) / 2, -0.1, (a_["z0"] + a_["z1"]) / 2)
                cam.distance = 1.35 * max(a_["z1"] - a_["z0"], a_["x1"] - a_["x0"]) + 2.0
                cam.azimuth, cam.elevation = 104, -12
            else:
                cam.lookat[:] = (x + 2.0, -4.0, z - 6.0)
                cam.distance = 12.0
                cam.azimuth, cam.elevation = 142, -22
            r = frames["r"]
            r.update_scene(sim.d, cam, frames["opt"])
            add_dirt(r.scene, sim)
            out.append(r.render().copy())
        frames[i] = (sim.t, out, round(sim.dp), round(sim.coverage(), 3), round(float(sim.tension_tick)))

    report = replay.replay(run, keep=keep)
    if not report["match"]:
        raise SystemExit("replay did not match, so the preview would not show the recorded run")
    n = len(ticks)
    sheet = Image.new("RGB", (W_PX // 2 * 2 * 1, H_PX // 2 * n))
    for row, i in enumerate(ticks):
        t, views, dp, cov, ten = frames[i]
        for col, im in enumerate(views):
            sheet.paste(Image.fromarray(im).resize((W_PX // 2, H_PX // 2)), (col * W_PX // 2, row * H_PX // 2))
        ImageDraw.Draw(sheet).text((6, row * H_PX // 2 + 4), f"t={t:.1f}s pressure {dp} Pa covered {cov:.0%} tether {ten} N", fill=(255, 255, 255))
    sheet.save(a.out)
    print(a.out, "failure", stored["failure"], "fired", list(stored["fired"]))


if __name__ == "__main__":
    main()
