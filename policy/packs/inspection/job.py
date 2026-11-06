"""The inspection pack's subprocess: .venv-newton/bin/python -m packs.inspection.job <command>. server/pack_job.py describes the commands.

Only run and judge import Newton, so a world edit stays fast. Simulated: the policy is upstream's and unchecked against a real robot.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "server"))
import pack_job

from . import plant as PL
from . import world as W

NAME, ROBOT, BACKEND = "inspection", "anymal_c", "newton"
NOTE = "Simulated. The policy is upstream's and unchecked against a real robot. Not calibrated."
catalog, physics_hash = W.catalog, W.physics_hash
HERE = Path(__file__).resolve().parent
NOTES = [
    "Axes: z up, metres. The robot starts at the origin and faces +x. The default route goes to (5, 0), then (5, 4), then (11, 4), inside a 3.4 m walkway. Put a thing on the route for it to matter.",
    "The route follower knows only the route and its pose. The walking policy is blind and reads only the robot's own state. Neither sees objects.",
    "Everything must be something found in a plant: a cabinet (add_box), a crossover (add_steps), a cable ramp (add_ramp), a low pipe, a dropped cable tray, a valve, a leak (add_wet_patch) or a floor grating. Give each a name that says what it is. A pipe stays below 1 m unless it is overhead on the rack. A route's time_limit_s stays at or below 60.",
    "The box around the start, 0.9 m each way, must stay empty. An object may not span the origin.",
]
NOT_MODELLED = [
    {"factor": "Sensors and perception", "terms": "sensor|camera|lidar|percept|vision|dark|light|smoke|steam", "reason": "The policy is blind, and the run has no camera or lidar. Dark, smoke or steam change nothing."},
    {"factor": "Battery and heat", "terms": "battery|heat|temperature|thermal", "reason": "The robot has no battery or motor heat model."},
    {"factor": "Moving things and people", "terms": "people|person|worker|forklift|moving", "reason": "Every solid stays still. Nothing moves or walks into the robot."},
    {"factor": "The real robot", "terms": "real robot|real hardware|calibrat", "reason": "The policy and model are upstream's, and no real robot has checked this."},
]


def start():
    return W.build(*PL.PLANT)


def call(world, fn, args=None):
    return W.call(world, fn, args)


def scene(world):
    return {"solids": W.primitives(world), "scenery": W.scenery_primitives(world), "route": [{"x": 0.0, "y": 0.0}] + world["route"]["waypoints"], "floor_friction": world["floor"]["friction"]}


def outline(world):
    return {"kind": "route", "points": [[0.0, 0.0]] + [[p["x"], p["y"]] for p in world["route"]["waypoints"]]}


def t_limit(world):
    return world["route"]["time_limit_s"]


def call_line(fn, args):
    return f"{fn} " + ", ".join(f"{k} {v:g}" if isinstance(v, float) else f"{k} {v}" for k, v in args.items())


def controller_files():
    return [str(HERE / "controller.py")]


def code_line(verdict):
    """RouteFollower.command is the one routine a user may change that picks each walking command. No executed-line trace backs this."""
    if verdict in ("passed", "sim_failed"):
        return None
    for number, line in enumerate((HERE / "controller.py").read_text().splitlines(), 1):
        if "def command(self" in line:
            return {"file": "policy/packs/inspection/controller.py", "line": number, "why": "RouteFollower picks every walking command here, and it cannot see objects.", "traced": False}
    return None


def _events(judged):
    rows = [{"name": f"waypoint {i + 1}", "t": t, "value": i + 1} for i, t in enumerate(judged.get("waypoint_t_s", []))]
    for key, name in (("fell_t_s", "fell"), ("stuck_t_s", "stuck")):
        if judged.get(key) is not None:
            rows.append({"name": name, "t": judged[key], "value": judged[key]})
    return sorted(rows, key=lambda e: e["t"])


def _finish(pack, rec, meta):
    judged = pack.judge(rec, meta["world"])
    digest = hashlib.sha256(rec["base_q"].tobytes()).hexdigest()
    return {**pack_job.split_judged(judged), "events": _events(judged), "code": code_line(judged["verdict"]), "label": meta["label"], "note": NOTE, "safe_hold": False, "record_sha256": digest}, judged


def run(world, seed, out, progress):
    from . import controller as C
    from . import pack as P
    from . import sim as S

    real_command = C.RouteFollower.command
    steps = [0]

    def command(self, x, y, yaw):
        steps[0] += 1
        progress.update(steps[0] * S.POLICY_DT, x, y)
        return real_command(self, x, y, yaw)
    C.RouteFollower.command = command
    rec, meta = P.run(world, seed=seed, out=out / "record.npz")
    done, judged = _finish(P, rec, meta)
    with gzip.GzipFile(out / "replay.json.gz", "wb", mtime=0) as f:
        f.write(json.dumps(P.replay(rec, meta, judged), separators=(",", ":")).encode())
    return done


def judge_again(out):
    from . import pack as P

    rec, meta = P.load(out / "record.npz")
    return _finish(P, rec, meta)[0]


if __name__ == "__main__":
    pack_job.serve(sys.modules[__name__])
