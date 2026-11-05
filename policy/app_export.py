"""Exports recorded high-rise runs for the browser app. Run with policy/.venv/bin/python at low priority.

app_export.py trial <run dir> <id> "<label>"     one replay: public/trials/<id>/
app_export.py run-worlds <scenarios dir> <out>   runs every world in scenarios.json with run_trial
app_export.py worlds <scenarios dir> <runs dir> [--trials a=id ...]  the worlds tab: public/trials/worlds.json

Reads policy/highrise and the given folders. Writes only under public/trials/ and the given <out>.
Refuses a run whose model or code no longer matches what recorded it, or whose replay diverges.
"""
import argparse
import gzip
import hashlib
import json
import shutil
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "policy" / "highrise"))
import replay as replay_module
import run_trial
import sim as S
import world as W

PUBLIC = ROOT / "public" / "trials"
REFERENCE_FRAMES = 21
DIRT_EVERY_STEPS = S.CONTROL_HZ  # one dirt grid per simulated second
DIRT_SCALE = 200  # stored byte = dirt level * scale
THUMB_NX, THUMB_NZ = 16, 20


def read_gz_json(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def reference_poses(model, frames):
    """Body poses from Python mj_forward, for the browser check to compare against."""
    data = mujoco.MjData(model)
    bid = lambda n: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)
    robot, roller = bid("robot"), bid("roller_lf")
    out = []
    for i in np.linspace(0, len(frames) - 1, REFERENCE_FRAMES).astype(int):
        data.qpos[:] = frames[i]
        mujoco.mj_forward(model, data)
        out.append({"frame": int(i), "robot": data.xpos[robot].tolist(), "roller": data.xpos[roller].tolist()})
    return out


def cmd_trial(a):
    run = Path(a.run_dir)
    result = json.loads((run / "result.json").read_text())
    world = W.load(run / "world.json")
    sim = S.Sim(world, result["seed"])
    if sim.model_sha != result["model_sha256"]:
        sys.exit("model hash differs from the recorded run: the sim changed, record the trial again")
    controller = (ROOT / "policy" / "highrise" / "controller.py").read_bytes()
    if hashlib.sha256(controller).hexdigest() != result["code_sha256"]["controller.py"]:
        sys.exit("controller.py differs from the recorded run: record the trial again")
    qpos = read_gz_json(run / "qpos.json.gz")
    trace = read_gz_json(run / "trace.json.gz")
    if qpos["nq"] != sim.m.nq:
        sys.exit("recorded nq differs from the model")

    # The dirt grid and wind are not in the log. A replay of the stored actions gives the same states, and the report proves it.
    dirt, wind, grid = [], [], {}

    def keep(s, i):
        wind.append(round(s.wind_now[0], 2))
        if i % DIRT_EVERY_STEPS == 0:
            grid.update(nx=s.nx, nz=s.nz)
            masked = np.where(s.dirt_mask, s.dirt, 0.0)
            dirt.append(np.clip(masked * DIRT_SCALE, 0, 255).astype(np.uint8))

    report = replay_module.replay(run, keep=keep)
    if not report["match"]:
        sys.exit(f"replay does not match the recorded run: {json.dumps(report)[:400]}")

    out = PUBLIC / a.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.xml").write_text(W.build_xml(world))
    (out / "qpos.json").write_text(json.dumps(qpos, separators=(",", ":")))
    (out / "trace.json").write_text(json.dumps(trace, separators=(",", ":")))
    (out / "wind.json").write_text(json.dumps(wind, separators=(",", ":")))
    (out / "dirt.bin").write_bytes(np.stack(dirt).tobytes())
    (out / "reference.json").write_text(json.dumps(reference_poses(sim.m, np.array(qpos["frames"]))))
    (out / "controller.py.txt").write_bytes(controller)
    shutil.copyfile(run / "world.json", out / "world.json")
    shutil.copyfile(run / "result.json", out / "result.json")
    (out / "manifest.json").write_text(json.dumps({
        "id": a.id, "label": a.label, "area": W.area(world), "hz": qpos["hz"], "nq": qpos["nq"],
        "frames": len(qpos["frames"]), "python_mujoco": result["versions"]["mujoco"], "friction": W.friction(world),
        "dirt": {"nx": grid["nx"], "nz": grid["nz"], "every_steps": DIRT_EVERY_STEPS, "scale": DIRT_SCALE,
                 "clean_below": S.CLEAN_THRESHOLD, "count": len(dirt)},
        "replay_match": True,
    }, indent=1) + "\n")

    index_path = PUBLIC / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    index = [t for t in index if t["id"] != a.id] + [{"id": a.id, "label": a.label}]
    index_path.write_text(json.dumps(index, indent=1) + "\n")
    print("exported", out, len(qpos["frames"]), "frames, replay MATCH")


def cmd_run_worlds(a):
    plan = json.loads((Path(a.scenarios) / "scenarios.json").read_text())
    for n, w in enumerate(plan["worlds"]):
        name = Path(w["file"]).stem
        out = Path(a.out) / name
        if (out / "result.json").exists():
            continue
        r = run_trial.run(W.load(Path(a.scenarios) / w["file"]), 1000 + n, out)
        print(name, r["passed"], r["failure"], r["time_s"], flush=True)


def thumb(run):
    with np.load(run / "dirt.npz") as z:
        dirt, mask = z["dirt"], z["mask"]
    nz, nx = dirt.shape
    rows = []
    for iz in range(THUMB_NZ):
        row = ""
        for ix in range(THUMB_NX):
            cell = (iz * nz // THUMB_NZ, ix * nx // THUMB_NX)
            row += "0" if not mask[cell] or dirt[cell] <= S.CLEAN_THRESHOLD else "1"
        rows.append(row)
    return rows


def cmd_worlds(a):
    plan = json.loads((Path(a.scenarios) / "scenarios.json").read_text())
    links = dict(t.split("=") for t in a.trials)
    worlds = []
    codes = set()
    for w in plan["worlds"]:
        name = Path(w["file"]).stem
        run = Path(a.runs) / name
        r = json.loads((run / "result.json").read_text())
        codes.add(r["code_sha256"]["sim.py"])
        area = W.area(W.load(run / "world.json"))
        rows = read_gz_json(run / "trace.json.gz")
        cols = rows["columns"]
        last = rows["rows"][-1]
        worlds.append({
            "name": name, "group": w["group"], "reason": w["reason"], "seed": r["seed"], "passed": r["passed"], "failure": r["failure"],
            "fired": r["fired"], "time_s": r["time_s"], "coverage": r["coverage"], "min_pressure_pa": r["min_pressure_pa"],
            "thumb": thumb(run), "end": [(last[cols.index("x")] - area["x0"]) / (area["x1"] - area["x0"]),
                                         (last[cols.index("z")] - area["z0"]) / (area["z1"] - area["z0"])],
            "trial": links.get(name),
        })
    if len(codes) != 1:
        sys.exit("worlds were recorded with different sim code")
    (PUBLIC / "worlds.json").write_text(json.dumps({
        "total": plan["total_worlds"], "count_reason": plan["count_reason"], "chat_sha256": plan["chat_sha256"],
        "groups": [{"name": g["name"], "reason": g["reason"]} for g in plan["groups"]],
        "not_tested": plan["not_tested"], "worlds": worlds, "sim_sha256": codes.pop(),
    }, separators=(",", ":")))
    print("worlds:", len(worlds), "failed:", sum(not w["passed"] for w in worlds))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trial")
    t.add_argument("run_dir")
    t.add_argument("id")
    t.add_argument("label")
    t.set_defaults(fn=cmd_trial)
    r = sub.add_parser("run-worlds")
    r.add_argument("scenarios")
    r.add_argument("out")
    r.set_defaults(fn=cmd_run_worlds)
    w = sub.add_parser("worlds")
    w.add_argument("scenarios")
    w.add_argument("runs")
    w.add_argument("--trials", nargs="*", default=[])
    w.set_defaults(fn=cmd_worlds)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
