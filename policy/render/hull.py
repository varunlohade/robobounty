#!/usr/bin/env python3
"""One command from a recorded hull run to a Cycles still or clip. Simulated: the film says so in its corner; the scan clip has a sidecar note instead.

  policy/.venv/bin/python policy/render/hull.py still --shot lane --samples 48
  policy/.venv/bin/python policy/render/hull.py clip  --shot lane --samples 24
  policy/.venv/bin/python policy/render/hull.py clip  --shot scan --samples 24

Output goes to design/render/hull/, which git ignores.
"""
import argparse
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
OUT = ROOT / "design" / "render" / "hull"
sys.path.insert(0, str(HERE))
import hull_record as R  # noqa: E402
import post_v2  # noqa: E402

LABEL = R.SIM_NOTE
FILM = {"EXPOSURE": 1.15, "CA": 0.0012, "VIGNETTE": 0.42, "BLOOM": (0.03, 0.02), "HALATION": 0.0, "SATURATION": 1.06, "GRAIN": 0.011}
SCAN = {"EXPOSURE": 1.5, "CA": 0.0, "VIGNETTE": 0.0, "BLOOM": (0.0, 0.0), "HALATION": 0.0, "SATURATION": 1.0, "GRAIN": 0.0}


def blender_bin(a):
    exe = a.blender or os.environ.get("BLENDER") or shutil.which("blender")
    if not exe:
        raise SystemExit("blender not found. Pass --blender or set BLENDER.")
    return exe


def run_blender(a, mode, work, extra=(), log=None):
    cmd = ["nice", "-n", "15", blender_bin(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "hull_scene.py"), "--",
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
            if line.startswith(("frame ", "mean seconds", "hull built", "render devices", "no GPU")) or "Error" in line or "Traceback" in line:
                print(line.rstrip(), flush=True)
        if p.wait():
            raise SystemExit(f"blender failed, see {f.name}")


def font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def label(rgb8, text):
    """A small burned-in label, on the film only."""
    im = Image.fromarray(rgb8)
    w, h = im.size
    s = h / 1080
    f = font(max(12, int(17 * s)))
    d = ImageDraw.Draw(im, "RGBA")
    box = d.textbbox((0, 0), text, font=f)
    x, y = int(24 * s), h - int(24 * s) - (box[3] - box[1])
    pad = int(6 * s)
    d.rectangle((x - pad, y - pad, x + box[2] + pad, y + box[3] + pad), fill=(4, 14, 16, 150))
    d.text((x, y), text, font=f, fill=(226, 236, 232, 255))
    return im


def finish(exr, png, burn, seed=1):
    img = cv2.imread(str(exr), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"cannot read {exr}")
    for key, val in (FILM if burn else SCAN).items():
        setattr(post_v2, key, val)
    y = post_v2.grade(img[:, :, :3][:, :, ::-1].astype(np.float32), seed)
    arr = (y * 255 + 0.5).astype(np.uint8)
    (label(arr, LABEL) if burn else Image.fromarray(arr)).save(png)


def do_still(a):
    a.res, a.samples = a.res or "1920x1080", a.samples or 64
    name = a.name or f"still_{a.shot}"
    work = OUT / "_work" / name
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    run_blender(a, "still", work, ["--t", str(a.t)] if a.t is not None else [])
    png = OUT / f"{name}.png"
    finish(work / "still.exr", png, R.SHOTS[a.shot]["kind"] != "orbit")
    print(f"{png} in {time.time() - t0:.0f} s", flush=True)


def do_clip(a):
    shot = R.SHOTS[a.shot]
    burn = shot["kind"] != "orbit"
    a.res, a.samples = a.res or "1920x1080", a.samples or 24
    name = a.name or f"clip_{a.shot}"
    work = OUT / "_work" / name
    pngs = work / "png"
    pngs.mkdir(parents=True, exist_ok=True)
    seconds = shot["t1"] - shot["t0"] if burn else shot["seconds"]
    n = int(round(seconds * a.fps))
    if a.end_frame is not None:
        n = min(n, a.end_frame)
    t0 = time.time()
    start = a.start_frame
    while (pngs / f"frame_{start:04d}.png").exists() and start < n:
        start += 1
    if start < n:
        run_blender(a, "clip", work, ["--start-frame", str(start), "--end-frame", str(n)], log=work / f"blender_{start:04d}.log")
    rendered = time.time() - t0

    def one(i):
        e, p = work / f"frame_{i:04d}.exr", pngs / f"frame_{i:04d}.png"
        if e.exists() and not p.exists():
            finish(e, p, burn, seed=i + 1)
            e.unlink()
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, range(a.start_frame, n)))
    out = OUT / f"{name}.mp4"
    subprocess.check_call(["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", str(a.start_frame), "-i", str(pngs / "frame_%04d.png"), "-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)])
    print(f"{out}: {n - a.start_frame} frames, render {rendered:.0f} s, total {time.time() - t0:.0f} s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["still", "clip"])
    ap.add_argument("--shot", required=True, choices=sorted(R.SHOTS))
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--res", default=None)
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.03)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--device", default="metal", choices=["auto", "metal", "optix", "cuda"])
    ap.add_argument("--blender", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--override", default=None, help="JSON merged over the shot, for framing tests")
    ap.add_argument("--no-blur", action="store_true")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--crf", type=int, default=19)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not post_v2.LUT_PATH.exists():
        subprocess.check_call(["nice", "-n", "15", blender_bin(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "bake_agx.py"), "--", str(post_v2.LUT_PATH)], stdout=subprocess.DEVNULL)
    (do_still if a.mode == "still" else do_clip)(a)


if __name__ == "__main__":
    main()
