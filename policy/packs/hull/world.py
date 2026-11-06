"""A hull world as JSON data: flat steel plate, weld seams, fouling, water, current and the patch to clean. No code and no paths.

Adhesion is flat only. The physics plate is the plane z = 0, facing down. The bilge curve exists only in the picture.
"""
import copy
import hashlib
import json
import math

SCHEMA = 1
OK = "ok"
PICTURE = "picture only, no re-run"
PLATE_X = (-1.5, 9.0)
PLATE_Y = (-1.5, 3.4)  # The physics plate. The picture's bilge starts at the far edge.
TRANSVERSE_SEAMS_X = (1.6, 4.0, 6.4)
LONGITUDINAL_SEAMS_Y = (1.0,)
MIN_LANE_LENGTH_M = 1.5
PHYSICS_KEYS = ("current", "water", "seam", "magnet", "fouling", "patch", "time_limit_s")


class Refuse(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _num(lo, hi):
    return {"type": "number", "minimum": lo, "maximum": hi}


def _set(section):
    def edit(world, args):
        world[section].update(args)
    return edit


def _set_patch(world, args):
    if args["x1"] - args["x0"] < MIN_LANE_LENGTH_M or args["y1"] - args["y0"] < 0.4:
        raise Refuse("patch_too_small")
    world["patch"] = dict(args)


def _set_limit(world, args):
    world["time_limit_s"] = args["seconds"]


REGISTRY = {
    "set_current": {"args": {"speed_ms": _num(0.0, 6.0), "dir_deg": _num(-180.0, 180.0)}, "edit": _set("current"), "rerun": True, "note": "A steady, uniform current. No waves and no flow simulation."},
    "set_water": {"args": {"density": _num(990.0, 1040.0), "viscosity": _num(0.0005, 0.002)}, "edit": _set("water"), "rerun": True, "note": "MuJoCo's fluid settings."},
    "set_seam": {"args": {"height_m": _num(0.0, 0.05)}, "edit": _set("seam"), "rerun": True, "note": "Height of every weld bead below the plate."},
    "set_magnet": {"args": {"force_n": _num(0.0, 1500.0), "rear_fraction": _num(0.0, 1.0), "gap_scale_m": _num(0.001, 0.05)}, "edit": _set("magnet"), "rerun": True, "note": "Force per driven wheel at zero gap, the rear swivel wheels' share of it, and the gap at which force falls to a quarter."},
    "set_fouling": {"args": {"slime": _num(0.0, 1.0), "barnacle": _num(0.0, 1.0)}, "edit": _set("fouling"), "rerun": True, "note": "Mean starting level of each layer. The seed sets the pattern."},
    "set_patch": {"args": {"x0": _num(*PLATE_X), "x1": _num(*PLATE_X), "y0": _num(*PLATE_Y), "y1": _num(*PLATE_Y)}, "edit": _set_patch, "rerun": True, "note": "The area the judge scores."},
    "set_time_limit": {"args": {"seconds": _num(5.0, 1200.0)}, "edit": _set_limit, "rerun": True, "note": "The run ends here if the lanes are not done."},
    "set_hull_mark": {"args": {"text": {"type": "string", "pattern": "^[A-Z0-9 -]{1,12}$"}}, "edit": _set("picture"), "rerun": False, "note": "Picture only. A stencil, never a real ship's name."},
}


def catalog():
    return [{"name": name, "args": copy.deepcopy(row["args"]), "rerun": row["rerun"], "note": row["note"]} for name, row in REGISTRY.items()]


def new_world():
    return {
        "schema": SCHEMA,
        "current": {"speed_ms": 0.5, "dir_deg": 90.0},
        "water": {"density": 1025.0, "viscosity": 0.00108},
        "seam": {"height_m": 0.006},
        "magnet": {"force_n": 380.0, "rear_fraction": 0.35, "gap_scale_m": 0.008},
        "fouling": {"slime": 0.75, "barnacle": 0.4},
        "patch": {"x0": 0.6, "x1": 5.6, "y0": 0.0, "y1": 2.4},
        "time_limit_s": 400.0,
        "picture": {"text": "FR 112"},
    }


def _check(row, args):
    if not isinstance(args, dict) or set(args) - set(row["args"]) or set(row["args"]) - set(args):
        raise Refuse("bad_args")
    for key, rule in row["args"].items():
        v = args[key]
        if rule["type"] == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise Refuse("bad_args")
            if not rule["minimum"] <= v <= rule["maximum"]:
                raise Refuse("out_of_range")
        else:
            import re
            if not isinstance(v, str) or not re.fullmatch(rule["pattern"], v):
                raise Refuse("bad_args")


def _apply(world, fn, args):
    if not isinstance(fn, str) or fn not in REGISTRY:
        raise Refuse("unknown_function")
    _check(REGISTRY[fn], args)
    out = copy.deepcopy(world)
    REGISTRY[fn]["edit"](out, dict(args))
    return out


def call(world, fn, args=None):
    try:
        new = _apply(world, fn, {} if args is None else args)
    except Refuse as refused:
        return {"result": f"cannot_build:{refused.code}", "rerun": False, "world": world}
    rerun = physics_hash(new) != physics_hash(world)
    return {"result": OK if rerun or REGISTRY[fn]["rerun"] else PICTURE, "rerun": rerun, "world": new}


def build(*calls):
    world = new_world()
    for fn, args in calls:
        world = _apply(world, fn, args)
    return world


def validate(world):
    """Replays a stored world through the same functions, so a hand-edited file gets the same checks."""
    base = new_world()
    if not isinstance(world, dict) or set(world) != set(base) or world.get("schema") != SCHEMA:
        raise Refuse("invalid_world")
    try:
        out = base
        out = _apply(out, "set_current", world["current"])
        out = _apply(out, "set_water", world["water"])
        out = _apply(out, "set_seam", world["seam"])
        out = _apply(out, "set_magnet", world["magnet"])
        out = _apply(out, "set_fouling", world["fouling"])
        out = _apply(out, "set_patch", world["patch"])
        out = _apply(out, "set_time_limit", {"seconds": world["time_limit_s"]})
        return _apply(out, "set_hull_mark", world["picture"])
    except (Refuse, TypeError, KeyError) as refused:
        raise Refuse("invalid_world") from refused


def physics_hash(world):
    text = json.dumps({k: world[k] for k in PHYSICS_KEYS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()
