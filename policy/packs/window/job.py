"""The window pack's subprocess: .venv/bin/python -m packs.window.job <command>. server/pack_job.py describes the commands. Simulated."""
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "server"))
import pack_job

from . import pack as P

from . import frames as FR
import scene5 as SCENE

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


# (section, fields that trigger it, fields to show, icon, words): a setting the world's functions changed, as one small icon and value on the square.
WIND_FIELDS = ("steady_ms", "gust_ms", "gust_start_s", "gust_duration_s", "gust_count", "gust_period_s", "dir_deg")
VALUE_MARKS = (
    ("wind", WIND_FIELDS, ("steady_ms", "gust_ms"), "wind", lambda s, g: f"{s:g}/{g:g} m/s"),
    ("weather", ("wetness",), ("wetness",), "rain", lambda v: f"wet {v * 100:.0f}%"),
    ("weather", ("dust_gm2",), ("dust_gm2",), "dirt", lambda v: f"dust {v:g} g/m2"),
    ("weather", ("temperature_c",), ("temperature_c",), "heat", lambda v: f"{v:g} C"),
    ("weather", ("humidity_pct",), ("humidity_pct",), "rain", lambda v: f"humid {v:g}%"),
    ("robot", ("suction_pa",), ("suction_pa",), "suction", lambda v: f"{v:.0f} Pa"),
    ("robot", ("seal_leak_mm2",), ("seal_leak_mm2",), "leak", lambda v: f"leak {v:.0f} mm2"),
    ("robot", ("pad_force_n",), ("pad_force_n",), "pad", lambda v: f"pad {v:g} N"),
    ("robot", ("battery_start_frac",), ("battery_start_frac",), "battery", lambda v: f"{v * 100:.0f}%"),
    ("robot", ("clean_speed_ms",), ("clean_speed_ms",), "speed", lambda v: f"{v:g} m/s"),
    ("area", ("dirt_level",), ("dirt_level",), "dirt", lambda v: f"dirt {v:g}"),
    ("area", ("margin_m",), ("margin_m",), "margin", lambda v: f"margin {v:g} m"),
    ("area", ("width_m", "height_m"), ("width_m", "height_m"), "margin", lambda w, h: f"area {w:g}x{h:g} m"),
    ("area", ("drop_below_roof_m",), ("drop_below_roof_m",), "margin", lambda v: f"{v:g} m down"),
    ("panes", ("width_m", "height_m", "offset_x_m", "offset_z_m", "skip_every"), ("width_m", "height_m"), "panes", lambda w, h: f"panes {w:g}x{h:g} m"),
    ("panes", ("joint_depth_m", "joint_gap_m"), ("joint_depth_m", "joint_gap_m"), "panes", lambda d, g: f"joint {d * 1000:g}x{g * 1000:g} mm"),
    ("tower", ("height_m", "width_m", "floor_m"), ("height_m",), "margin", lambda v: f"tower {v:g} m"),
    ("robot_start", ("x_m", "above_top_m"), ("x_m", "above_top_m"), "route", lambda x, z: f"start {x:g}, {z:g} m"),
)


def _object_words(o):
    props, depth_mm = o["props"], o["size"][1] * 1000 if len(o["size"]) > 1 else 0
    return {"wet_patch": lambda: f"wet patch {props['wetness'] * 100:.0f}%", "dirt_patch": lambda: f"grime {props['level']:g}", "vent": lambda: f"vent {props['open_frac'] * 100:.0f}% open",
            "cradle": lambda: f"cradle {props['travel_m']:g} m travel", "object": lambda: "fixture"}.get(o["kind"], lambda: f"{o['kind'].replace('_', ' ')} {depth_mm:.0f} mm")()


def marks(base, world):
    """What this scenario changed, from its world: each new or moved object's rectangle on the glass in outline axes, and each changed setting as a value. Nothing else."""
    base, world = W.validate(base), W.validate(world)
    was = {o["name"]: o for o in base["objects"]}
    out = []
    for o in world["objects"]:
        if was.get(o["name"]) != o:
            x0, x1, z0, z1 = SCENE._rect(world, o)
            out.append({"kind": "shape", "what": o["kind"], "name": o["name"], "text": _object_words(o), "points": [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]})
    for section, trigger, shown, icon, words in VALUE_MARKS:
        if any(base[section][f] != world[section][f] for f in trigger):
            out.append({"kind": "value", "icon": icon, "text": words(*(world[section][f] for f in shown))})
    for side in ("corner", "setback"):
        if world["tower"][side] and base["tower"][side] != world["tower"][side]:
            at = world["tower"][side]
            out.append({"kind": "value", "icon": side, "text": f"corner at {at['x_m']:g} m" if side == "corner" else f"setback {at['above_top_m']:g} m up"})
    return out


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
        if re.fullmatch(rf'\s*(el)?if self\.phase == "{phase}":', line):
            return {"file": f"policy/highrise5/{path.name}", "line": number, "why": f"The controller was in its {phase} phase when the judge fired.", "traced": False}
    return None


def _finish(result, world, folder):
    judged = pack_job.split_judged(P.judge({"result": result}, world))
    events = sorted(({"name": k, "t": v["t"], "value": v["value"]} for k, v in result["fired"].items()), key=lambda e: e["t"])
    return {**judged, "events": events, "code": code_line(result, folder), "label": result["label"], "note": NOTE, "safe_hold": judged["verdict"] in P.HOLDS,
            "final_state_sha256": result["final_state_sha256"], "action_chain_head": result["action_chain_head"]}


def run(world, seed, out, progress):
    real_step = P.R.S.Sim.step
    frames_on = pack_job.frames_on(progress)
    camera = FR.Camera(world) if frames_on else None
    clock = pack_job.FrameClock(out, camera.live) if frames_on else None

    def step(sim, action):
        x, z = sim.body_xz()
        progress.update(sim.t, x, z)
        if frames_on:
            clock.tick(sim.d)  # Copies the state to a separate model and draws there. The sim's state is not touched.
            progress.frames = clock.count
        return real_step(sim, action)
    P.R.S.Sim.step = step
    folder = out / "run"
    record, meta = P.run(world, seed=seed, out=folder)
    done = _finish(record["result"], meta["world"], folder)
    if frames_on:
        done["film"] = pack_job.write_film(out, camera.film(folder))
    return done


def judge_again(out):
    folder = out / "run"
    result = json.loads((folder / "result.json").read_text())
    return _finish(result, W.load(folder / "world.json"), folder)


if __name__ == "__main__":
    pack_job.serve(sys.modules[__name__])
