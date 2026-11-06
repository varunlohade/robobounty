"""The window pack's subprocess: .venv/bin/python -m packs.window.job <command>. server/pack_job.py describes the commands. Simulated."""
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "server"))
import pack_job

from . import pack as P

R, W, J = P.R, P.W, P.J
NAME, ROBOT, BACKEND, NOTE = P.NAME, P.ROBOT, P.BACKEND, P.SIMULATED_NOTE
catalog, call, physics_hash, controller_files = P.catalog, P.call, P.physics_hash, P.controller_files
NOTES = [
    "x_m is along the glass from the left edge of the work area. below_top_m is down from the top of the work area, and a negative value is above it. out_m is outward from the glass plane.",
    "The robot cleans vertical lanes across the whole work area, from above its top to below its bottom. Its heading is fixed. It knows nothing about objects on the glass.",
    "An object changes the run only if it is solid and within 0.13 m of the glass. Names are lower case letters, digits and underscores.",
    "Use add_part (ac_unit, sign, vent_hood, window_frame_bracket) or the add_ledge, add_sill, add_fin, add_sign, add_balcony, add_vent, add_frame_step, add_wet_patch, add_dirt_patch and add_cradle functions, since each brings its own mounts. Use add_object only for a real thing with a mount, with material brushed_alu, painted_steel, weathered_concrete, dark_sealant, galvanised or safety_paint, and with out_m half its depth so it touches the wall.",
]
NOT_MODELLED = [
    {"factor": "Airborne sand and snow", "terms": "sand|snow|ice|hail", "reason": "Only dust already on the glass has physics. Sand or snow in the air is picture only."},
    {"factor": "Rain on the seal and sensors", "terms": "rain|droplet", "reason": "Wetness changes glass friction only. Rain does not reach the seal, sensors or tether."},
    {"factor": "Wear and corrosion", "terms": "wear|corros|ageing|aging", "reason": "The robot's parts stay as new for the whole run."},
    {"factor": "The fall after a detach", "terms": "fall|tether catch", "reason": "Physics stops at a detach. The fall and the tether catch are not simulated."},
    {"factor": "Real hardware", "terms": "real hardware|calibrat", "reason": "The physics is hand-built, and no real robot has checked it."},
]


def start():
    return P.new_world()


def scene(world):
    return {}


def outline(world):
    return {"kind": "area", **W.area_rect(W.validate(world))}


def t_limit(world):
    return J.TIME_LIMIT_S


def call_line(fn, args):
    return f"{fn} " + ", ".join(f"{k} {v:g}" if isinstance(v, float) else f"{k} {v}" for k, v in args.items())


def code_line(result, folder):
    """The controller branch active when the first rule fired. It comes from the recorded phase, and is not an executed-line trace."""
    fired = result["fired"]
    if not fired:
        return None
    first = min(fired.values(), key=lambda e: e["t"])
    with gzip.open(folder / "trace.json.gz", "rt") as f:
        trace = json.load(f)
    rows = trace["rows"]
    if not rows:
        return None
    phase = rows[min(int(first["t"] * P.R.S.CONTROL_HZ), len(rows) - 1)][trace["columns"].index("phase")]
    path = Path(P.controller_files()[0])
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if re.search(rf'self\.phase (==|in) .*"{phase}"', line):
            return {"file": f"policy/highrise5/{path.name}", "line": number, "why": f"The controller was in its {phase} phase when the judge fired.", "traced": False}
    return None


def _finish(result, world, folder):
    judged = pack_job.split_judged(P.judge({"result": result}, world))
    events = sorted(({"name": k, "t": v["t"], "value": v["value"]} for k, v in result["fired"].items()), key=lambda e: e["t"])
    return {**judged, "events": events, "code": code_line(result, folder), "label": result["label"], "note": NOTE, "safe_hold": judged["verdict"] in P.HOLDS,
            "final_state_sha256": result["final_state_sha256"], "action_chain_head": result["action_chain_head"]}


def run(world, seed, out, progress):
    real_step = P.R.S.Sim.step

    def step(sim, action):
        x, z = sim.body_xz()
        progress.update(sim.t, x, z)
        return real_step(sim, action)
    P.R.S.Sim.step = step
    folder = out / "run"
    record, meta = P.run(world, seed=seed, out=folder)
    return _finish(record["result"], meta["world"], folder)


def judge_again(out):
    folder = out / "run"
    result = json.loads((folder / "result.json").read_text())
    return _finish(result, W.load(folder / "world.json"), folder)


if __name__ == "__main__":
    pack_job.serve(sys.modules[__name__])
