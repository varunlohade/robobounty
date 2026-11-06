#!/usr/bin/env python3
"""Proves that a render shows the record. Reads the record directly, not through the render's own code.

  policy/.venv/bin/python policy/render/inspection_check.py --shot leak_corner --work design/render/inspection/_work/still_leak_corner

1. Logged poses: every body against the record at every logged frame. Worst error under 0.1 mm. No time past the record's end.
2. Pixels: Cycles renders only the robot's base, at 3 or more recorded times of the shot. The silhouette's box must match the record's pose put through a plain pinhole projection, within 2 pixels at 960x540. The projected root must agree with Blender's own within 0.2 pixels.
3. Solids: every physics solid in the record appears, at its recorded box, within 3 mm. Wet patches: the drawn water matches the record's circles.
4. Visual-only scenery stays away from the robot: no box touches any recorded body point.
"""
import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_REC = ROOT / "policy" / "packs" / "inspection" / "out"
sys.path.insert(0, str(HERE))
import inspection_record as IR  # noqa: E402 (the shot table only)

bad = []


def report(ok, text):
    print(("OK   " if ok else "FAIL ") + text, flush=True)
    if not ok:
        bad.append(text)


def qrot(q, v):
    x, y, z, w = q
    u = np.array((x, y, z))
    return v + 2.0 * np.cross(u, np.cross(u, v) + w * v)


def recorded(t_arr, body_q, t):
    f = (t - t_arr[0]) / (t_arr[1] - t_arr[0])
    i = min(int(f), len(t_arr) - 2)
    u = f - i
    a, b = body_q[i], body_q[i + 1].copy()
    b[(a[:, 3:7] * b[:, 3:7]).sum(axis=1) < 0, 3:7] *= -1
    q = a[:, 3:7] * (1 - u) + b[:, 3:7] * u
    return a[:, :3] * (1 - u) + b[:, :3] * u, q / np.linalg.norm(q, axis=1, keepdims=True)


def project(p, row):
    """Plain pinhole: logged camera matrix, lens and sensor."""
    C = np.array(row["cam"])
    d = (np.atleast_2d(p) - C[:3, 3]) @ C[:3, :3]
    w, h = row["res"]
    f = row["lens"] / row["sensor"]
    u = 0.5 + f * d[:, 0] / -d[:, 2]
    v = 0.5 + f * (w / h) * d[:, 1] / -d[:, 2]
    return np.column_stack([u * w, (1 - v) * h])


def base_vertices():
    meta = json.loads((ROOT / "public/robots/anymal_c/robot.json").read_text())
    raw = (ROOT / "public/robots/anymal_c/robot.bin").read_bytes()
    pos = np.frombuffer(raw, np.float32, meta["vertices"] * 3, meta["layout"]["position"]).reshape(-1, 3).astype(np.float64)
    idx = np.frombuffer(raw, np.uint32, meta["indices"], meta["layout"]["index"])
    ids = np.concatenate([idx[p["first_index"]:p["first_index"] + p["index_count"]] for p in meta["parts"] if p["body"] == "base"])
    return pos[np.unique(ids)]


def prim_box(s):
    p, q, size = np.array(s["pos"]), np.array(s["quat"]), s["size"]
    x, y, z, w = q
    m = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    if s["type"] == "box":
        e = np.abs(m) @ np.array(size)
    else:
        r, h = size
        ax = m[:, 2]
        if s["type"] == "capsule":
            e = np.abs(ax) * h + r
        else:
            e = np.abs(ax) * h + r * np.sqrt(np.maximum(1 - ax * ax, 0))
    return p - e, p + e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--blender", default=None)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-probe", action="store_true")
    a = ap.parse_args()
    work = Path(a.work)
    shot = IR.SHOTS[a.shot]
    d = np.load(OUT_REC / f"{shot['run']}.npz")
    t_arr, body_q = d["t"].astype(np.float64), d["body_q"].astype(np.float64)
    labels = json.loads(str(d["meta"]))["body_labels"]
    with gzip.open(OUT_REC / f"{shot['run']}.replay.json.gz") as f:
        replay = json.load(f)

    # 1. Logged poses.
    rows = []
    for p in sorted(work.glob("poses_still_*.json")) + sorted(work.glob("poses_clip_*.json")):
        rows += json.loads(p.read_text())
    report(bool(rows), f"{len(rows)} logged frames")
    worst = 0.0
    for r in rows:
        pos, _ = recorded(t_arr, body_q, r["t"])
        for i, b in enumerate(labels):
            worst = max(worst, float(np.linalg.norm(np.array(r["bodies"][b]["loc"]) - pos[i])))
    report(worst < 1e-4, f"poses: worst body error {worst * 1000:.4f} mm over {len(rows)} frames and {len(labels)} bodies")
    report(max((r["t"] for r in rows), default=0) <= t_arr[-1], f"no frame past the record's end at {t_arr[-1]:.2f} s")
    roots = []
    for r in rows[:: max(1, len(rows) // 6)][:6]:
        pos, _ = recorded(t_arr, body_q, r["t"])
        uv = project(pos[0], r)[0]
        bl = np.array(r["screen"][:2]) * r["res"]
        bl[1] = r["res"][1] - bl[1]
        e = float(np.linalg.norm(uv - bl))
        roots.append(e)
        print(f"     t={r['t']:.2f}s root {np.round(pos[0], 3).tolist()} projects to ({uv[0]:.1f}, {uv[1]:.1f}) px, Blender says ({bl[0]:.1f}, {bl[1]:.1f}), diff {e:.3f} px")
    report(max(roots, default=9) < 0.2, f"projected root equals recorded position: worst {max(roots, default=-1):.3f} px at {rows[0]['res']}")

    # 2. Pixels.
    if not a.no_probe:
        probe = work / "probe"
        probe.mkdir(exist_ok=True)
        times = [shot["t"] - 0.5, shot["t"], shot["t"] + 0.5] if "t" in shot else np.linspace(shot["t0"] + 0.2, shot["t1"] - 0.2, 5).tolist()
        exe = a.blender or "blender"
        subprocess.check_call(["nice", "-n", "15", exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "inspection_scene.py"), "--", "--shot", a.shot, "--out", str(probe), "--mode", "probe", "--probe-times", ",".join(f"{t:.4f}" for t in times), "--device", a.device, "--res", "960x540", "--samples", "4"], stdout=subprocess.DEVNULL, cwd=str(ROOT))
        pr = json.loads((probe / "poses_probe_0000.json").read_text())
        verts = base_vertices()
        for r in pr:
            pos, q = recorded(t_arr, body_q, r["t"])
            world = np.array([qrot(q[0], v) for v in verts]) + pos[0]
            uv = project(world, r)
            box_p = np.array([uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()])
            alpha = np.array(Image.open(probe / f"probe_{r['frame']:02d}.png").convert("RGBA"))[:, :, 3] > 127
            ys, xs = np.where(alpha)
            if not len(xs):
                report(False, f"t={r['t']:.2f}s: silhouette is empty")
                continue
            box_r = np.array([xs.min(), ys.min(), xs.max() + 1, ys.max() + 1], float)
            # Parts of the box outside the frame cannot be seen, so they do not count.
            box_c = np.clip(box_p, [0, 0, 0, 0], [960, 540, 960, 540])
            e = float(np.abs(box_c - box_r).max())
            report(e <= 2.0, f"t={r['t']:.2f}s: rendered base silhouette box {box_r.astype(int).tolist()}, record gives {np.round(box_c, 1).tolist()}, worst edge {e:.2f} px")

    # 3. Solids.
    man = json.loads((work / "manifest.json").read_text())
    drawn = {s["name"]: s for s in man["solids"]}
    worst = 0.0
    wet_circles = []
    missing = 0
    for s in replay["solids"]:
        if s["material"] == "wet":
            wet_circles.append((s["pos"][0], s["pos"][1], s["size"][0]))
            continue
        if s["name"] not in drawn:
            missing += 1
            continue
        lo, hi = prim_box(s)
        worst = max(worst, float(np.abs(np.array(drawn[s["name"]]["min"]) - lo).max()), float(np.abs(np.array(drawn[s["name"]]["max"]) - hi).max()))
    report(missing == 0 and worst < 0.003, f"solids: {len(replay['solids']) - len(wet_circles)} in the record, {missing} missing, worst box error {worst * 1000:.2f} mm")
    if wet_circles:
        wet = np.load(work / "floor_wet.npy")
        px = wet.shape[1] / 22.0
        xs = -5.0 + (np.arange(wet.shape[1]) + 0.5) / px
        ys = -10.0 + (np.arange(wet.shape[0]) + 0.5) / px
        xx, yy = np.meshgrid(xs, ys)
        dist = np.min([np.hypot(xx - x, yy - y) - r for x, y, r in wet_circles], axis=0)
        inside = wet[dist < -0.05].mean() > 0.97 if (dist < -0.05).any() else False
        rim = float((wet[dist > 0.05] >= 0.9).mean())
        report(bool(inside) and rim < 1e-3, f"wet film matches the record's {len(wet_circles)} circles: inside {wet[dist < -0.05].mean():.3f}, standing water more than 5 cm outside {rim:.5f}")

    # 4. Visual-only scenery.
    bad_names = man["other_objects"]
    report(all(n == "cam" for n in bad_names), f"objects are solid_* or visual_*, others: {bad_names}")
    pts = body_q[:, :, :3].reshape(-1, 3)
    near = None
    for vb in man["visual_boxes"]:
        lo, hi = np.array(vb["min"]), np.array(vb["max"])
        dist = np.maximum(np.maximum(lo - pts, pts - hi), 0).max(axis=1).min()
        near = dist if near is None else min(near, dist)
        if dist < 0.05:
            report(False, f"visual {vb['kind']} is {dist:.3f} m from a recorded body")
    report(near is None or near >= 0.05, f"visual scenery off the path: nearest {0 if near is None else near:.2f} m over {len(man['visual_boxes'])} boxes")

    print("CHECK PASS" if not bad else f"CHECK FAIL ({len(bad)})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
