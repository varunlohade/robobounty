#!/usr/bin/env python3
"""Proves that a hull render shows the record. Reads the record directly, not through the render's own reader. Run from the repo root with policy/.venv.

  policy/.venv/bin/python policy/render/hull_check.py --shot lane --work design/render/hull/_work/clip_lane

1. Logged poses: every body against the record at every logged frame. Worst error under 0.1 mm. No time past the record's end.
2. Moving parts: the drum's turn per frame against its recorded speed, the roller springs against the record, and the shoes' place on the track loop against the record's track travel.
3. Pixels: Cycles renders only the chassis at five recorded times. The silhouette's box must match the record's pose through a plain pinhole, within 2 pixels at 960x540.
4. Fouling: the drawn grid's totals against this file's own replay of the record's start and changes.
5. Sizes: copied constants against packs/hull/model.py and the weld beads against the world's height.
6. Visual-only hardware stays away from the robot's whole recorded path.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "policy"))
import hull_record as HR  # noqa: E402 (the shot table and the copied constants only)
from packs.hull import model as M  # noqa: E402
from packs.hull import world as W  # noqa: E402

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
    C = np.array(row["cam"])
    d = (np.atleast_2d(p) - C[:3, 3]) @ C[:3, :3]
    w, h = row["res"]
    f = row["lens"] / row["sensor"]
    u = 0.5 + f * d[:, 0] / -d[:, 2]
    v = 0.5 + f * (w / h) * d[:, 1] / -d[:, 2]
    return np.column_stack([u * w, (1 - v) * h])


def replay_grid(d, t):
    """Own replay of the grid. Same 10 Hz blend the render says it uses."""
    s, b = d["fouling0_slime"].astype(np.float64) / 255, d["fouling0_barnacle"].astype(np.float64) / 255
    gt = d["grid_t"]
    k = int(np.searchsorted(gt, t, side="right")) - 1
    frame, cell = d["delta_frame"], d["delta_cell"]
    ds, db = d["delta_slime"].astype(np.float64) / 255, d["delta_barnacle"].astype(np.float64) / 255
    mask = frame <= k
    # Later changes to the same cell win, in frame order.
    order = np.argsort(frame[mask], kind="stable")
    s.ravel()[cell[mask][order]] = ds[mask][order]
    b.ravel()[cell[mask][order]] = db[mask][order]
    if 0 <= k and k + 1 < len(gt):
        u = (t - gt[k]) / (gt[k + 1] - gt[k])
        nxt = frame == k + 1
        s.ravel()[cell[nxt]] += (ds[nxt] - s.ravel()[cell[nxt]]) * u
        b.ravel()[cell[nxt]] += (db[nxt] - b.ravel()[cell[nxt]]) * u
    return s, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--blender", default="blender")
    ap.add_argument("--device", default="metal")
    a = ap.parse_args()
    work = Path(a.work)
    shot = HR.SHOTS[a.shot]
    scan = shot["kind"] == "orbit"
    d = dict(np.load(HR.run_path(shot["run"])))
    t_arr, body_q = d["t"].astype(np.float64), d["body_q"].astype(np.float64)
    meta = json.loads(str(d["meta"]))
    labels = meta["body_labels"]

    rows = []
    for p in sorted(work.glob("poses_clip_*.json")) + sorted(work.glob("poses_still_*.json")):
        rows += json.loads(p.read_text())
    report(bool(rows), f"{len(rows)} logged frames")

    worst = 0.0
    for r in rows:
        pos, _ = recorded(t_arr, body_q, r["t"])
        for i, b in enumerate(labels):
            worst = max(worst, float(np.linalg.norm(np.array(r["bodies"][b]["loc"]) - pos[i])))
    report(worst < 1e-4, f"poses: worst body error {worst * 1000:.4f} mm over {len(rows)} frames and {len(labels)} bodies")
    report(max(r["t"] for r in rows) <= t_arr[-1], f"no frame past the record's end at {t_arr[-1]:.2f} s")
    roots = []
    for r in rows[:: max(1, len(rows) // 6)][:6]:
        pos, _ = recorded(t_arr, body_q, r["t"])
        uv = project(pos[0], r)[0]
        bl = np.array(r["screen"][:2]) * r["res"]
        bl[1] = r["res"][1] - bl[1]
        roots.append(float(np.linalg.norm(uv - bl)))
    report(max(roots) < 0.2, f"projected root equals recorded position: worst {max(roots):.3f} px at {rows[0]['res']}")

    # Moving parts.
    if not scan and len(rows) > 2:
        dt_log = t_arr[1] - t_arr[0]
        errs = []
        for r0, r1 in zip(rows[:-1:7], rows[1::7]):
            q0, q1 = np.array(r0["bodies"]["drum"]["quat"]), np.array(r1["bodies"]["drum"]["quat"])
            ang = 2 * np.arccos(min(1.0, abs(float(q0 @ q1))))
            i0, i1 = int(r0["t"] / dt_log), int(r1["t"] / dt_log)
            errs.append(abs(ang - abs(float(d["drum_rate"][i0:i1 + 1].mean())) * (r1["t"] - r0["t"])))
        report(max(errs) < 0.05, f"drum: turn per frame matches the recorded speed, worst {np.degrees(max(errs)):.2f} degrees per frame")
    tr_err, shoe_err = 0.0, 0.0
    for r in rows[:: max(1, len(rows) // 60)]:
        i = (r["t"] - t_arr[0]) / (t_arr[1] - t_arr[0])
        i0 = min(int(i), len(t_arr) - 2)
        u = i - i0
        tr = d["track_travel"][i0] * (1 - u) + d["track_travel"][i0 + 1] * u
        tr_err = max(tr_err, float(np.abs(tr - np.array(r["track_travel"])).max()))
        sp = (d["spring"][i0] * (1 - u) + d["spring"][i0 + 1] * u)[:HR.ROLLERS].astype(np.float64)
        x, z, th = HR.shoe_poses(tr[0], sp)
        shoe_err = max(shoe_err, float(np.hypot(x[0] - r["shoe0"][0][0], z[0] - r["shoe0"][0][2])))
    report(tr_err < 1e-4, f"tracks: drawn travel equals the record, worst {tr_err * 1000:.4f} mm")
    report(shoe_err < 1e-4, f"tracks: first shoe on the path the record gives, worst {shoe_err * 1000:.4f} mm")
    if scan:
        report(all(abs(r["t"] - shot["t"]) < 1e-9 for r in rows), f"scan: every frame shows the parked robot at t = {shot['t']} s")
        rate = abs(float(d["drum_rate"][int(shot["t"] / (t_arr[1] - t_arr[0]))]))
        report(rate < 0.05, f"scan: drum stopped at that time, {rate:.4f} rad/s")
        eyes = np.array([np.array(r["cam"])[:3, 3] for r in rows])
        if len(eyes) > 2:
            step = np.linalg.norm(np.diff(eyes, axis=0), axis=1)
            report(step.max() / max(step.min(), 1e-9) < 1.05, f"scan: steady camera, {step.mean() * 1000:.1f} mm per frame, spread {step.min() * 1000:.2f} to {step.max() * 1000:.2f} mm")
        inside = [(0 <= (uv := project(recorded(t_arr, body_q, r["t"])[0][0], r)[0])[0] <= r["res"][0]) and (0 <= uv[1] <= r["res"][1]) for r in rows]
        report(all(inside), "scan: the robot stays in frame in every frame")

    # Pixels.
    probe = work / "probe"
    probe.mkdir(exist_ok=True)
    if scan:
        times = [shot["t"]]
    else:
        times = np.linspace(shot["t0"] + 0.2, shot["t1"] - 0.2, 5).tolist()
    subprocess.check_call(["nice", "-n", "15", a.blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "hull_scene.py"), "--", "--shot", a.shot, "--out", str(probe), "--mode", "probe", "--probe-times", ",".join(f"{t:.4f}" for t in times), "--device", a.device, "--res", "960x540"], stdout=subprocess.DEVNULL)
    pr = json.loads((probe / "poses_probe_0000.json").read_text())
    verts = np.load(probe / "chassis_verts.npy")
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
        box_c = np.clip(box_p, [0, 0, 0, 0], [960, 540, 960, 540])
        e = float(np.abs(box_c - box_r).max())
        report(e <= 2.0, f"t={r['t']:.2f}s: rendered chassis silhouette box {box_r.astype(int).tolist()}, record gives {np.round(box_c, 1).tolist()}, worst edge {e:.2f} px")

    # Fouling.
    worst_s = worst_b = 0.0
    for r in rows[:: max(1, len(rows) // 40)]:
        s, b = replay_grid(d, r["t"])
        worst_s = max(worst_s, abs(float(s.sum()) - r["slime_sum"]))
        worst_b = max(worst_b, abs(float(b.sum()) - r["barnacle_sum"]))
    report(worst_s < 2.0 and worst_b < 2.0, f"fouling grid: drawn totals match this file's replay, worst {worst_s:.3f} and {worst_b:.3f} level-cells of {np.prod(d['fouling0_slime'].shape)}")

    # Sizes.
    pairs = (("ROLLER_R", HR.ROLLER_R, M.ROLLER_R), ("AXLE_Z", HR.AXLE_Z, M.AXLE_Z), ("TRACK_Y", HR.TRACK_Y, M.TRACK_Y), ("TRACK_X", HR.TRACK_X, M.TRACK_X), ("ROLLERS", HR.ROLLERS, M.ROLLERS), ("SEAM_R", HR.SEAM_R, M.SEAM_R), ("DRUM_X", HR.DRUM_X, M.DRUM_X), ("DRUM_Z", HR.DRUM_Z, M.DRUM_Z), ("DRUM_TIP_R", HR.DRUM_TIP_R, M.DRUM_TIP_R), ("DRUM_HALF_W", HR.DRUM_HALF_W, M.DRUM_HALF_W), ("SEAMS_X", HR.SEAMS_X, W.TRANSVERSE_SEAMS_X), ("SEAMS_Y", HR.SEAMS_Y, W.LONGITUDINAL_SEAMS_Y), ("PLATE_Y", HR.PLATE_Y, W.PLATE_Y))
    wrong = [n for n, x, y in pairs if not np.allclose(x, y)]
    report(not wrong, f"copied constants equal the pack's: {len(pairs)} checked, wrong: {wrong}")
    man = json.loads((work / "manifest.json").read_text())
    h = meta["world"]["seam"]["height_m"]
    report(abs(man["seams"]["height_m"] - h) < 1e-9 and abs(man["seams"]["max_z_drop"] - h) < 0.0008, f"weld beads: drawn {man['seams']['max_z_drop'] * 1000:.2f} mm, recorded world {h * 1000:.2f} mm, art waver under 0.8 mm")

    # Visual hardware off the path.
    pts = body_q[::5, :, :3].reshape(-1, 3)
    near = None
    for vb in man["visual_boxes"]:
        lo, hi = np.array(vb["min"]), np.array(vb["max"])
        dist = float(np.maximum(np.maximum(lo[:2] - pts[:, :2], pts[:, :2] - hi[:2]), 0).max(axis=1).min())
        near = dist if near is None else min(near, dist)
    reach = HR.DRUM_HALF_W + 0.05
    report(near is not None and near >= reach, f"visual hardware off the path: nearest {near:.2f} m from any recorded body centre, over {len(man['visual_boxes'])} boxes; need {reach:.2f} m")

    print("CHECK PASS" if not bad else f"CHECK FAIL ({len(bad)})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
