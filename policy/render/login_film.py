#!/usr/bin/env python3
"""The login page film: real recorded runs, rendered in Cycles, one tile each. Simulated, and the words on each tile come from that run's result.

  login_film.py plan                       Reads the recorded runs and writes design/render/login_film/plan.json and _src/.
  login_film.py render --tiles a,b --res 640x540 --samples 48 --device optix --jobs 3 [--preview]
  login_film.py compose                    is in login_film_compose.py.

Nothing here simulates. A clip is a time window of a record, and the camera reads the recorded path and writes nothing back.
"""
import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "design" / "render" / "login_film"
SRC = OUT / "_src"
DEMO = ROOT / "policy" / "runs" / "demo"
FIX_TRIALS = Path(os.environ.get("LOGIN_FILM_FIXES", "/tmp/lg/trials"))
FPS = 30
CLIP_S = 5.0  # Screen seconds of motion in one tile.
SKY = "kloofendal_overcast_puresky"

INSPECTION = ["w015", "w019", "w021", "w032", "w040", "w043", "w016", "w046", "w029"]
WINDOW = []
# Real before and after, each replayed through export5 with a match, from the record of where the fix came from. Three at most.
FIXES = {
    "fix041": {"name": "Strong climb, smallest margin", "before": "wall-fix041-before", "after": "wall-fix041-after", "who": "Bounty fix", "minus": "LOW_PRESSURE_PA = 1500.0", "plus": "LOW_PRESSURE_PA = 1400.0"},
}


def pretty(s):
    t = s.replace("_", " ")
    return t[0].upper() + t[1:]


def gunzip_dir(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.suffix == ".gz":
            (dst / f.stem).write_bytes(gzip.decompress(f.read_bytes()))
        elif f.is_file():
            shutil.copy(f, dst / f.name)


def inspection_tile(run_id, scenarios, rng):
    """A demo replay holds the record at 25 Hz. It becomes the same .npz and .replay files that inspection_record.Record reads."""
    d = DEMO / "inspection" / run_id
    replay = json.loads(gzip.decompress((d / "replay.json.gz").read_bytes()))
    world = scenarios[int(run_id[1:])]
    res = json.loads((d / "job_result.json").read_text())
    assert replay["result"]["verdict"] == res["verdict"]
    t = np.array([f["t"] for f in replay["frames"]], dtype=np.float64)
    body_q = np.array([f["q"] for f in replay["frames"]], dtype=np.float64).reshape(len(t), len(replay["body_labels"]), 7)
    assert not [o for o in world["world"]["objects"] if o["kind"] == "generated"], run_id
    name = f"insp-{run_id}"
    SRC.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(SRC / f"{name}.npz", t=t, body_q=body_q, meta=json.dumps({"body_labels": replay["body_labels"], "world": world["world"]}))
    (SRC / f"{name}.replay.json.gz").write_bytes((d / "replay.json.gz").read_bytes())

    verdict = res["verdict"]
    m = re.search(r"at ([\d.]+) s", res["reason"])
    if verdict == "passed":
        at = [e for e in res["events"] if e["name"].startswith("waypoint")][-1]["t"]
        words = f"Passed, {res['numbers']['waypoints_reached']} of {res['numbers']['waypoints']} waypoints"
        t1 = min(at + 0.6, float(t[-1]))
    elif verdict in ("fell", "stuck"):
        at = float(m.group(1))
        words = f"{verdict.capitalize()} at {at:.1f} s"
        t1 = min(at + 1.3, float(t[-1]))
    else:
        raise SystemExit(f"{run_id}: not planned for verdict {verdict}")
    t0 = max(float(t[0]) + 0.02, t1 - CLIP_S)
    root = body_q[:, 0, :3]
    a, b = np.interp(t0, t, root[:, 0]), np.interp(t1, t, root[:, 0])
    c, e = np.interp(t0, t, root[:, 1]), np.interp(t1, t, root[:, 1])
    head = np.array([b - a, e - c])
    head = head / max(np.linalg.norm(head), 1e-6)
    if np.linalg.norm([b - a, e - c]) < 0.4:
        head = np.array([1.0, 0.0])
    # The camera stays inside the walkway: its side is the one toward the route's centre line, away from the rail the robot has drifted to.
    wp = [(0.0, 0.0)] + [(p["x"], p["y"]) for p in world["world"]["route"]["waypoints"]]
    here = np.array([b, e])
    near = min((np.array(u) + np.clip(np.dot(here - u, np.subtract(v, u)) / max(np.dot(np.subtract(v, u), np.subtract(v, u)), 1e-6), 0, 1) * np.subtract(v, u) for u, v in zip(wp, wp[1:])), key=lambda c: np.linalg.norm(c - here))
    side = np.array([-head[1], head[0]])
    toward = np.dot(near - here, side)
    side = side * (np.sign(toward) if abs(toward) > 0.08 else rng.choice([-1, 1]))
    front = rng.choice([1, 1, -1])  # Mostly from ahead, walking at the lens.
    dist, lateral, height = rng.uniform(2.3, 2.9), rng.uniform(0.6, 1.0), rng.uniform(0.62, 1.05)
    # The first leg's walkway ends at a wall at about x = 6.4 m. A camera ahead of this run would pass through it.
    dist = {"w019": 1.85}.get(run_id, dist)
    off = head * front * dist + side * lateral
    keys = []
    for k in np.arange(t0 - 2, t1 + 2, 0.45):  # An operator's hand: a couple of centimetres, slow. Art only.
        keys.append([float(k), float(off[0] + rng.normal(0, 0.022)), float(off[1] + rng.normal(0, 0.022)), float(height + rng.normal(0, 0.012))])
    shot = {"run": str(SRC / f"{name}.npz"), "t0": t0, "t1": t1, "follow": keys, "follow_sigma": 0.3, "at": [float(-off[0] * 0.05), float(-off[1] * 0.05), float(rng.uniform(-0.12, -0.04))],
            "lens": float(rng.uniform(33, 41)), "fstop": float(rng.uniform(2.4, 3.2)), "sigma": 0.55}
    label = pretty(world["name"])
    return {"id": name, "robot": "inspection", "run": run_id, "name": label, "speed": 1, "kind": "fail" if verdict != "passed" else "pass", "words": words, "verdict": verdict,
            "reason": res["reason"], "segments": [{"key": name, "scene": "inspection", "shot": shot, "seconds": t1 - t0, "fps": FPS, "t0": t0, "t1": t1, "verdict_at": (at - t0)}]}


def window_camera(rng, slip=False):
    """The wide look of the other window clips: off the wall, the street below, the robot right of centre."""
    return {"fixed": False, "pos": [[1.55, -1.22, 0.5], [1.45, -1.27, 0.53]], "target": [[-0.75, -0.26, 0.0], [-0.85, -0.29, 0.02]], "lens": [30.0, 30.0], "fstop": 1.7, "roll": 0.0, "seconds": 8.0}
    # Off the wall, level with the robot, a long lens on it. The side changes tile to tile.
    sx = rng.choice([-1, 1])
    px, py, pz = rng.uniform(1.2, 1.5), rng.uniform(-1.05, -0.9), rng.uniform(-0.38, -0.12)
    if slip:
        px, py, pz = rng.uniform(1.25, 1.4), rng.uniform(-0.98, -0.88), rng.uniform(-0.42, -0.24)
    tx = rng.uniform(0.12, 0.24)
    dr = rng.uniform(-0.1, 0.1)
    return {"pos": [[float(sx * px), float(py), float(pz)], [float(sx * (px + dr)), float(py + 0.04), float(pz + 0.03)]],
            "target": [[float(-sx * tx), -0.17, -0.02], [float(-sx * tx), -0.17, -0.02]],
            "lens": [float(rng.uniform(44, 50))] * 2, "fstop": float(rng.uniform(1.8, 2.4)), "sigma": 1.4 if not slip else 0.4, "lag": 0.06 if slip else 0.0}


def window_trial(key, src):
    dst = SRC / key
    if src.exists():
        gunzip_dir(src, dst)
    w = json.loads((dst / "world.json").read_text())
    if "panes" in w:  # A v5 world keeps these under groups. The render reads the flat names.
        w.update(mullion_depth_m=w["panes"]["joint_depth_m"], mullion_spacing_m=w["panes"]["width_m"], mullion_offset_m=w["panes"]["offset_x_m"], joint_gap_m=w["panes"]["joint_gap_m"],
                 edge_margin_m=w["area"]["margin_m"], dirt_level=w["area"]["dirt_level"], steady_wind_ms=w["wind"]["steady_ms"], wind_dir_deg=w["wind"]["dir_deg"])
        (dst / "world.json").write_text(json.dumps(w))
    m = json.loads((dst / "manifest.json").read_text())
    if not m.get("replay_match"):
        raise SystemExit(f"{key}: the export did not match its replay")
    return dst


def stop_time(trial):
    """When the recorded robot last moved, for a run that ended standing still."""
    q = json.loads((trial / "qpos.json").read_text())
    p = np.array(q["frames"])[:, :3]
    moved = np.linalg.norm(p - p[-1], axis=1) > 0.01
    return float(np.nonzero(moved)[0][-1]) / q["hz"]


def window_tile(run_id, scenarios, rng):
    d = DEMO / "window" / run_id
    res = json.loads((d / "job_result.json").read_text())
    key = f"win-{run_id}"
    trial = window_trial(key, d / "export")
    name = pretty(scenarios[int(run_id[1:])]["name"])
    v, n = res["verdict"], res["numbers"]
    end = n["time_s"]
    if v == "slip_distance":
        m = re.search(r"slid ([\d.]+) m in one slide at ([\d.]+) s\. The limit is ([\d.]+) m", res["reason"])
        at = float(m.group(2))
        speed = 2
        t1 = min(at + 1.8, end - 0.1)
        words = f"Slid {m.group(1)} m, limit {m.group(3)} m"
    elif v == "coverage":
        speed, t1, at = 4, end - 0.1, end - 0.1
        words = f"Cleaned {n['coverage'] * 100:.0f}%, needs 90%"
    elif v == "passed":
        speed, t1, at = 4, end - 0.1, end - 0.1
        words = f"Passed, {n['coverage'] * 100:.0f}% cleaned"
    else:
        raise SystemExit(f"{run_id}: not planned for verdict {v}")
    t0 = t1 - CLIP_S * speed
    slip = v == "slip_distance"
    shot = {"t": t0, **window_camera(rng, slip)}
    return {"id": key, "robot": "window", "run": run_id, "name": name, "speed": speed, "kind": "pass" if v == "passed" else "fail", "words": words, "verdict": v, "reason": res["reason"],
            "segments": [{"key": key, "scene": "window", "trial": key, "shot": shot, "seconds": CLIP_S * speed, "fps": FPS / speed, "t0": t0, "t1": t1, "verdict_at": (at - t0) / speed}]}


def fix_tile(key, spec, rng):
    """Before: the last stretch up to the recorded failure. Then the recorded diff. After: the last stretch of the passing run."""
    b = spec["before"]
    before = window_trial(f"{key}-before", DEMO / "window" / b[5:] / "export" if b.startswith("demo:") else FIX_TRIALS / b)
    after = window_trial(f"{key}-after", FIX_TRIALS / spec["after"])
    rb, ra = json.loads((before / "result.json").read_text()), json.loads((after / "result.json").read_text())
    if rb["passed"] or not ra["passed"]:
        raise SystemExit(f"{key}: not a real before and after")
    speed = 4
    part = 2.0
    failure = rb["failure"]
    stop = stop_time(before) if failure == "stalled" else rb["time_s"]
    t1b = min(stop + 1.0, rb["time_s"] - 0.1)
    t0b = t1b - part * speed
    t1a = ra["time_s"] - 0.1
    t0a = t1a - part * speed
    cam = window_camera(rng)
    fail_words = {"stalled": f"Stalled, {rb['coverage'] * 100:.0f}% cleaned", "false_done": f"False finish, {rb['coverage'] * 100:.0f}% cleaned"}[failure]
    return {"id": key, "robot": "window", "run": key, "name": spec["name"], "speed": speed, "kind": "fix", "words": fail_words, "after_words": f"Passed, {ra['coverage'] * 100:.0f}% cleaned",
            "who": spec["who"], "minus": spec["minus"], "plus": spec["plus"], "verdict": failure,
            "segments": [{"key": f"{key}-before", "scene": "window", "trial": f"{key}-before", "shot": {"t": t0b, **cam}, "seconds": part * speed, "fps": FPS / speed, "t0": t0b, "t1": t1b, "verdict_at": (min(stop, t1b) - t0b) / speed},
                         {"key": f"{key}-after", "scene": "window", "trial": f"{key}-after", "shot": {"t": t0a, **cam}, "seconds": part * speed, "fps": FPS / speed, "t0": t0a, "t1": t1a, "verdict_at": part}]}


def reused():
    """Cycles clips of real runs already on disk, at 24 fps. crop is x0, y0, x1, y1 of the 1920x1080 frame, clear of any burnt-in line."""
    runs = ROOT / "design" / "render" / "_runs"
    low = json.loads(gzip.decompress((ROOT / "policy" / "packs" / "inspection" / "out" / "low_pipe.replay.json.gz").read_bytes()))["result"]
    pl = json.loads(gzip.decompress((ROOT / "policy" / "packs" / "inspection" / "out" / "plant.replay.json.gz").read_bytes()))["result"]
    slip, good = json.loads((runs / "t0010" / "result.json").read_text()), json.loads((runs / "t0014" / "result.json").read_text())
    nominal = json.loads((ROOT / "public" / "trials" / "nominal-seed1" / "result.json").read_text())
    assert low["verdict"] == "fell" and pl["verdict"] == "passed" and slip["failure"] == "slip_distance" and good["passed"] and nominal["passed"]
    def seg(key, folder, first, count, crop, verdict_at):
        return [{"key": key, "reuse": f"design/render/{folder}/png", "first": first, "seconds": count / 24, "fps": 24, "crop": crop, "t0": 0, "t1": 0, "verdict_at": verdict_at}]
    return [
        {"id": "re-low_pipe", "robot": "inspection", "run": "low_pipe", "name": "Low pipe", "speed": 1, "kind": "fail", "verdict": "fell", "words": "Fell at 5.2 s", "reason": low["reason"], "segments": seg("re-low_pipe", "inspection/_work/clip_fall", 0, 120, [300, 0, 1673, 1030], 3.0)},
        {"id": "re-plant", "robot": "inspection", "run": "plant", "name": "Plant route", "speed": 1, "kind": "pass", "verdict": "passed", "words": f"Passed, {pl['numbers']['waypoints_reached'] if 'numbers' in pl else 3} of 3 waypoints", "reason": pl["reason"], "segments": seg("re-plant", "inspection/_work/clip_plant_route", 382, 120, [230, 0, 1603, 1030], 4.0)},
        {"id": "re-t0010", "robot": "window", "run": "t0010", "name": f"Gusts to {json.loads((runs / 't0010' / 'world.json').read_text())['gust_speed_ms']:.0f} m/s", "speed": 1, "kind": "fail", "verdict": "slip_distance", "words": f"Slid {slip['slip_m']:.2f} m", "reason": "", "segments": seg("re-t0010", "_work/clip_slip", 96, 120, [480, 0, 1920, 1080], 2.6)},
        {"id": "re-t0014", "robot": "window", "run": "t0014", "name": f"Gusts to {json.loads((runs / 't0014' / 'world.json').read_text())['gust_speed_ms']:.0f} m/s", "speed": 1, "kind": "pass", "verdict": "passed", "words": f"Passed, {good['coverage'] * 100:.0f}% cleaned", "reason": "", "segments": seg("re-t0014", "_work/clip_pass", 40, 120, [480, 0, 1920, 1080], 4.6)},
        {"id": "re-nominal", "robot": "window", "run": "nominal-seed1", "name": "Nominal wind", "speed": 1, "kind": "pass", "verdict": "passed", "words": f"Passed, {nominal['coverage'] * 100:.0f}% cleaned", "reason": "", "segments": seg("re-nominal", "_work/clip", 40, 120, [480, 0, 1920, 1080], 4.6)},
    ]


def plan():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261106)
    si = json.loads(gzip.decompress((DEMO / "inspection" / "scenarios.json.gz").read_bytes()))["worlds"]
    sw = json.loads(gzip.decompress((DEMO / "window" / "scenarios.json.gz").read_bytes()))["worlds"]
    tiles = [inspection_tile(r, si, rng) for r in INSPECTION] + [window_tile(r, sw, rng) for r in WINDOW] + [fix_tile(k, v, rng) for k, v in FIXES.items()] + reused()
    (OUT / "plan.json").write_text(json.dumps({"fps": FPS, "note": "Simulated. Every tile is a window of a recorded run; words come from its result.", "tiles": tiles}, indent=1))
    frames = sum(round(s["seconds"] * s["fps"]) for t in tiles for s in t["segments"])
    for t in tiles:
        print(t["id"], t["name"], "|", t["words"], "|", [(round(s["t0"], 1), round(s["t1"], 1)) for s in t["segments"]])
    print(len(tiles), "tiles,", frames, "frames")


def blender(a):
    return a.blender or os.environ.get("BLENDER") or shutil.which("blender")


def render_segment(seg, a, res, samples, preview):
    work = OUT / "_work" / ("preview" if preview else "final") / seg["key"]
    (work / "jpg").mkdir(parents=True, exist_ok=True)
    fps = seg["fps"] if not preview else 3 / seg["seconds"]
    total = int(round(seg["seconds"] * fps))
    done = sum(1 for i in range(total) if (work / "jpg" / f"{i:04d}.jpg").exists())
    start = 0
    while start < total and (work / "jpg" / f"{start:04d}.jpg").exists():
        start += 1
    if start < total:
        t = time.time()
        if seg["scene"] == "inspection":
            cmd = ["nice", "-n", "15", blender(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "login_film_scene.py"), "--", "--shot", "plant", "--out", str(work), "--mode", "clip", "--res", res,
                   "--samples", str(samples), "--threshold", str(a.threshold), "--device", a.device, "--fps", str(fps), "--override", json.dumps(seg["shot"]), "--start-frame", str(start), "--end-frame", str(total)]
            if preview:
                cmd.append("--no-blur")
            env = {**os.environ, "LOGIN_FILM_SCENE": "inspection"}
        else:
            sky = ROOT / "design" / "render" / "_cache" / "hdri" / "overcast_soil_puresky.exr"
            cmd = ["nice", "-n", "15", blender(a), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(HERE / "login_film_scene.py"), "--", "--trial", str(SRC / seg["trial"]), "--out", str(work), "--mode", "clip", "--shot", "login",
                   "--res", res, "--samples", str(samples), "--sky", str(sky), "--fps", str(fps), "--seconds", str(seg["seconds"]), "--t", str(seg["t0"]), "--start-frame", str(start), "--end-frame", str(total)]
            env = {**os.environ, "LOGIN_FILM_SCENE": "window", "LOGIN_FILM_DEVICE": a.device.upper(), "LOGIN_FILM_SHOT": json.dumps(seg["shot"])}
        with open(work / f"blender_{start:04d}.log", "w") as f:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT), env=env)
            seen = start
            for line in p.stdout:
                f.write(line)
                if line.startswith("frame "):
                    seen += 1
                    finish_ready(work, total, seg["scene"] == "window")
                if "Traceback" in line or "Error" in line:
                    print(seg["key"], line.rstrip(), flush=True)
            if p.wait():
                print(seg["key"], "BLENDER FAILED, see", f.name, flush=True)
                return 0, time.time() - t
        finish_ready(work, total, seg["scene"] == "window")
        dt = time.time() - t
        print(f"{seg['key']}: {total - start} frames in {dt:.0f} s, {dt / max(total - start, 1):.2f} s per frame", flush=True)
        return total - start, dt
    print(seg["key"], "already done", done, flush=True)
    return 0, 0


def finish_ready(work, total, wide=False):
    """Grades each finished frame the same way as the clips it sits beside: post.py for the wide window look, post_v2.py for the plant."""
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    import post
    import post_v2
    for e in sorted(work.glob("frame_*.exr")):
        i = int(e.stem.split("_")[1])
        if wide:
            try:
                png = work / "jpg" / f"{i:04d}.png"
                post.process(str(e), str(png), seed=i + 1)
                y8 = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
                y8 = (y8 / 257).astype(np.uint8) if y8.dtype == np.uint16 else y8
                cv2.imwrite(str(work / "jpg" / f"{i:04d}.jpg"), y8, [cv2.IMWRITE_JPEG_QUALITY, 96])
                png.unlink()
                e.unlink()
            except Exception:
                pass  # Still being written.
            continue
        img = cv2.imread(str(e), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue  # Still being written.
        y = post_v2.grade(img[:, :, :3][:, :, ::-1].astype(np.float32), i + 1)
        cv2.imwrite(str(work / "jpg" / f"{i:04d}.jpg"), (y[:, :, ::-1] * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 96])
        e.unlink()


def render(a):
    tiles = json.loads((OUT / "plan.json").read_text())["tiles"]
    wanted = a.tiles.split(",") if a.tiles else None
    segs = [s for t in tiles if (not wanted or t["id"] in wanted) for s in t["segments"] if "reuse" not in s]
    t0 = time.time()
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda s: render_segment(s, a, a.res, a.samples, a.preview), segs))
    n = sum(r[0] for r in res)
    wall = time.time() - t0
    print(f"ALL DONE {n} frames, wall {wall:.0f} s, {wall / max(n, 1):.2f} s per frame of throughput", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "render"])
    ap.add_argument("--tiles", default=None)
    ap.add_argument("--res", default="576x540")
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--threshold", type=float, default=0.03)
    ap.add_argument("--device", default="metal", choices=["optix", "cuda", "metal", "auto"])
    ap.add_argument("--blender", default=None)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    if a.mode == "plan":
        plan()
    else:
        sys.path.insert(0, str(HERE))
        render(a)


if __name__ == "__main__":
    main()
