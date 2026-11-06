#!/usr/bin/env python3
"""One command from a recorded run to a still or a clip.

  policy/.venv/bin/python policy/render/render.py still --trial nominal-seed1
  policy/.venv/bin/python policy/render/render.py clip  --trial nominal-seed1 --samples 64

--trial is a folder under public/trials/ or any path with the same export format. To render a new
run, first export it with policy/app_export.py. Blender runs at low priority, on the Metal GPU.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "design" / "render"
sys.path.insert(0, str(HERE))
import post  # noqa: E402
import post_v2  # noqa: E402


def blender_cmd(a, mode, frames_dir, extra=()):
    trial = Path(a.trial)
    if not trial.exists():
        trial = ROOT / "public" / "trials" / a.trial
    if not (trial / "qpos.json").exists():
        raise SystemExit(f"no recorded run at {trial}")
    sky = OUT / "_cache" / "hdri" / f"{a.sky}.exr"
    if not sky.exists():
        raise SystemExit(f"sky map missing: {sky}. See policy/render/README.md for the free download.")
    cmd = ["nice", "-n", "15", "blender", "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", str(HERE / ("scene_v2.py" if a.look == "v2" else "scene.py")), "--",
           "--trial", str(trial), "--out", str(frames_dir), "--mode", mode, "--shot", a.shot,
           "--res", a.res, "--samples", str(a.samples), "--sky", str(sky), "--fps", str(a.fps)]
    if a.t is not None:
        cmd += ["--t", str(a.t)]
    if a.no_volume:
        cmd += ["--no-volume"]
    if a.override:
        cmd += ["--override", a.override]
    return cmd + list(extra)


def run_blender(cmd, log):
    with open(log, "w") as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT))
        for line in p.stdout:
            f.write(line)
            if line.startswith(("frame ", "mean seconds", "city", "render devices")) or "Error" in line or "Traceback" in line:
                print(line.rstrip(), flush=True)
        if p.wait():
            raise SystemExit(f"blender failed, see {log}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["still", "clip"])
    ap.add_argument("--trial", default="nominal-seed1")
    ap.add_argument("--shot", default="side")
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--res", default=None)
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--sky", default="overcast_soil_puresky")
    ap.add_argument("--name", default=None, help="output name inside design/render")
    ap.add_argument("--no-volume", action="store_true")
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--no-encode", action="store_true")
    ap.add_argument("--look", default="v1", choices=["v1", "v2"], help="v2 is the close, photographic look")
    ap.add_argument("--override", default=None, help="JSON merged over the shot (v2), for framing tests")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "_logs").mkdir(exist_ok=True)
    a.res = a.res or "1920x1080"
    if a.look == "v2":
        if a.shot == "side":
            a.shot = "close"
        if a.sky == "overcast_soil_puresky":
            a.sky = "kloofendal_overcast_puresky"
        lut = post_v2.LUT_PATH
        if not lut.exists():
            subprocess.check_call(["nice", "-n", "15", "blender", "--background", "--factory-startup", "--python-exit-code", "1",
                                   "--python", str(HERE / "bake_agx.py"), "--", str(lut)], stdout=subprocess.DEVNULL)
    finish = post_v2.process if a.look == "v2" else post.process
    if a.mode == "still":
        a.samples = a.samples or 256
        name = a.name or "still"
        work = OUT / "_work" / name
        work.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        run_blender(blender_cmd(a, "still", work), OUT / "_logs" / f"{name}.log")
        finish(str(work / "still.exr"), str(OUT / f"{name}.png"))
        print(f"{OUT / (name + '.png')} in {time.time() - t0:.0f} s")
    else:
        a.samples = a.samples or 64
        name = a.name or "clip"
        work = OUT / "_work" / name
        work.mkdir(parents=True, exist_ok=True)
        extra = ["--start-frame", str(a.start_frame)]
        if a.end_frame is not None:
            extra += ["--end-frame", str(a.end_frame)]
        t0 = time.time()
        run_blender(blender_cmd(a, "clip", work, extra), OUT / "_logs" / f"{name}.log")
        if a.no_encode:
            return
        pngs = work / "png"
        pngs.mkdir(exist_ok=True)
        exrs = sorted(work.glob("frame_*.exr"))
        for i, e in enumerate(exrs):
            if a.look == "v2":
                finish(str(e), str(pngs / (e.stem + ".png")), seed=i + 1, bits=8)  # Grain dithers; 16 bits per frame cost too much disk.
            else:
                finish(str(e), str(pngs / (e.stem + ".png")), seed=i + 1)
        out = OUT / f"{name}.mp4"
        subprocess.check_call(["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps),
                               "-i", str(pngs / "frame_%04d.png"), "-c:v", "libx264", "-crf", "16", "-preset", "slow",
                               "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)])
        for e in exrs:
            e.unlink()  # The PNGs and the encode stay. Linear frames are 10 MB each.
        print(f"{out}: {len(exrs)} frames in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
