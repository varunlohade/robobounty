"""Runs one trial headless: run_trial5.py <world.json> --seed S [--out DIR]. Writes the action log and qpos per control step.

A world file may be v3, v4 or v5. Old schemas upgrade on load. Results are simulated with hand-built physics.
"""
import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compile5 as C
import controller5 as controller_module
import judge5 as judge_module
import sim5 as S
import world5 as W

GENESIS = "0" * 64
CODE_FILES = ("compile5.py", "controller5.py", "engine5.py", "judge5.py", "parts5.py", "run_trial5.py", "scene5.py", "sim5.py", "world5.py")


def code_hashes():
    return {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in CODE_FILES}


def sim_label(hashes):
    joined = "".join(f"{name}:{hashes[name]}\n" for name in sorted(hashes))
    return "sim highrise5 " + hashlib.sha256(joined.encode()).hexdigest()[:12]


def mission(world, sim):
    sx, sz = W.start_pose(world)
    a = W.area_rect(world)
    return {"area": a, "start_x": sx, "start_z": sz, "anchor": (float(sim.d.site_xpos[0, 0]), W.ANCHOR_Y, world["tower"]["height_m"]),
            "clean_speed_ms": world["robot"]["clean_speed_ms"]}


def run(world, seed, out=None):
    world = W.validate(world)
    sim = S.Sim(world, seed)
    ctl = controller_module.Controller(mission(world, sim))
    judge = judge_module.Judge()
    prev = GENESIS
    rows = [{"i": -1, "a": [], "s": sim.start_sha, "h": S.digest(GENESIS, -1, [], sim.start_sha)}]
    prev = rows[0]["h"]
    frames = [sim.d.qpos.copy()]
    mocap_frames = [sim.d.mocap_pos.copy()] if sim.m.nmocap else None
    trace = []
    action = [0.0] * len(S.ACTION_FIELDS)
    status = "ok"
    t0 = time.time()
    i = 0
    while True:
        action = [float(x) for x in ctl.step(sim.obs())]
        if not sim.step(action):
            status = "invalid_action"
            break
        judge.update(sim, action)
        sha = sim.state_sha()
        h = S.digest(prev, i, action, sha)
        rows.append({"i": i, "a": action, "s": sha, "h": h})
        prev = h
        frames.append(sim.d.qpos.copy())
        if mocap_frames is not None:
            mocap_frames.append(sim.d.mocap_pos.copy())
        trace.append([ctl.phase, round(ctl.estimate, 3), round(sim.dp, 1), round(sim.body_xz()[0], 3), round(sim.body_xz()[1], 3),
                      round(sim.tension_tick, 1), round(sim.slip_rate, 3), round(sim.volts, 2), round(sim.coverage(), 3) if i % 20 == 0 else None])
        i += 1
        if sim.diverged:
            status = "sim_diverged"
            break
        if judge.should_stop(sim, action):
            break
    result = judge.finish(sim, action)
    if status != "ok":
        result["passed"] = False
        result["failure"] = status
        result["outcome"] = "sim_diverged" if status == "sim_diverged" else "fail"
        result["diverged_reason"] = sim.diverged_reason
    hashes = code_hashes()
    result.update({
        "label": sim_label(hashes), "physics_sha256": C.physics_hash(world),
        "status": status, "seed": seed, "world_sha256": W.world_hash(world), "model_sha256": sim.model_sha,
        "start_state_sha256": sim.start_sha, "final_state_sha256": sim.state_sha(), "action_chain_head": prev,
        "steps": i, "wall_s": round(time.time() - t0, 3), "versions": S.versions(), "code_sha256": hashes,
    })
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "world.json").write_text(json.dumps(world, indent=1) + "\n")
        with gzip.GzipFile(out / "actions.jsonl.gz", "wb", mtime=0) as f:
            f.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode())
        with gzip.GzipFile(out / "qpos.json.gz", "wb", mtime=0) as f:
            recording = {"hz": S.CONTROL_HZ, "nq": sim.m.nq, "frames": np.round(np.array(frames), 5).tolist()}
            if mocap_frames is not None:
                recording["mocap_frames"] = np.round(np.array(mocap_frames), 5).tolist()
            f.write(json.dumps(recording, separators=(",", ":")).encode())
        with gzip.GzipFile(out / "trace.json.gz", "wb", mtime=0) as f:
            f.write(json.dumps({"columns": ["phase", "est_fraction", "dp", "x", "z", "tension", "slip_rate", "volts", "coverage"],
                                "rows": trace}, separators=(",", ":")).encode())
        np.savez_compressed(out / "dirt.npz", dirt=sim.dirt, mask=sim.dirt_mask)
        (out / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    r = run(W.load(args.world), args.seed, args.out)
    print(json.dumps({k: v for k, v in r.items() if k != "code_sha256"}, indent=1))
