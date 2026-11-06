#!/usr/bin/env python3
"""One command from a recorded inspection run to a Cycles still or clip. Simulated: every output says so.

  policy/.venv/bin/python policy/render/inspection.py still --shot plant --res 2560x1440 --samples 256
  policy/.venv/bin/python policy/render/inspection.py clip  --shot fall --samples 24
  policy/.venv/bin/python policy/render/inspection.py all   --device optix

--device auto|metal|optix|cuda. Output goes to design/render/inspection/, which git ignores. See GPU.md for a rented machine.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "design" / "render" / "inspection"
sys.path.insert(0, str(HERE))
import inspection_record as R  # noqa: E402
import post_v2  # noqa: E402

STILLS = {"plant": "plant route", "low_pipe": "low pipe", "leak_corner": "leak at the corner", "dropped_tray": "dropped tray"}
CLIPS = {"plant_route": "plant route", "fall": "fall at the low pipe"}
EXPOSURE = 1.0


def blender_bin(a):
    exe = a.blender or os.environ.get("BLENDER") or shutil.which("blender")
    if not exe:
        raise SystemExit("blender not found. Pass --blender or set BLENDER.")
    return exe


def run_blender(a, mode, work, extra=(), log=None):
    cmd = ["nice", "-n", "15", blender_bin(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "inspection_scene.py"), "--",
           "--shot", a.shot, "--out", str(work), "--mode", mode, "--res", a.res, "--samples", str(a.samples), "--threshold", str(a.threshold), "--device", a.device, "--fps", str(a.fps)]
    if a.override:
        cmd += ["--override", a.override]
    if a.no_blur:
        cmd += ["--no-blur"]
    cmd += list(extra)
    with open(log or work / "blender.log", "w") as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT))
        for line in p.stdout:
            f.write(line)
            if line.startswith(("frame ", "mean seconds", "plant built", "render devices", "no GPU")) or "Error" in line or "Traceback" in line:
                print(line.rstrip(), flush=True)
        if p.wait():
            raise SystemExit(f"blender failed, see {f.name}")


def ensure_lut(a):
    if not post_v2.LUT_PATH.exists():
        subprocess.check_call(["nice", "-n", "15", blender_bin(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "bake_agx.py"), "--", str(post_v2.LUT_PATH)], stdout=subprocess.DEVNULL)


def font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def label(rgb8, text):
    """Burns the label in: every output says Simulated."""
    im = Image.fromarray(rgb8)
    w, h = im.size
    s = h / 1080
    f = font(max(12, int(19 * s)))
    d = ImageDraw.Draw(im, "RGBA")
    box = d.textbbox((0, 0), text, font=f)
    x, y = int(26 * s), h - int(26 * s) - (box[3] - box[1])
    pad = int(8 * s)
    d.rectangle((x - pad, y - pad, x + box[2] + pad, y + box[3] + pad), fill=(10, 10, 10, 165))
    d.text((x, y), text, font=f, fill=(238, 238, 234, 255))
    return im


def finish(exr, png, text, seed=1):
    img = cv2.imread(str(exr), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"cannot read {exr}")
    post_v2.EXPOSURE = EXPOSURE
    y = post_v2.grade(img[:, :, :3][:, :, ::-1].astype(np.float32), seed)
    label((y * 255 + 0.5).astype(np.uint8), text).save(png)


def do_still(a, res=None, samples=None):
    shot = dict(R.SHOTS[a.shot])
    a.res, a.samples = res or a.res or "2560x1440", samples or a.samples or 256
    name = a.name or f"still_{a.shot}"
    work = OUT / "_work" / name
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    run_blender(a, "still", work, ["--t", str(a.t)] if a.t is not None else [])
    t = a.t if a.t is not None else shot["t"]
    png = OUT / f"{name}.png"
    verdict = R.Record(shot["run"]).result["verdict"]
    finish(work / "still.exr", png, f"Simulated  |  ANYmal C, upstream policy  |  {STILLS.get(a.shot, a.shot)}  |  t = {t:.1f} s  |  run: {verdict}")
    print(f"{png} in {time.time() - t0:.0f} s", flush=True)
    return png


def do_clip(a):
    shot = R.SHOTS[a.shot]
    a.res, a.samples = a.res or "1920x1080", a.samples or 24
    name = a.name or f"clip_{a.shot}"
    work = OUT / "_work" / name
    work.mkdir(parents=True, exist_ok=True)
    rec = R.Record(shot["run"])
    pngs = work / "png"
    pngs.mkdir(exist_ok=True)
    n = int(round((shot["t1"] - shot["t0"]) * a.fps))
    if a.end_frame is not None:
        n = min(n, a.end_frame)
    t0 = time.time()
    start = a.start_frame
    while (pngs / f"frame_{start:04d}.png").exists() and start < n:
        start += 1  # A stopped run picks up where it stopped.
    if start < n:
        run_blender(a, "clip", work, ["--start-frame", str(start), "--end-frame", str(n)], log=work / f"blender_{start:04d}.log")
    rendered = time.time() - t0

    def one(i):
        e = work / f"frame_{i:04d}.exr"
        p = pngs / f"frame_{i:04d}.png"
        if e.exists() and not p.exists():
            t = shot["t0"] + i / a.fps
            finish(e, p, f"Simulated  |  ANYmal C, upstream policy  |  {CLIPS.get(a.shot, a.shot)}  |  t = {t:.1f} s  |  run: {rec.result['verdict']}", seed=i + 1)
            e.unlink()
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, range(a.start_frame, n)))
    out = OUT / f"{name}.mp4"
    subprocess.check_call(["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", str(a.start_frame), "-i", str(pngs / "frame_%04d.png"), "-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)])
    print(f"{out}: {n - a.start_frame} frames, render {rendered:.0f} s, total {time.time() - t0:.0f} s", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["still", "clip", "probe"])
    ap.add_argument("--shot", required=True)
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--res", default=None)
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--device", default="auto", choices=["auto", "metal", "optix", "cuda"])
    ap.add_argument("--blender", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--override", default=None, help="JSON merged over the shot, for framing tests")
    ap.add_argument("--no-blur", action="store_true")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ensure_lut(a)
    if a.mode == "still":
        do_still(a)
    elif a.mode == "clip":
        do_clip(a)


if __name__ == "__main__":
    main()
