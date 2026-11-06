"""The window pack's interface: the suction window robot on MuJoCo. It wraps policy/highrise5 with no edit there. Import this file and nothing else from the pack.

packs/README.md describes the contract. Simulated with hand-built physics, and not checked against real hardware.
"""
import gzip
import json
import math
import pathlib
import sys
import tempfile

HIGHRISE5 = pathlib.Path(__file__).resolve().parent.parent.parent / "highrise5"
HIGHRISE = HIGHRISE5.parent / "highrise"
if str(HIGHRISE5) not in sys.path:
    sys.path.insert(0, str(HIGHRISE5))

import mujoco

import compile5 as C
import engine5 as G
import judge5 as J
import run_trial5 as R
import world5 as W

NAME = "window"
ROBOT = "suction_window_cleaner"
BACKEND = "mujoco"
SIMULATED_NOTE = "Simulated with hand-built physics. Not checked against real hardware."
HOLDS = ("wind_hold", "battery_stop")
NUMBER_KEYS = ("coverage", "time_s", "slip_m", "peak_tether_n", "peak_chassis_contact_n", "min_pressure_pa", "end_battery", "hold_s", "hold_mean_wind_ms")
KEPT_STATES = 64
_states = {}  # Engine state for a world, so a group made by one call is there for the next call in this process.


def new_world():
    return W.parse((HIGHRISE / "worlds" / "nominal.json").read_bytes())


def validate(world):
    return W.validate(world)


def _state(world):
    key = json.dumps(world, sort_keys=True)
    if key not in _states:
        _states[key] = G.new_state(world)
    return _states[key]


def call(world, fn, args=None):
    try:
        state = _state(world)
    except W.WorldError:
        return {"result": "cannot_build:invalid_world", "rerun": False, "world": world}
    out = G.call(state, fn, args)
    new = out["state"]["world"]
    _states[json.dumps(new, sort_keys=True)] = out["state"]
    while len(_states) > KEPT_STATES:
        _states.pop(next(iter(_states)))
    return {"result": out["result"], "rerun": out["rerun"], "world": new}


def catalog():
    return G.catalog()


def physics_hash(world):
    return C.physics_hash(world)


def load_model(world):
    return mujoco.MjModel.from_xml_string(C.compile(world)[0])


def controller_files():
    return [str(HIGHRISE5 / "controller5.py")]


def run(world, *, seed=0, out=None):
    """The record holds run_trial5's result, because judge5 reads the sim live and cannot read it later. Its files stay in out, for export5 and replay."""
    folder = pathlib.Path(out) if out is not None else pathlib.Path(tempfile.mkdtemp(prefix="window-run-"))
    result = R.run(world, seed, folder)
    record = {"result": result, "out": str(folder)}
    meta = {"label": result["label"], "note": SIMULATED_NOTE, "robot": ROBOT, "seed": seed, "world": W.validate(world), "physics_hash": result["physics_sha256"], "wall_s": result["wall_s"]}
    return record, meta


def _rule_words(rule, event, result):
    t, value = event["t"], event["value"]
    return {
        "detach": f"The robot came off the glass at {t:.1f} s.",
        "tether_load": f"The tether load reached {value:.0f} N at {t:.1f} s. The limit is {J.TETHER_LOAD_LIMIT_N:.0f} N.",
        "slip_distance": f"The robot slid {value:.3f} m in one slide at {t:.1f} s. The limit is {J.SLIP_LIMIT_M:.2f} m.",
        "stalled": f"The robot stayed still on the glass for {value:.0f} s at the end, with no wind or battery reason.",
        "time_limit": f"The robot did not finish in {t:.0f} s.",
        "coverage": f"The robot cleaned {result['coverage'] * 100:.1f}% of the glass. The job needs {J.COVERAGE_REQUIRED * 100:.0f}%.",
        "false_done": f"The robot reported done at {t:.1f} s, with {value * 100:.0f} points more coverage than it had.",
    }.get(rule, f"The judge fired {rule} at {t:.1f} s.")


def judge(record, world):
    """From the recorded result. Same shape as the inspection pack: verdict, passed, reason, then numbers."""
    r = record["result"]
    numbers = {k: r[k] for k in NUMBER_KEYS if k in r and isinstance(r[k], (int, float)) and math.isfinite(r[k])}
    if r["failure"] == "sim_diverged":
        verdict, reason = "sim_diverged", f"The physics could not finish this run ({str(r.get('diverged_reason')).replace('_', ' ')}), so it says nothing about the robot."
    elif r["passed"]:
        verdict, reason = "passed", f"The robot cleaned {r['coverage'] * 100:.1f}% of the glass in {r['time_s']:.0f} s."
    elif r["outcome"] == "wind_hold":
        verdict, reason = "wind_hold", f"The robot held on the glass for {r['hold_s']:.0f} s at a mean wind of {r['hold_mean_wind_ms']:.1f} m/s and kept its grip. It cleaned {r['coverage'] * 100:.1f}%. The job did not finish."
    elif r["outcome"] == "battery_stop":
        verdict, reason = "battery_stop", f"The robot stopped on low battery and kept its grip. It cleaned {r['coverage'] * 100:.1f}%. The job did not finish."
    elif r["failure"] in r["fired"]:
        verdict, reason = r["failure"], _rule_words(r["failure"], r["fired"][r["failure"]], r)
    else:
        verdict, reason = str(r["failure"]), f"The run ended with status {r['status']}."
    return {"verdict": verdict, "passed": bool(r["passed"]), "reason": reason, **numbers}


def replay(record, meta, result=None):
    """JSON for a browser. The app's own player reads export5's files, and check that replay first. This is the same run as one file."""
    folder = pathlib.Path(record["out"])
    with gzip.open(folder / "qpos.json.gz", "rt") as f:
        qpos = json.load(f)
    return {"format": "window-qpos/1", "pack": NAME, "robot": ROBOT, "label": meta["label"], "note": meta["note"], "simulated": True, "hz": qpos["hz"], "nq": qpos["nq"],
            "model_xml": C.compile(meta["world"])[1], "area": W.area_rect(meta["world"]), "result": result, "frames": qpos["frames"], **({"mocap_frames": qpos["mocap_frames"]} if "mocap_frames" in qpos else {})}
