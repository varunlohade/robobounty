"""Typed functions that edit a Newton lab world. Function names and arguments are untrusted.

call(world, fn, args) checks the arguments, builds a new world and never changes the old one. It returns
{"result", "world"}. The result is "ok" or "cannot_build:<code>". A code comes from CODES, so no text from the call
reaches the result. A world is data only: no code, no file paths, no mesh. sim.py is the only reader.

Axes: z up, the robot starts at the origin facing +x. Results are simulated. Nothing here is calibrated.
"""
import copy
import math
import re

SCHEMA = 1
MAX_OBJECTS = 40
MAX_REACH_M = 30.0
START_CLEAR_M = 0.7
MAX_RAMP_DEG = 45.0
DEFAULT_MU = 0.75

CODES = frozenset({
    "bad_args", "bad_name", "blocks_start", "invalid_world", "name_taken", "out_of_range", "outside_world", "too_many_objects",
    "too_steep", "unknown_function",
})
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")

MU = ("mu", 0.01, 2.0)
XY = (-MAX_REACH_M, MAX_REACH_M)
FUNCTIONS = {
    "set_ground": {"required": {"mu": MU[1:]}, "optional": {}},
    "set_target": {"required": {"x": XY, "y": XY}, "optional": {"radius": (0.2, 5.0)}},
    "add_box": {
        "required": {"x": XY, "y": XY, "sx": (0.02, 10.0), "sy": (0.02, 10.0), "sz": (0.02, 5.0)},
        "optional": {"yaw_deg": (-180.0, 180.0), "mu": MU[1:]},
    },
    "add_ramp": {
        "required": {"x": XY, "y": XY, "length": (0.2, 10.0), "width": (0.2, 10.0), "height": (0.01, 3.0)},
        "optional": {"mu": MU[1:]},
    },
    "add_steps": {
        "required": {"x": XY, "y": XY, "width": (0.2, 10.0), "depth": (0.1, 2.0), "rise": (0.01, 0.5)},
        "optional": {"count": (1, 20), "mu": MU[1:]},
    },
}
ADDERS = frozenset({"add_box", "add_ramp", "add_steps"})


class Refuse(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def new_world():
    return {"schema": SCHEMA, "ground": {"mu": DEFAULT_MU}, "target": {"x": 6.0, "y": 0.0, "radius": 1.5}, "objects": []}


def _number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refuse("bad_args")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise Refuse("out_of_range")
    return value


def _check_args(fn, args):
    if fn not in FUNCTIONS:
        raise Refuse("unknown_function")
    if not isinstance(args, dict):
        raise Refuse("bad_args")
    spec = FUNCTIONS[fn]
    allowed = set(spec["required"]) | set(spec["optional"]) | ({"name"} if fn in ADDERS else set())
    if set(args) - allowed or set(spec["required"]) - set(args):
        raise Refuse("bad_args")
    out = {}
    for key, (lo, hi) in {**spec["required"], **spec["optional"]}.items():
        if key in args:
            value = _number(args[key], lo, hi)
            if isinstance(lo, int) and isinstance(hi, int) and not isinstance(value, int):
                raise Refuse("bad_args")
            out[key] = value
    if fn in ADDERS:
        name = args.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refuse("bad_name")
        out["name"] = name
    return out


def footprint(obj):
    """Bounding rectangle (x0, x1, y0, y1) of an object on the ground."""
    x, y = obj["x"], obj["y"]
    if obj["kind"] == "box":
        a = math.radians(obj.get("yaw_deg", 0.0))
        hx = (abs(math.cos(a)) * obj["sx"] + abs(math.sin(a)) * obj["sy"]) / 2
        hy = (abs(math.sin(a)) * obj["sx"] + abs(math.cos(a)) * obj["sy"]) / 2
        return x - hx, x + hx, y - hy, y + hy
    if obj["kind"] == "ramp":
        run = obj["length"] + obj["height"] * obj["height"] / obj["length"]
        return x, x + run, y - obj["width"] / 2, y + obj["width"] / 2
    return x, x + obj["depth"] * obj.get("count", 3), y - obj["width"] / 2, y + obj["width"] / 2


def _check_object(obj):
    x0, x1, y0, y1 = footprint(obj)
    if max(abs(x0), abs(x1), abs(y0), abs(y1)) > MAX_REACH_M:
        raise Refuse("outside_world")
    if x0 < START_CLEAR_M and x1 > -START_CLEAR_M and y0 < START_CLEAR_M and y1 > -START_CLEAR_M:
        raise Refuse("blocks_start")
    if obj["kind"] == "ramp" and math.degrees(math.atan2(obj["height"], obj["length"])) > MAX_RAMP_DEG:
        raise Refuse("too_steep")


def validate(world):
    """Replays a stored world through the same functions, so a hand-edited file gets the same checks."""
    try:
        if not isinstance(world, dict) or set(world) != {"schema", "ground", "target", "objects"} or world["schema"] != SCHEMA:
            raise Refuse("invalid_world")
        out = new_world()
        out = _apply(out, "set_ground", world["ground"])
        out = _apply(out, "set_target", world["target"])
        if not isinstance(world["objects"], list):
            raise Refuse("invalid_world")
        for obj in world["objects"]:
            if not isinstance(obj, dict) or obj.get("kind") not in ("box", "ramp", "steps"):
                raise Refuse("invalid_world")
            out = _apply(out, "add_" + obj["kind"], {k: v for k, v in obj.items() if k != "kind"})
        return out
    except Refuse as refused:
        raise Refuse("invalid_world") from refused


def _apply(world, fn, args):
    clean = _check_args(fn, args)
    out = copy.deepcopy(world)
    if fn == "set_ground":
        out["ground"] = {"mu": float(clean["mu"])}
    elif fn == "set_target":
        out["target"] = {"x": float(clean["x"]), "y": float(clean["y"]), "radius": float(clean.get("radius", 1.5))}
    else:
        if len(out["objects"]) >= MAX_OBJECTS:
            raise Refuse("too_many_objects")
        if any(o["name"] == clean["name"] for o in out["objects"]):
            raise Refuse("name_taken")
        obj = {"kind": fn[len("add_"):], **clean}
        _check_object(obj)
        out["objects"].append(obj)
    return out


def call(world, fn, args):
    try:
        return {"result": "ok", "world": _apply(world, fn, args)}
    except Refuse as refused:
        return {"result": f"cannot_build:{refused.code}", "world": world}


def build(*calls):
    """Applies (fn, args) pairs from a new world and raises on the first refusal."""
    world = new_world()
    for fn, args in calls:
        world = _apply(world, fn, args)
    return world
