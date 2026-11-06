"""Exports one recorded sim5 run for the browser: export5.py <run dir> <id> "<label>" --out DIR [--world FILE].

The stored actions replay through sim5 first, and a replay that differs from the record refuses the export.
--world names the current world, whose picture may be newer than the run's. Its physics hash must match the run. The view model and world.json come from it.
A run of this code carries the label "sim highrise5 <sha12>". Results are simulated with hand-built physics.
"""
import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compile5 as C
import judge5 as judge_module
import run_trial5 as R
import sim5 as S
import world5 as W

DIRT_EVERY_STEPS = S.CONTROL_HZ
DIRT_SCALE = 200
KEYS = ("failure", "passed", "coverage", "slip_m", "peak_tether_n", "time_s")


def read_log(path):
    with gzip.open(path, "rt") as f:
        rows = [json.loads(line) for line in f]
    prev = R.GENESIS
    for n, row in enumerate(rows):
        if row["i"] != n - 1 or S.digest(prev, row["i"], row["a"], row["s"]) != row["h"]:
            sys.exit(f"the action log breaks at line {n}")
        prev = row["h"]
    return rows, prev


# These build a world and may gain new kinds of object. The physics hash above and the replay of every state below judge them, as board_fix._is_stale does.
WORLD_BUILD_FILES = {"compile5.py", "engine5.py", "world5.py", "parts5.py", "geoms5.py", "scene5.py"}


def read_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("id")
    ap.add_argument("label")
    ap.add_argument("--out", required=True)
    ap.add_argument("--world")
    a = ap.parse_args()
    run, out = Path(a.run_dir), Path(a.out)
    stored = json.loads((run / "result.json").read_text())
    world = W.load(run / "world.json")
    current = W.load(a.world) if a.world else world
    if C.physics_hash(current) != stored["physics_sha256"]:
        sys.exit("the current world's physics differ from the recorded run")
    now = R.code_hashes()
    if any(now.get(name) != stored["code_sha256"].get(name) for name in set(now) | set(stored["code_sha256"]) if name not in WORLD_BUILD_FILES):
        sys.exit("highrise5 code differs from the recorded run: record the trial again")

    rows, head = read_log(run / "actions.jsonl.gz")
    if head != stored["action_chain_head"]:
        sys.exit("the action log is not this run's")
    sim = S.Sim(world, stored["seed"])
    if sim.model_sha != stored["model_sha256"] or sim.start_sha != stored["start_state_sha256"]:
        sys.exit("the model differs from the recorded run")
    judge = judge_module.Judge()
    wind, dirt = [], []
    action = [0.0] * len(S.ACTION_FIELDS)
    for row in rows[1:]:
        action = row["a"]
        if not sim.step(action):
            sys.exit(f"the replay refused the action at step {row['i']}")
        judge.update(sim, action)
        if sim.state_sha() != row["s"]:
            sys.exit(f"the replay differs from the record at step {row['i']}")
        wind.append(round(sim.wind_now[0], 2))
        if row["i"] % DIRT_EVERY_STEPS == 0:
            dirt.append(np.clip(np.where(sim.dirt_mask, sim.dirt, 0.0) * DIRT_SCALE, 0, 255).astype(np.uint8))
    result = judge.finish(sim, action)
    if sim.diverged:
        result["failure"], result["passed"] = "sim_diverged", False
    if any(result[k] != stored[k] for k in KEYS) and stored["status"] == "ok":
        sys.exit("the replay's result differs from the record")

    qpos = read_gz(run / "qpos.json.gz")
    out.mkdir(parents=True, exist_ok=True)
    _, view_xml, _ = C.compile(current)
    if mujoco.MjModel.from_xml_string(view_xml).nq != qpos["nq"]:
        sys.exit("the view model's nq differs from the record")
    (out / "model.xml").write_text(view_xml)
    (out / "qpos.json").write_text(json.dumps(qpos, separators=(",", ":")))
    (out / "trace.json").write_text(json.dumps(read_gz(run / "trace.json.gz"), separators=(",", ":")))
    (out / "wind.json").write_text(json.dumps(wind, separators=(",", ":")))
    (out / "dirt.bin").write_bytes(np.stack(dirt).tobytes())
    shutil.copyfile(HERE / "controller5.py", out / "controller.py.txt")
    (out / "world.json").write_text(json.dumps(current, indent=1) + "\n")
    shutil.copyfile(run / "result.json", out / "result.json")
    (out / "manifest.json").write_text(json.dumps({
        "id": a.id, "label": a.label, "sim_label": stored["label"], "area": W.area_rect(world), "hz": qpos["hz"], "nq": qpos["nq"], "frames": len(qpos["frames"]),
        "python_mujoco": stored["versions"]["mujoco"], "friction": W.friction(world), "sim_sha256": stored["code_sha256"]["sim5.py"],
        "dirt": {"nx": sim.nx, "nz": sim.nz, "every_steps": DIRT_EVERY_STEPS, "scale": DIRT_SCALE, "clean_below": S.CLEAN_THRESHOLD, "count": len(dirt)},
        "replay_match": True,
    }, indent=1) + "\n")
    print("exported", out, len(qpos["frames"]), "frames, replay MATCH", stored["label"])


if __name__ == "__main__":
    main()
