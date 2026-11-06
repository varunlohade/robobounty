#!/usr/bin/env python3
"""Exports conditioning passes for one recorded Blender clip, at low priority. Physics stays the source: the passes
use the recorded poses, and Blender stops if its camera or robot differs from the clip's pose log.

  policy/.venv/bin/python policy/render/enhance/export_passes.py --clip design/render/clip_slip.mp4 \
      --trial design/render/_runs/t0010 --shot slip --poses design/render/_work/clip_slip/poses_0000_0216.json

Output, under design/render/enhance/<shot>/:
  labels/ one PNG per frame: 0 sky and city, 1 robot, 2 glass, 3 tether, 4 frame, 5 tower
  depth_mm/ one 16-bit PNG per frame, millimetres along the view axis, 0 for sky
  controls/<WxH>/ rgb.mp4, depth.mp4 (near is bright, sky is black), seg.mp4, edge.mp4
  manifest.json with the camera, clip and trial
"""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "design" / "render" / "enhance"
SIZES = [(832, 480), (1280, 720)]
SEG_BGR = np.array([[60, 40, 30], [40, 40, 230], [200, 160, 60], [40, 220, 240], [80, 200, 80], [180, 80, 200]], np.uint8)


def writer(path, w, h, fps, pix="bgr24"):
    cmd = ["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", "-an", str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def render(a, exr_dir):
    cmd = ["nice", "-n", "15", "blender", "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", str(HERE / "passes_scene.py"), "--", "--trial", str(a.trial), "--shot", a.shot, "--poses", str(a.poses),
           "--out", str(exr_dir), "--fps", str(a.fps)]
    if a.end_frame is not None:
        cmd += ["--end-frame", str(a.end_frame)]
    subprocess.check_call(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL)


def edges(labels, depth_mm):
    """White on black: label changes and depth steps over 2%. Geometry only, no RGB."""
    d = depth_mm.astype(np.float32)
    k = np.ones((3, 3), np.uint8)
    lab = cv2.dilate(labels, k) != cv2.erode(labels, k)
    hi, lo = cv2.dilate(d, k), cv2.erode(d, k)
    step = (hi - lo) > 0.02 * np.maximum(lo, 1.0)
    return (lab | step).astype(np.uint8) * 255


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--shot", required=True)
    ap.add_argument("--poses", type=Path, required=True)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--end-frame", type=int, default=None, help="stop early, for a test")
    a = ap.parse_args()

    base = OUT / a.shot
    exr_dir, lab_dir, dep_dir = base / "_exr", base / "labels", base / "depth_mm"
    for d in (exr_dir, lab_dir, dep_dir):
        d.mkdir(parents=True, exist_ok=True)
    render(a, exr_dir)
    exrs = sorted(exr_dir.glob("frame_*.exr"))

    cameras = []
    for p in sorted(exr_dir.glob("cameras_*.json")):
        cameras += json.loads(p.read_text())

    # Near limit over the whole clip, so a pixel's depth value never flickers between frames.
    near = np.inf
    for e in exrs:
        img = cv2.imread(str(e), cv2.IMREAD_UNCHANGED)
        labels = np.rint(img[:, :, 1]).astype(np.uint8)
        depth = np.where(img[:, :, 2] > 0, img[:, :, 2], 0.0)
        near = min(near, float(np.percentile(depth[depth > 0], 0.1)))
        mm = np.clip(depth * 1000.0, 0, 65535).astype(np.uint16)
        cv2.imwrite(str(lab_dir / (e.stem + ".png")), labels)
        cv2.imwrite(str(dep_dir / (e.stem + ".png")), mm)
        e.unlink()
    shutil.rmtree(exr_dir)

    cap = cv2.VideoCapture(str(a.clip))
    outs = {}
    for w, h in SIZES:
        d = base / "controls" / f"{w}x{h}"
        d.mkdir(parents=True, exist_ok=True)
        outs[(w, h)] = {n: writer(d / f"{n}.mp4", w, h, a.fps) for n in ("rgb", "depth", "seg", "edge")}
    for lp in sorted(lab_dir.glob("frame_*.png")):
        labels = cv2.imread(str(lp), cv2.IMREAD_UNCHANGED)
        mm = cv2.imread(str(dep_dir / lp.name), cv2.IMREAD_UNCHANGED)
        ok, rgb = cap.read()
        if not ok:
            raise SystemExit(f"clip ended before {lp.name}")
        for (w, h), o in outs.items():
            lab = cv2.resize(labels, (w, h), interpolation=cv2.INTER_NEAREST)
            dep = cv2.resize(mm, (w, h), interpolation=cv2.INTER_NEAREST)
            inv = np.where(dep > 0, np.clip(near * 1000.0 / np.maximum(dep, 1), 0, 1), 0.0)
            gray = (inv * 255).astype(np.uint8)
            o["rgb"].stdin.write(cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA).tobytes())
            o["depth"].stdin.write(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR).tobytes())
            o["seg"].stdin.write(SEG_BGR[lab].tobytes())
            o["edge"].stdin.write(cv2.cvtColor(edges(lab, dep), cv2.COLOR_GRAY2BGR).tobytes())
    for o in outs.values():
        for p in o.values():
            p.stdin.close()
            if p.wait():
                raise SystemExit("ffmpeg failed")

    frames, width, height = len(exrs), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    manifest = {"clip": str(a.clip), "trial": str(a.trial), "shot": a.shot, "fps": a.fps, "frames": frames,
                "width": width, "height": height, "near_m": near,
                "labels": {"sky_city": 0, "robot": 1, "glass": 2, "tether": 3, "frame": 4, "tower": 5}, "cameras": cameras}
    (base / "manifest.json").write_text(json.dumps(manifest))
    print(f"{base}: {frames} frames, near {near:.2f} m")


if __name__ == "__main__":
    main()
