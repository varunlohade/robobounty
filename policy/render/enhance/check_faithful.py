#!/usr/bin/env python3
"""Proves faithful_check.py can tell a faithful video from a bad one. Builds altered copies of the Blender clip with
known faults, runs the check on each, and compares the verdict with the expected one. It stops on a mismatch.

  policy/.venv/bin/python policy/render/enhance/check_faithful.py
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PASSES = ROOT / "design/render/enhance/slip"
TESTS = ROOT / "design/render/enhance/tests"
N = 216


def shift(img, dx, dy):
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), img.shape[1::-1], borderMode=cv2.BORDER_REPLICATE)


def remove(img, mask, r=6):
    """Fills a masked area from around it, in a crop so it stays quick."""
    m = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((2 * r + 1, 2 * r + 1), np.uint8))
    ys, xs = np.where(m > 0)
    if not len(xs):
        return img
    pad = 8
    x0, x1, y0, y1 = max(xs.min() - pad, 0), xs.max() + pad + 1, max(ys.min() - pad, 0), ys.max() + pad + 1
    out = img.copy()
    out[y0:y1, x0:x1] = cv2.inpaint(img[y0:y1, x0:x1], m[y0:y1, x0:x1], 3, cv2.INPAINT_TELEA)
    return out


def move_robot(img, lab, dx, dy):
    robot = lab == 1
    empty = remove(img, robot)
    m = cv2.dilate(robot.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
    m = cv2.GaussianBlur(shift(m, dx, dy), (0, 0), 1.0)[..., None]
    return (empty * (1 - m) + shift(img, dx, dy) * m).astype(np.uint8)


def restyle(img, lab, i):
    """A strong change of look with no change of geometry: flattened texture, cold grade, grain."""
    s = cv2.edgePreservingFilter(img, flags=cv2.RECURS_FILTER, sigma_s=20, sigma_r=0.2)
    s = np.clip((s / 255.0) ** 0.8 * [1.15, 1.0, 0.82] * 255, 0, 255)
    noise = np.random.default_rng(i).normal(0, 3, s.shape)
    return np.clip(s + noise, 0, 255).astype(np.uint8)


def invented(img, lab, i):
    if not 40 <= i < 120:
        return img
    out = img.copy()
    x, y = 500 + 2 * (i - 40), 620
    cv2.rectangle(out, (x, y), (x + 130, y + 90), (25, 25, 30), -1, cv2.LINE_AA)
    return out


CASES = {
    # name: (expected, function of (frame, labels, index))
    "copy": ("PASS", lambda f, l, i: f),
    "restyle": ("PASS", restyle),
    "shift_20px": ("FAIL", lambda f, l, i: shift(f, 20, 0)),
    "shift_12px": ("FAIL", lambda f, l, i: shift(f, 12, 0)),
    "robot_shift_20px": ("FAIL", lambda f, l, i: move_robot(f, l, 20, 0)),
    "robot_drift_to_40px": ("FAIL", lambda f, l, i: move_robot(f, l, int(40 * i / (N - 1)), 0)),
    "robot_removed": ("FAIL", lambda f, l, i: remove(f, l == 1)),
    "invented_object": ("FAIL", invented),
    "frame_and_tether_removed": ("FAIL", lambda f, l, i: remove(f, np.isin(l, [3, 4]), 3)),
}


def build(name, fn, clip):
    out = TESTS / f"{name}.mp4"
    if out.exists() and out.stat().st_size:
        return out
    cap = cv2.VideoCapture(str(clip))
    w, h = int(cap.get(3)), int(cap.get(4))
    p = subprocess.Popen(["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                          "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-an", str(out)], stdin=subprocess.PIPE)
    for i in range(N):
        ok, f = cap.read()
        if not ok:
            raise SystemExit("clip too short")
        lab = cv2.imread(str(PASSES / "labels" / f"frame_{i:04d}.png"), cv2.IMREAD_UNCHANGED)
        p.stdin.write(fn(f, lab, i).tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit("ffmpeg failed")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    TESTS.mkdir(parents=True, exist_ok=True)
    man = json.loads((PASSES / "manifest.json").read_text())
    clip = ROOT / man["clip"]
    bad = 0
    for name, (expect, fn) in CASES.items():
        if a.only and name not in a.only:
            continue
        video = clip if name == "copy" else build(name, fn, clip)
        r = subprocess.run(["nice", "-n", "15", sys.executable, str(HERE / "faithful_check.py"), "--video", str(video), "--passes", str(PASSES),
                            "--report", str(TESTS / f"{name}.csv")], capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.stderr:
            print(r.stderr[-400:])
        got = "PASS" if r.returncode == 0 else ("FAIL" if r.returncode == 1 else "ERROR")
        ok = got == expect
        bad += not ok
        print(f"== {name}: expected {expect}, got {got} {'OK' if ok else 'MISMATCH'}\n", flush=True)
    print("CHECK PASS" if not bad else f"CHECK FAIL ({bad})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
