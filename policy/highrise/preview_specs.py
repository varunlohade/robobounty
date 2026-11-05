"""One readable preview per sample spec, on one contact sheet, plus a headless trial of each: preview_specs.py [--out DIR]"""
import argparse
import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "cgl")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mujoco
import numpy as np
from PIL import Image, ImageDraw

import preview
import run_trial
import sim as S
import world as W

W_PX, H_PX = 640, 360
MAX_PROCS = 4


def trial(job):
    path, out = job
    r = run_trial.run(W.load(path), 5, Path(out) / Path(path).stem)
    return {"spec": Path(path).stem, "outcome": r["outcome"], "failure": r["failure"], "coverage": r["coverage"], "time_s": r["time_s"]}


def picture(path):
    world = W.load(path)
    sim = S.Sim(world, 5)
    m = sim.m
    m.vis.global_.offwidth, m.vis.global_.offheight = W_PX, H_PX
    renderer = mujoco.Renderer(m, H_PX, W_PX, max_geom=6000)
    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 1
    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = 1
    opt = mujoco.MjvOption()
    opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = 1
    a = sim.area
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = ((a["x0"] + a["x1"]) / 2, -0.15, (a["z0"] + a["z1"]) / 2 - 0.2)
    cam.distance = 1.7 * max(a["z1"] - a["z0"], a["x1"] - a["x0"]) + 2.5
    cam.azimuth, cam.elevation = 112, -14
    renderer.update_scene(sim.d, cam, opt)
    preview.add_dirt(renderer.scene, sim)
    image = renderer.render().copy()
    renderer.close()
    return image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "runs" / "highrise" / "samples"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted((HERE / "worlds" / "samples").glob("*.json"))
    with mp.Pool(min(MAX_PROCS, len(paths))) as pool:
        rows = pool.map(trial, [(str(p), str(out)) for p in paths])
    (out / "outcomes.json").write_text(json.dumps(rows, indent=1) + "\n")
    cols = 4
    sheet = Image.new("RGB", (W_PX * cols, H_PX * ((len(paths) + cols - 1) // cols)))
    for n, (path, row) in enumerate(zip(paths, rows)):
        cell = Image.fromarray(picture(path))
        ImageDraw.Draw(cell).text((6, 4), f"{path.stem}: {row['failure'] or row['outcome']}, covered {row['coverage']:.0%}", fill=(255, 255, 255))
        sheet.paste(cell, ((n % cols) * W_PX, (n // cols) * H_PX))
    sheet.save(out / "contact_sheet.png")
    print(json.dumps(rows, indent=0))


if __name__ == "__main__":
    main()
