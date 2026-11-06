"""Exports recorded high-rise runs for the browser app. Run with policy/.venv/bin/python at low priority.

app_export.py trial <run dir> <id> "<label>" [--out DIR]  one replay: public/trials/<id>/, or DIR with no change to the index
app_export.py worlds <scenarios dir> <campaign dir> --trials world_007=id ...  the worlds tab and the Recorded run: public/trials/worlds.json
The worlds file holds one finished campaign and its diagnosis, with the campaign's own seeds. A separate re-run with other seeds gives other outcomes.

Reads policy/highrise and the given folders. Writes only under public/trials/ and the given <out>.
Refuses a run whose model or code no longer matches what recorded it, or whose replay diverges.
"""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "policy" / "highrise"))
sys.path.insert(0, str(ROOT / "policy" / "server"))
import replay as replay_module
import sim as S
import stored_fix
import world as W

PUBLIC = ROOT / "public" / "trials"
REFERENCE_FRAMES = 21
DIRT_EVERY_STEPS = S.CONTROL_HZ  # one dirt grid per simulated second
DIRT_SCALE = 200  # stored byte = dirt level * scale
THUMB_NX, THUMB_NZ = 16, 20


def scene_elements(world):
    """Names of the scene elements in a world, for the label. Plain worlds have none."""
    return sorted({e["type"] if isinstance(e, dict) and "type" in e else str(e) for e in world.get("elements") or []})


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

    out = Path(a.out) if a.out else PUBLIC / a.id
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
        "sim_sha256": result["code_sha256"]["sim.py"], "elements": scene_elements(world),
        "dirt": {"nx": grid["nx"], "nz": grid["nz"], "every_steps": DIRT_EVERY_STEPS, "scale": DIRT_SCALE,
                 "clean_below": S.CLEAN_THRESHOLD, "count": len(dirt)},
        "replay_match": True,
    }, indent=1) + "\n")

    if a.out:
        print("exported", out, len(qpos["frames"]), "frames, replay MATCH")
        return
    index_path = PUBLIC / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    index = [t for t in index if t["id"] != a.id] + [{"id": a.id, "label": a.label}]
    index_path.write_text(json.dumps(index, indent=1) + "\n")
    print("exported", out, len(qpos["frames"]), "frames, replay MATCH")


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


def thumb_and_end(run):
    """The end-of-run glass and where the robot ended, as fractions of the work area."""
    area = W.area(W.load(run / "world.json"))
    rows = read_gz_json(run / "trace.json.gz")
    cols = rows["columns"]
    last = rows["rows"][-1]
    return {"thumb": thumb(run), "end": [(last[cols.index("x")] - area["x0"]) / (area["x1"] - area["x0"]),
                                         (last[cols.index("z")] - area["z0"]) / (area["z1"] - area["z0"])]}


def failure_view(diagnosis, trial_index, name_of):
    """The diagnosis in the shape of the run server's failures event, so the recorded and live pages draw the same thing."""
    types, other = [], []
    for f in diagnosis["failure_types"]:
        if not f["is_failure"]:
            other.append({"type": f["type"], "count": f["count"]})
            continue
        worst = f["worst_world"]
        types.append({"id": f"F{len(types) + 1}", "rule": f["type"], "requirement": f["requirement"], "severity": f["severity"], "count": f["count"],
                      "worlds": [trial_index(t) for t in f["trials"] if t.startswith("t")], "worst": trial_index(worst["trial"]), "worst_name": name_of(worst["trial"]),
                      "worst_measure": worst["measure"], "worst_value": worst["value"], "code_line": f["code_line"], "code": f.get("code")})
    excluded = [{"index": trial_index(f["trial"]), "name": name_of(f["trial"]), "why": f"Failed once, then came back in {f['same_failure_runs']} of {f['of']} repeats."} for f in diagnosis["reproduce"]["flaky"]]
    return {"types": types, "other": other, "excluded": excluded, "diverged": [], "known": True, "limits": "Code lines hold in this simulation only. Not checked against real hardware."}


def cmd_worlds(a):
    plan = json.loads((Path(a.scenarios) / "scenarios.json").read_text())
    campaign = Path(a.campaign)
    links = dict(t.split("=") for t in a.trials)
    rows = {r["trial"]: r for r in map(json.loads, (campaign / "results.jsonl").read_text().splitlines())}
    diagnosis = json.loads((campaign / "diagnosis.json").read_text())
    flaky = {f["trial"] for f in diagnosis["reproduce"]["flaky"]}
    worlds = []
    codes = set()
    for n, w in enumerate(plan["worlds"]):
        name = Path(w["file"]).stem
        trial = f"t{n:04d}"
        run = campaign / trial
        r = json.loads((run / "result.json").read_text())
        codes.add(r["code_sha256"]["sim.py"])
        if W.load(Path(a.scenarios) / w["file"]) != rows[trial]["world"]:
            sys.exit(f"{name}: the plan's world differs from the campaign's")
        if trial in flaky and name in links:
            sys.exit(f"{name} is flaky, so it cannot be a headline replay")
        worlds.append({
            "name": name, "index": n, "campaign_trial": trial, "group": w["group"], "reason": w["reason"], "seed": r["seed"], "passed": r["passed"], "failure": r["failure"], "outcome": r["outcome"],
            "flaky": trial in flaky, "fired": r["fired"], "time_s": r["time_s"], "coverage": r["coverage"], "min_pressure_pa": r["min_pressure_pa"],
            **thumb_and_end(run),
            "trial": links.get(name), "kind": "elements" if w.get("has_elements") else "varied",
        })
    if len(codes) != 1:
        sys.exit("worlds were recorded with different sim code")
    sim_sha = codes.pop()
    index_of = lambda t: int(t[1:])
    name_of = lambda t: worlds[index_of(t)]["name"]
    chat = re.search(r'^CHAT="(.*)"$', (ROOT / "policy" / "crashlab" / "loop.sh").read_text(), re.M).group(1)
    if hashlib.sha256(chat.encode()).hexdigest() != plan["chat_sha256"]:
        sys.exit("the chat in loop.sh is not the one this plan came from")
    fix, fix_summary, fix_log = stored_fix.recorded_fix(hashlib.sha256((ROOT / "policy" / "highrise" / "sim.py").read_bytes()).hexdigest())
    lines = []
    for line in (stored_fix.STORED_FIX / "try_2" / "patch.diff").read_text().splitlines()[:200]:
        if not line.startswith(("---", "+++", "diff ", "index ")):
            kind = "add" if line.startswith("+") else "del" if line.startswith("-") else "same"
            lines.append({"kind": kind, "text": line[1:] if line[:1] in "+- " else line})
    (PUBLIC / "worlds.json").write_text(json.dumps({
        "chat": chat, "total": plan["total_worlds"], "count_reason": plan["count_reason"], "chat_sha256": plan["chat_sha256"],
        "campaign": campaign.name, "campaign_seed": json.loads((campaign / "campaign.json").read_text())["seed"],
        "requirements": json.loads((campaign / "requirements.json").read_text())["requirements"],
        "counts": diagnosis["counts"], "controls": {"n": diagnosis["counts"]["controls"], "passed": diagnosis["counts"]["controls_passed"]},
        "failures": failure_view(diagnosis, index_of, name_of),
        "fix": fix, "fix_summary": fix_summary, "fix_log": fix_log, "fix_diff": lines,
        "campaign_seconds": a.seconds,
        "groups": [{"name": g["name"], "reason": g["reason"]} for g in plan["groups"]],
        "not_tested": plan["not_tested"], "worlds": worlds, "sim_sha256": sim_sha,
    }, separators=(",", ":")))
    print("worlds:", len(worlds), "failed:", sum(not w["passed"] and bool(w["failure"]) for w in worlds), "flaky:", sorted(flaky))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trial")
    t.add_argument("run_dir")
    t.add_argument("id")
    t.add_argument("label")
    t.add_argument("--out")
    t.set_defaults(fn=cmd_trial)
    w = sub.add_parser("worlds")
    w.add_argument("scenarios")
    w.add_argument("campaign")
    w.add_argument("--trials", nargs="*", default=[])
    w.add_argument("--seconds", type=float, required=True, help="wall time of the campaign, from its table.txt")
    w.set_defaults(fn=cmd_worlds)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
