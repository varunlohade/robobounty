#!/usr/bin/env python3
"""Checks that an enhanced video keeps the recorded motion. Physics is the reference: the robot path comes from
the trial's qpos.json through the logged camera. No model takes part.

  policy/.venv/bin/python policy/render/enhance/faithful_check.py --video OUT.mp4 --passes design/render/enhance/slip

Output frame i is compared with control frame i. Any output size works; x and y scale separately.

The tracker has only the robot's expected outline and the output's gradients, in a window around the recorded
position. So it does not depend on colour or style, and it can report a position that differs from the record.

PASS needs all of these. They come from the robot's size and from what a viewer could notice, not from a test result.
  position   95th percentile error <= 0.020 m (about 6% of the 0.36 m body), worst frame <= 0.050 m
  found      robot found in at least 95% of the frames
  frames     at most 6 control frames missing (the model trims its output to whole chunks)
  invented   no area that differs from the source by over 40 grey levels (after matching tones), with over 25% of the
             robot's area, in the building zone for 12 or more frames in a row
  structure  frame, tower and tether outlines are at least 60% as visible as in the source clip

Limits. The invented check cannot name an object. It flags any large change, such as a new reflection, so a FAIL
there needs a human look. It misses objects smaller than its area limit or close to the source's tone. It does not
cover the sky and city, which are art and out of focus. A body's position can be right while its details are wrong.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
GRID = (1280, 720)
SEARCH = 60  # grid pixels each way

P95_M, MAX_M = 0.020, 0.050
FOUND_MIN, MIN_SCORE = 0.95, 0.30
MISSING_FRAMES = 6
BLOB_FRAMES, BLOB_ROBOT_RATIO, BLOB_LEVELS = 12, 0.25, 40  # frames, share of the robot's area, grey levels of 255
RECALL_RATIO = 0.60
EDGE_LOW, EDGE_HIGH = 3.0, 6.0  # times the zone's median gradient
SHUTTER = 0.5  # frames; scene.py renders with this motion blur shutter


def recorded_path(man, trial):
    """Robot centre in clip pixels and camera depth for each frame, from qpos.json and the logged camera."""
    q = json.loads((trial / "qpos.json").read_text())
    frames, hz = np.array(q["frames"], float), q["hz"]
    w, h = man["width"], man["height"]
    rows = []
    for c in man["cameras"]:
        f = c["t"] * hz
        i = min(int(f), len(frames) - 2)
        u = f - i
        world = frames[i, :3] * (1 - u) + frames[i + 1, :3] * u
        cam = np.linalg.inv(np.array(c["cam_matrix"]))
        x, y, z = (cam @ np.append(world, 1.0))[:3]
        fpx = c["lens_mm"] / c["sensor_mm"] * w
        px, py = w / 2 + fpx * x / -z, h / 2 - fpx * y / -z
        sx, sy = c["screen"][0] * w, (1 - c["screen"][1]) * h
        if max(abs(px - sx), abs(py - sy)) > 0.5:
            raise SystemExit(f"frame {c['frame']}: recorded path ({px:.2f}, {py:.2f}) differs from the pass log ({sx:.2f}, {sy:.2f})")
        rows.append((px, py, -z, -z / fpx))
    return np.array(rows)


def gradient(gray):
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.0)
    return cv2.magnitude(cv2.Scharr(g, cv2.CV_32F, 1, 0), cv2.Scharr(g, cv2.CV_32F, 0, 1))


def blurred_mask(mask, v):
    """The robot's outline as the shutter would smear it along its recorded motion."""
    m = mask.astype(np.float32)
    if np.hypot(*v) * SHUTTER < 1:
        return m
    acc = np.zeros_like(m)
    steps = np.linspace(-SHUTTER / 2, SHUTTER / 2, 7)
    for s in steps:
        acc += cv2.warpAffine(m, np.float32([[1, 0, v[0] * s], [0, 1, v[1] * s]]), m.shape[::-1])
    return acc / len(steps)


def track(grad, mask, v):
    """Returns (dx, dy, score): the offset from the expected place, on the grid."""
    ys, xs = np.where(mask > 0)
    if len(xs) < 20:
        return None
    H, W = grad.shape
    pad = 6
    x0, x1, y0, y1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, W), max(ys.min() - pad, 0), min(ys.max() + pad + 1, H)
    tmpl = gradient(blurred_mask(mask, v) * 255)[y0:y1, x0:x1]
    sx0, sx1, sy0, sy1 = max(x0 - SEARCH, 0), min(x1 + SEARCH, W), max(y0 - SEARCH, 0), min(y1 + SEARCH, H)
    r = cv2.matchTemplate(grad[sy0:sy1, sx0:sx1], tmpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (bx, by) = cv2.minMaxLoc(r)
    fx = fy = 0.0
    if 0 < bx < r.shape[1] - 1:
        d = r[by, bx - 1] - 2 * r[by, bx] + r[by, bx + 1]
        fx = 0.5 * (r[by, bx - 1] - r[by, bx + 1]) / d if d < 0 else 0.0
    if 0 < by < r.shape[0] - 1:
        d = r[by - 1, bx] - 2 * r[by, bx] + r[by + 1, bx]
        fy = 0.5 * (r[by - 1, bx] - r[by + 1, bx]) / d if d < 0 else 0.0
    return bx + fx + sx0 - x0, by + fy + sy0 - y0, float(score)


def canny(gray, zone):
    """Edges relative to the building's own texture. A whole-frame threshold follows the bright sky edge and misses
    dark objects on dark glass."""
    g = cv2.GaussianBlur(gray, (0, 0), 1.0)
    dx, dy = cv2.Sobel(g, cv2.CV_16S, 1, 0), cv2.Sobel(g, cv2.CV_16S, 0, 1)
    typical = max(float(np.median(cv2.magnitude(dx.astype(np.float32), dy.astype(np.float32))[zone])), 1.0)
    return cv2.Canny(dx, dy, EDGE_LOW * typical, EDGE_HIGH * typical, L2gradient=True) > 0


def tone_matched(gray, ref, where):
    """The output with the source's tones, so a new grade or exposure does not read as a new object."""
    a, _ = np.histogram(gray[where], 256, (0, 256))
    b, _ = np.histogram(ref[where], 256, (0, 256))
    lut = np.interp(np.cumsum(a) / max(a.sum(), 1), np.cumsum(b) / max(b.sum(), 1), np.arange(256))
    return lut[gray].astype(np.float32)


def boundary(mask):
    k = np.ones((3, 3), np.uint8)
    return (cv2.dilate(mask, k) != cv2.erode(mask, k))


def grown(mask, r):
    return cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0


class Blobs:
    """Links large changed areas across frames. One that lasts is a candidate object."""

    def __init__(self):
        self.live, self.flagged = [], []

    def add(self, frame, boxes):
        next_live = []
        for b in boxes:
            x, y, w, h = b
            found = None
            for t in self.live:
                X, Y, W, H = t["box"]
                if x < X + W and X < x + w and y < Y + H and Y < y + h:
                    found = t
                    break
            if found:
                self.live.remove(found)
                found["box"], found["n"] = b, found["n"] + 1
                next_live.append(found)
            else:
                next_live.append({"box": b, "n": 1, "start": frame})
        for t in next_live:
            if t["n"] == BLOB_FRAMES:
                self.flagged.append(t)
        self.live = next_live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--passes", type=Path, default=ROOT / "design/render/enhance/slip")
    ap.add_argument("--source", type=Path, default=None, help="default: the clip named in the manifest")
    ap.add_argument("--report", type=Path, default=None, help="per-frame CSV path; default beside the video")
    a = ap.parse_args()

    man = json.loads((a.passes / "manifest.json").read_text())
    n_ref = man["frames"]
    if n_ref != len(man["cameras"]):
        raise SystemExit("manifest camera count differs from its frame count")
    L = man["labels"]
    trial = Path(man["trial"])
    trial = trial if trial.is_absolute() else ROOT / trial
    source = a.source or Path(man["clip"])
    source = source if source.is_absolute() else ROOT / source
    path = recorded_path(man, trial)
    vel = np.gradient(path[:, :2], axis=0) * (GRID[0] / man["width"], GRID[1] / man["height"])
    ref_per_grid = man["width"] / GRID[0]

    cap, src = cv2.VideoCapture(str(a.video)), cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise SystemExit(f"cannot read {a.video}")
    out_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    out_per_ref = out_w / man["width"]

    rows, recall = [], {k: [0.0, 0.0, 0] for k in ("frame", "tower", "tether")}
    blobs = Blobs()
    n_out = 0
    for i in range(n_ref):
        ok, frame = cap.read()
        ok2, sframe = src.read()
        if not ok:
            break
        if not ok2:
            raise SystemExit(f"source clip ended at frame {i}")
        n_out += 1
        gray = cv2.cvtColor(cv2.resize(frame, GRID, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        sgray = cv2.cvtColor(cv2.resize(sframe, GRID, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        lab = cv2.resize(cv2.imread(str(a.passes / "labels" / f"frame_{i:04d}.png"), cv2.IMREAD_UNCHANGED), GRID, interpolation=cv2.INTER_NEAREST)
        robot = (lab == L["robot"]).astype(np.uint8)

        px, py, depth, m_per_px = path[i]
        res = track(gradient(gray), robot, vel[i])
        if res is None:
            rows.append({"frame": i, "expected_x": px, "expected_y": py, "status": "out_of_frame"})
        else:
            dx, dy, score = res
            err_ref = float(np.hypot(dx, dy)) * ref_per_grid
            status = "found" if score >= MIN_SCORE else "lost"
            rows.append({"frame": i, "expected_x": px, "expected_y": py, "tracked_x": px + dx * ref_per_grid, "tracked_y": py + dy * ref_per_grid,
                         "error_px_clip": err_ref, "error_px_output": err_ref * out_per_ref, "error_m": err_ref * m_per_px,
                         "score": score, "status": status})

        zone = np.isin(lab, [L["glass"], L["frame"], L["tower"]])
        e_out, e_src = canny(gray, zone), canny(sgray, zone)
        for k in recall:
            b = boundary((lab == L[k]).astype(np.uint8))
            if b.sum() < 20:
                continue
            recall[k][0] += float((b & grown(e_out, 3)).sum()) / b.sum()
            recall[k][1] += float((b & grown(e_src, 3)).sum()) / b.sum()
            recall[k][2] += 1

        moving = grown(np.isin(lab, [L["robot"], L["tether"]]), 8)
        check = zone & ~moving
        changed = (np.abs(cv2.GaussianBlur(tone_matched(gray, sgray, check), (0, 0), 3.0) - cv2.GaussianBlur(sgray.astype(np.float32), (0, 0), 3.0)) > BLOB_LEVELS) & check
        count, _, stats, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8))
        min_area = BLOB_ROBOT_RATIO * max(int(robot.sum()), 1)
        blobs.add(i, [tuple(int(v) for v in stats[j, :4]) for j in range(1, count) if stats[j, 4] >= min_area])

    report = a.report or a.video.with_suffix(".faithful.csv")
    report.parent.mkdir(parents=True, exist_ok=True)
    fields = ["frame", "expected_x", "expected_y", "tracked_x", "tracked_y", "error_px_clip", "error_px_output", "error_m", "score", "status"]
    with open(report, "w", newline="") as f:
        wr = csv.DictWriter(f, fields)
        wr.writeheader()
        wr.writerows(rows)

    measured = [r for r in rows if r["status"] != "out_of_frame"]
    found = [r for r in measured if r["status"] == "found"]
    errs = np.array([r["error_m"] for r in found]) if found else np.array([np.inf])
    px_err = np.array([r["error_px_clip"] for r in found]) if found else np.array([np.inf])
    p50, p95, worst = np.percentile(errs, 50), np.percentile(errs, 95), errs.max()
    found_share = len(found) / max(len(measured), 1)
    missing = n_ref - n_out

    checks = [
        ("position p95", p95 <= P95_M, f"{p95:.4f} m ({np.percentile(px_err, 95):.1f} clip px), limit {P95_M} m; median {p50:.4f} m"),
        ("position worst", worst <= MAX_M, f"{worst:.4f} m ({px_err.max():.1f} clip px), limit {MAX_M} m"),
        ("robot found", found_share >= FOUND_MIN, f"{found_share * 100:.1f}% of {len(measured)} frames, limit {FOUND_MIN * 100:.0f}%"),
        ("frame count", missing <= MISSING_FRAMES, f"{n_out} of {n_ref}, up to {MISSING_FRAMES} may be missing"),
        ("invented objects", not blobs.flagged, f"{len(blobs.flagged)} lasting blobs" + "".join(f"; from frame {t['start']} at grid box {t['box']}" for t in blobs.flagged[:4])),
    ]
    for k, (o, s, c) in recall.items():
        if c:
            ratio = o / max(s, 1e-6)
            checks.append((f"{k} outline", ratio >= RECALL_RATIO, f"{ratio:.2f} of the source's ({o / c:.2f} vs {s / c:.2f}), limit {RECALL_RATIO}"))
    print(f"{a.video}: {n_out} frames at {out_w} px wide")
    for name, ok, msg in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {msg}")
    for r in sorted(found, key=lambda r: -r["error_m"])[:3]:
        print(f"  worst frame {r['frame']}: {r['error_m']:.4f} m, {r['error_px_clip']:.1f} clip px, {r['error_px_output']:.1f} output px, score {r['score']:.2f}")
    print(f"  per-frame report: {report}")
    passed = all(ok for _, ok, _ in checks)
    print("PASS" if passed else "FAIL")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
