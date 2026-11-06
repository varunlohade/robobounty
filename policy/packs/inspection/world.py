"""Typed functions that edit an inspection world. Function names and arguments are untrusted.

call(world, fn, args) checks the arguments, builds a new world and never changes the old one. It returns
{"result", "rerun", "world"}. The result is "ok", "picture only, no re-run" or "cannot_build:<code>". A code comes from
CODES, so no text from the call reaches the result. A world is data only: no code, no file paths, no mesh.

Axes: z up, metres. The robot starts at the origin and faces +x. Each object has a local +x, its walking direction,
and yaw_deg turns that about the object's x, y. primitives() is the one place that turns objects into solids, and the
model loader and the replay both read it. Scenery is picture only: it never enters the physics model, and the robot
walks through it. Limits here are ours. Results are simulated, and nothing is calibrated to a real robot.
"""
import copy
import hashlib
import json
import math
import re

SCHEMA = 1
OK = "ok"
PICTURE = "picture only, no re-run"
DEFAULT_FRICTION = 0.75  # upstream's default_shape_cfg.mu
EARTH_G = 9.81
MAX_REACH_M = 40.0
START_CLEAR_M = 0.9  # half the box around the start that must stay empty. ANYmal C is about 1.1 m long
MIN_LEG_M = 0.5
MAX_WAYPOINTS = 16
MAX_OBJECTS = 40
MAX_SCENERY = 120
MAX_PRIMITIVES = 300
MAX_SCENERY_PRIMITIVES = 2500
MAX_RAMP_DEG = 35.0
WET_PATCH_THICK_M = 0.005
GRATING_BAR_WIDTH_M = 0.03

CODES = frozenset({
    "bad_args", "bad_name", "blocks_start", "invalid_world", "name_taken", "out_of_range", "outside_world", "route_leg_too_short",
    "too_many_objects", "too_many_shapes", "too_many_waypoints", "too_steep", "unknown_function",
})
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")


class Refuse(Exception):
    def __init__(self, code):
        assert code in CODES
        super().__init__(code)
        self.code = code


# Argument schemas are a small subset of JSON Schema, as in highrise5/engine5.py, so an AI loop can pass them on as they are.
def _num(lo, hi):
    return {"type": "number", "minimum": lo, "maximum": hi}


def _int(lo, hi):
    return {"type": "integer", "minimum": lo, "maximum": hi}


NAME = {"type": "string", "pattern": NAME_RE.pattern}
XY = _num(-MAX_REACH_M, MAX_REACH_M)
YAW = _num(-180.0, 180.0)
FRICTION = _num(0.02, 2.0)
POINT = {"type": "object", "properties": {"x": XY, "y": XY}, "required": ["x", "y"], "additionalProperties": False}


def _schema(props, required):
    return {"type": "object", "properties": props, "required": sorted(required), "additionalProperties": False}


def _object_schema(props, required):
    base = {"name": NAME, "x": XY, "y": XY, "yaw_deg": YAW}
    return _schema({**base, **props}, {"name", "x", "y", *required})


def _check_value(rule, value):
    kind = rule["type"]
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == "integer" and not isinstance(value, int)):
            raise Refuse("bad_args")
        try:
            number = float(value)
        except OverflowError:
            raise Refuse("out_of_range") from None
        if not math.isfinite(number) or not rule["minimum"] <= number <= rule["maximum"]:
            raise Refuse("out_of_range")
        return value if kind == "integer" else number
    if kind == "string":
        if not isinstance(value, str) or not re.fullmatch(rule["pattern"], value):
            raise Refuse("bad_name" if rule is NAME else "bad_args")
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise Refuse("bad_args")
        if len(value) < rule["minItems"]:
            raise Refuse("bad_args")
        if len(value) > rule["maxItems"]:
            raise Refuse("too_many_waypoints")
        return [_check_value(rule["items"], item) for item in value]
    return _check_args(rule, value)


def _check_args(schema, args):
    if not isinstance(args, dict):
        raise Refuse("bad_args")
    props = schema["properties"]
    if any(not isinstance(key, str) or key not in props for key in args) or any(key not in args for key in schema["required"]):
        raise Refuse("bad_args")
    return {key: _check_value(props[key], value) for key, value in args.items()}


def _adder(kind):
    def add(world, a):
        names = [o["name"] for o in world["objects"]] + [o["name"] for o in world["scenery"]]
        if a["name"] in names:
            raise Refuse("name_taken")
        if len(world["objects"]) >= MAX_OBJECTS:
            raise Refuse("too_many_objects")
        obj = {"kind": kind, **a}
        x0, x1, y0, y1 = footprint(obj)
        if max(abs(x0), abs(x1), abs(y0), abs(y1)) > MAX_REACH_M:
            raise Refuse("outside_world")
        if x0 < START_CLEAR_M and x1 > -START_CLEAR_M and y0 < START_CLEAR_M and y1 > -START_CLEAR_M and not _high_above_start(obj):
            raise Refuse("blocks_start")
        if kind == "ramp" and math.degrees(math.atan2(a["height"], a["length"])) > MAX_RAMP_DEG:
            raise Refuse("too_steep")
        world["objects"].append(obj)
        if len(primitives(world)) > MAX_PRIMITIVES:
            raise Refuse("too_many_shapes")
    return add


def _high_above_start(obj):
    return obj["kind"] == "pipe" and obj.get("clearance", 0.0) > 1.2


def _scenery_adder(kind):
    def add(world, a):
        names = [o["name"] for o in world["objects"]] + [o["name"] for o in world["scenery"]]
        if a["name"] in names:
            raise Refuse("name_taken")
        if len(world["scenery"]) >= MAX_SCENERY:
            raise Refuse("too_many_objects")
        world["scenery"].append({"kind": kind, **a})
        if len(scenery_primitives(world)) > MAX_SCENERY_PRIMITIVES:
            raise Refuse("too_many_shapes")
    return add


def _set_floor(world, a):
    world["floor"] = {"friction": a["friction"]}


def _set_route(world, a):
    points = [(0.0, 0.0)] + [(p["x"], p["y"]) for p in a["waypoints"]]
    if any(math.dist(p, q) < MIN_LEG_M for p, q in zip(points, points[1:])):
        raise Refuse("route_leg_too_short")
    world["route"] = {"waypoints": a["waypoints"], "time_limit_s": a.get("time_limit_s", 60.0)}


def _set_payload(world, a):
    world["payload"] = {"mass_kg": a["mass_kg"]}


def _set_gravity(world, a):
    world["gravity"] = {"g": a["g"]}


def _picture(props, required, kind, note):
    return {"args": _schema({"name": NAME, **props}, {"name", *required}), "edit": _scenery_adder(kind), "rerun": False, "note": f"Picture only. The robot walks through it. {note}"}


REGISTRY = {
    "set_floor": {"args": _schema({"friction": FRICTION}, {"friction"}), "edit": _set_floor, "rerun": True, "note": "Friction of the whole floor."},
    "add_box": {"args": _object_schema({"sx": _num(0.02, 10.0), "sy": _num(0.02, 10.0), "sz": _num(0.02, 5.0), "friction": FRICTION}, {"sx", "sy", "sz"}),
                "edit": _adder("box"), "rerun": True, "note": "A solid box. x, y is its centre."},
    "add_ramp": {"args": _object_schema({"length": _num(0.2, 10.0), "width": _num(0.2, 10.0), "height": _num(0.01, 2.0), "landing": _num(0.2, 10.0), "friction": FRICTION},
                                        {"length", "width", "height"}),
                 "edit": _adder("ramp"), "rerun": True, "note": "Up, a flat landing, and down. x, y is the middle of the first edge."},
    "add_steps": {"args": _object_schema({"width": _num(0.2, 10.0), "depth": _num(0.1, 2.0), "rise": _num(0.01, 0.5), "count": _int(1, 12), "landing": _num(0.2, 10.0), "friction": FRICTION},
                                         {"width", "depth", "rise"}),
                  "edit": _adder("steps"), "rerun": True, "note": "A steel crossover: steps up, a landing, steps down, and handrails at both edges. x, y is the middle of the first edge."},
    "add_pipe": {"args": _object_schema({"length": _num(0.2, 20.0), "radius": _num(0.01, 0.5), "clearance": _num(0.0, 3.0)}, {"length", "radius"}),
                 "edit": _adder("pipe"), "rerun": True, "note": "A pipe across the walkway, with flanges, and with saddles when clearance is above 0. clearance is the gap under it. x, y is its centre."},
    "add_cable_tray": {"args": _object_schema({"length": _num(0.5, 10.0), "width": _num(0.15, 0.8), "height": _num(0.03, 0.2)}, {"length"}),
                       "edit": _adder("cable_tray"), "rerun": True, "note": "A dropped ladder-type cable tray with its cables, lying across the walkway. x, y is its centre."},
    "add_valve": {"args": _object_schema({"size": _num(0.05, 0.2)}, set()),
                  "edit": _adder("valve"), "rerun": True, "note": "A gate valve on a floor-mounted spool, with a handwheel. size is the spool radius. x, y is its centre."},
    "add_wet_patch": {"args": _object_schema({"sx": _num(0.1, 20.0), "sy": _num(0.1, 20.0), "friction": FRICTION}, {"sx", "sy"}),
                      "edit": _adder("wet_patch"), "rerun": True, "note": f"A leak: a {WET_PATCH_THICK_M * 1000:g} mm thick slippery puddle that fits inside sx by sy. x, y is its centre."},
    "add_grating": {"args": _object_schema({"length": _num(0.2, 10.0), "width": _num(0.2, 10.0), "bar_height": _num(0.005, 0.1), "pitch": _num(0.05, 0.5), "friction": FRICTION},
                                           {"length", "width"}),
                    "edit": _adder("grating"), "rerun": True, "note": "Raised steel bars across the walkway. x, y is the middle of the first edge."},
    "set_route": {"args": _schema({"waypoints": {"type": "array", "items": POINT, "minItems": 1, "maxItems": MAX_WAYPOINTS}, "time_limit_s": _num(5.0, 300.0)}, {"waypoints"}),
                  "edit": _set_route, "rerun": True, "note": "Waypoints in order, from the start at the origin."},
    "set_payload": {"args": _schema({"mass_kg": _num(0.0, 40.0)}, {"mass_kg"}), "edit": _set_payload, "rerun": True,
                    "note": "A sensor box fixed on the back. The upstream policy never trained with it."},
    "set_gravity": {"args": _schema({"g": _num(0.5, 25.0)}, {"g"}), "edit": _set_gravity, "rerun": True,
                    "note": "Downward gravity in m/s2. The upstream policy never trained away from 9.81."},
    "add_wall": _picture({"x0": XY, "y0": XY, "x1": XY, "y1": XY, "height": _num(0.1, 15.0)}, {"x0", "y0", "x1", "y1"}, "wall", "Clad wall on a concrete base."),
    "add_tank": _picture({"x": XY, "y": XY, "radius": _num(0.1, 10.0), "height": _num(0.1, 15.0)}, {"x", "y", "radius"}, "tank", "Vertical vessel on legs, with bands, a ladder and a nozzle."),
    "add_pipe_rack": _picture({"x0": XY, "y0": XY, "x1": XY, "y1": XY, "height": _num(1.0, 15.0)}, {"x0", "y0", "x1", "y1", "height"}, "pipe_rack", "Overhead pipes with flanges, on hangers."),
    "add_railing": _picture({"x0": XY, "y0": XY, "x1": XY, "y1": XY}, {"x0", "y0", "x1", "y1"}, "railing", "Walkway handrail with posts and a toe board."),
    "add_column": _picture({"x": XY, "y": XY, "height": _num(1.0, 15.0)}, {"x", "y", "height"}, "column", "Steel building column."),
    "add_beam": _picture({"x0": XY, "y0": XY, "x1": XY, "y1": XY, "height": _num(1.0, 15.0)}, {"x0", "y0", "x1", "y1", "height"}, "beam", "Steel roof beam."),
    "add_light": _picture({"x": XY, "y": XY, "height": _num(1.0, 15.0)}, {"x", "y", "height"}, "light", "Hanging high-bay light. The renderer also places a light here."),
    "add_floor_line": _picture({"x0": XY, "y0": XY, "x1": XY, "y1": XY}, {"x0", "y0", "x1", "y1"}, "floor_line", "Painted walkway line."),
    "add_gauge": _picture({"x": XY, "y": XY}, {"x", "y"}, "gauge", "Pressure gauge on a post: what the robot comes to read."),
    "add_pump": _picture({"x": XY, "y": XY, "yaw_deg": YAW}, {"x", "y"}, "pump", "Pump and motor on a base."),
}
OBJECT_FN = {k: f"add_{k}" for k in ("box", "ramp", "steps", "pipe", "wet_patch", "grating", "cable_tray", "valve")}
SCENERY_FN = {k: f"add_{k}" for k in ("wall", "tank", "pipe_rack", "railing", "column", "beam", "light", "floor_line", "gauge", "pump")}


def catalog():
    return [{"name": name, "args": copy.deepcopy(row["args"]), "rerun": row["rerun"], "note": row["note"]} for name, row in REGISTRY.items()]


def new_world():
    return {
        "schema": SCHEMA,
        "floor": {"friction": DEFAULT_FRICTION},
        "gravity": {"g": EARTH_G},
        "payload": {"mass_kg": 0.0},
        "route": {"waypoints": [{"x": 6.0, "y": 0.0}], "time_limit_s": 60.0},
        "objects": [],
        "scenery": [],
    }


def _apply(world, fn, args):
    if not isinstance(fn, str) or fn not in REGISTRY:
        raise Refuse("unknown_function")
    row = REGISTRY[fn]
    clean = _check_args(row["args"], args)
    out = copy.deepcopy(world)
    row["edit"](out, clean)
    return out


def call(world, fn, args=None):
    try:
        new = _apply(world, fn, {} if args is None else args)
    except Refuse as refused:
        return {"result": f"cannot_build:{refused.code}", "rerun": False, "world": world}
    rerun = physics_hash(new) != physics_hash(world)
    return {"result": OK if rerun or REGISTRY[fn]["rerun"] else PICTURE, "rerun": rerun, "world": new}


def build(*calls):
    """Applies (fn, args) pairs from a new world and raises on the first refusal."""
    world = new_world()
    for fn, args in calls:
        world = _apply(world, fn, args)
    return world


def validate(world):
    """Replays a stored world through the same functions, so a hand-edited file gets the same checks."""
    keys = {"schema", "floor", "gravity", "payload", "route", "objects", "scenery"}
    try:
        if not isinstance(world, dict) or set(world) != keys or world["schema"] != SCHEMA:
            raise Refuse("invalid_world")
        if not isinstance(world["objects"], list) or not isinstance(world["scenery"], list):
            raise Refuse("invalid_world")
        out = new_world()
        out = _apply(out, "set_floor", world["floor"])
        out = _apply(out, "set_gravity", world["gravity"])
        out = _apply(out, "set_payload", world["payload"])
        out = _apply(out, "set_route", world["route"])
        for items, table in ((world["objects"], OBJECT_FN), (world["scenery"], SCENERY_FN)):
            for obj in items:
                if not isinstance(obj, dict) or not isinstance(obj.get("kind"), str) or obj["kind"] not in table:
                    raise Refuse("invalid_world")
                out = _apply(out, table[obj["kind"]], {k: v for k, v in obj.items() if k != "kind"})
        return out
    except Refuse as refused:
        raise Refuse("invalid_world") from refused


def physics_inputs(world):
    """All that the physics reads. A picture edit leaves this unchanged."""
    return {k: world[k] for k in ("floor", "gravity", "payload", "route", "objects")}


def physics_hash(world):
    text = json.dumps(physics_inputs(world), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _local_extent(obj):
    """(x0, x1, half_y) in the object's own frame, with x, y at its local origin."""
    kind = obj["kind"]
    if kind == "box" or kind == "wet_patch":
        return -obj["sx"] / 2, obj["sx"] / 2, obj["sy"] / 2
    if kind == "ramp":
        return 0.0, 2 * obj["length"] + obj.get("landing", 1.0), obj["width"] / 2
    if kind == "steps":
        return 0.0, 2 * obj["depth"] * obj.get("count", 3) + obj.get("landing", 1.0), obj["width"] / 2
    if kind == "pipe":
        return -obj["radius"], obj["radius"], obj["length"] / 2 + obj["radius"]
    if kind == "cable_tray":
        return -obj.get("width", 0.3) / 2, obj.get("width", 0.3) / 2, obj["length"] / 2
    if kind == "valve":
        r = obj.get("size", 0.08)
        return -2.0 * r, 2.0 * r, 3.0 * r
    return 0.0, obj["length"], obj["width"] / 2


def _cos_sin(obj):
    a = math.radians(obj.get("yaw_deg", 0.0))
    return math.cos(a), math.sin(a)


def footprint(obj):
    """Bounding rectangle (x0, x1, y0, y1) of an object on the floor, in world axes."""
    x0, x1, hy = _local_extent(obj)
    c, s = _cos_sin(obj)
    xs = [obj["x"] + c * lx - s * ly for lx in (x0, x1) for ly in (-hy, hy)]
    ys = [obj["y"] + s * lx + c * ly for lx in (x0, x1) for ly in (-hy, hy)]
    return min(xs), max(xs), min(ys), max(ys)


def _quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _axis_quat(axis, angle):
    s, c = math.sin(angle / 2), math.cos(angle / 2)
    return (axis[0] * s, axis[1] * s, axis[2] * s, c)


ALONG_Y = _axis_quat((1.0, 0.0, 0.0), math.pi / 2)
NO_TURN = (0.0, 0.0, 0.0, 1.0)
# Albedo in linear colour. Muted on purpose: paint, galvanised steel, concrete. A texture name, if any, is applied by the renderer only.
MATERIALS = {
    "steel": (0.22, 0.23, 0.24), "dark_steel": (0.09, 0.09, 0.10), "galvanised": (0.30, 0.31, 0.31), "plate": (0.19, 0.20, 0.21), "pipe_paint": (0.17, 0.21, 0.20), "flange": (0.12, 0.13, 0.14),
    "valve_body": (0.08, 0.10, 0.13), "handwheel": (0.24, 0.05, 0.04), "rubber": (0.015, 0.015, 0.017), "cabinet": (0.33, 0.33, 0.29), "wet": (0.10, 0.105, 0.115),
    "clad_pipe": (0.42, 0.43, 0.43), "tank": (0.42, 0.43, 0.41), "cladding": (0.40, 0.43, 0.41), "concrete": (0.36, 0.35, 0.33), "column": (0.17, 0.20, 0.23), "line": (0.42, 0.31, 0.05),
    "lamp": (0.95, 0.93, 0.85), "motor": (0.06, 0.11, 0.15), "gauge": (0.75, 0.75, 0.72), "route_mark": (0.42, 0.31, 0.05),
}
TEXTURED = {"concrete": "grime", "cladding": "sheet", "tank": "grime", "plate": "grime", "cabinet": "grime", "column": "grime", "clad_pipe": "grime"}
PUDDLE = ((0.0, 0.0, 0.42), (0.32, 0.12, 0.3), (-0.3, -0.14, 0.34), (0.1, -0.3, 0.2), (-0.12, 0.3, 0.22), (0.38, -0.2, 0.12), (-0.38, 0.22, 0.12))


def _object_parts(obj):
    """Solids in the object's own frame: (type, centre, quat, half or (radius, half_height), material). The physics and the picture read the same list."""
    kind = obj["kind"]
    if kind == "box":
        return [("box", (0.0, 0.0, obj["sz"] / 2), NO_TURN, (obj["sx"] / 2, obj["sy"] / 2, obj["sz"] / 2), "cabinet")]
    if kind == "wet_patch":
        scale = min(obj["sx"], obj["sy"])
        return [("cylinder", (ox * obj["sx"], oy * obj["sy"], WET_PATCH_THICK_M / 2), NO_TURN, (r * scale, WET_PATCH_THICK_M / 2), "wet") for ox, oy, r in PUDDLE]
    if kind == "pipe":
        r, length, gap = obj["radius"], obj["length"], obj.get("clearance", 0.05)
        z = gap + r
        parts = [("capsule", (0.0, 0.0, z), ALONG_Y, (r, length / 2), "pipe_paint")]
        if r >= 0.03:
            parts += [("cylinder", (0.0, side * length * 0.3, z), ALONG_Y, (r * 1.5, 0.02), "flange") for side in (-1, 1)]
        if gap > 0.0 and z < 1.0:
            parts += [("box", (0.0, side * length * 0.42, z / 2), NO_TURN, (r * 0.9, 0.05, z / 2), "dark_steel") for side in (-1, 1)]
        return parts
    if kind == "cable_tray":
        length, width, height = obj["length"], obj.get("width", 0.3), obj.get("height", 0.08)
        parts = [("box", (side * width / 2, 0.0, height / 2), NO_TURN, (0.004, length / 2, height / 2), "galvanised") for side in (-1, 1)]
        rungs = max(2, int(length / 0.3))
        parts += [("box", (0.0, -length / 2 + (i + 0.5) * length / rungs, 0.008), NO_TURN, (width / 2, 0.012, 0.008), "galvanised") for i in range(rungs)]
        parts += [("capsule", (off * width, 0.0, 0.03), ALONG_Y, (0.013, length / 2 - 0.02), "rubber") for off in (-0.25, 0.0, 0.25)]
        return parts
    if kind == "valve":
        r = obj.get("size", 0.08)
        z = r * 1.6
        top = z + r * 3.2
        return [
            ("box", (0.0, 0.0, z / 4), NO_TURN, (r * 1.5, r * 2.2, z / 4), "dark_steel"),
            ("capsule", (0.0, 0.0, z), ALONG_Y, (r * 0.8, r * 1.4), "valve_body"),
            ("cylinder", (0.0, r * 1.7, z), ALONG_Y, (r * 1.45, r * 0.18), "flange"),
            ("cylinder", (0.0, -r * 1.7, z), ALONG_Y, (r * 1.45, r * 0.18), "flange"),
            ("cylinder", (0.0, 0.0, z + r * 1.1), NO_TURN, (r * 0.75, r * 1.1), "valve_body"),
            ("cylinder", (0.0, 0.0, top - r * 0.7), NO_TURN, (r * 0.16, r * 0.9), "steel"),
            ("cylinder", (0.0, 0.0, top + r * 0.2), NO_TURN, (r * 1.4, r * 0.1), "handwheel"),
        ]
    if kind == "ramp":
        length, height, width, landing = obj["length"], obj["height"], obj["width"], obj.get("landing", 1.0)
        slope = math.atan2(height, length)
        thick = height / math.cos(slope) + 0.02
        half = (math.hypot(length, height) / 2, width / 2, thick / 2)
        cz = height / 2 - math.cos(slope) * thick / 2
        shift = math.sin(slope) * thick / 2
        return [
            ("box", (length / 2 + shift, 0.0, cz), _axis_quat((0.0, 1.0, 0.0), -slope), half, "plate"),
            ("box", (length + landing / 2, 0.0, height / 2), NO_TURN, (landing / 2, width / 2, height / 2), "plate"),
            ("box", (length + landing + length / 2 - shift, 0.0, cz), _axis_quat((0.0, 1.0, 0.0), slope), half, "plate"),
        ]
    if kind == "steps":
        count, depth, rise, width, landing = obj.get("count", 3), obj["depth"], obj["rise"], obj["width"], obj.get("landing", 1.0)
        parts = []
        far = 2 * depth * count + landing
        for i in range(count):
            top = rise * (i + 1)
            half = (depth / 2, width / 2, top / 2)
            parts.append(("box", (depth * (i + 0.5), 0.0, top / 2), NO_TURN, half, "plate"))
            parts.append(("box", (far - depth * (i + 0.5), 0.0, top / 2), NO_TURN, half, "plate"))
        top = rise * count
        parts.append(("box", (depth * count + landing / 2, 0.0, top / 2), NO_TURN, (landing / 2, width / 2, top / 2), "plate"))
        rail_z = top + 0.9
        for side in (-1, 1):
            y = side * (width / 2 - 0.03)
            parts.append(("box", (far / 2, y, rail_z), NO_TURN, (far / 2, 0.02, 0.02), "galvanised"))
            for lx in (0.03, depth * count, far - depth * count, far - 0.03):
                parts.append(("box", (lx, y, rail_z / 2), NO_TURN, (0.02, 0.02, rail_z / 2), "galvanised"))
        return parts
    pitch, bar = obj.get("pitch", 0.15), obj.get("bar_height", 0.02)
    count = math.floor((obj["length"] - GRATING_BAR_WIDTH_M) / pitch) + 1
    return [("box", (GRATING_BAR_WIDTH_M / 2 + pitch * i, 0.0, bar / 2), NO_TURN, (GRATING_BAR_WIDTH_M / 2, obj["width"] / 2, bar / 2), "galvanised") for i in range(count)]


def primitives(world):
    """Every physical solid, in world axes. Plain JSON data, read by the model loader and sent in the replay."""
    out = []
    for obj in world["objects"]:
        c, s = _cos_sin(obj)
        yaw = _axis_quat((0.0, 0.0, 1.0), math.radians(obj.get("yaw_deg", 0.0)))
        for i, (shape, centre, quat, size, material) in enumerate(_object_parts(obj)):
            out.append({
                "name": f"{obj['name']}_{i}", "object": obj["name"], "type": shape,
                "pos": [obj["x"] + c * centre[0] - s * centre[1], obj["y"] + s * centre[0] + c * centre[1], centre[2]],
                "quat": list(_quat_mul(yaw, quat)), "size": list(size), "friction": obj.get("friction", 0.05 if obj["kind"] == "wet_patch" else world["floor"]["friction"]),
                "material": material, "colour": list(MATERIALS[material]),
            })
    return out


def _segment(x0, y0, x1, y1):
    """Centre, half length and yaw quaternion of a straight run."""
    dx, dy = x1 - x0, y1 - y0
    return ((x0 + x1) / 2, (y0 + y1) / 2), max(math.hypot(dx, dy) / 2, 0.01), _axis_quat((0.0, 0.0, 1.0), math.atan2(dy, dx))


def _prim(shape, pos, quat, size, material):
    return {"type": shape, "pos": list(pos), "quat": list(quat), "size": list(size), "material": material, "colour": list(MATERIALS[material]), "picture_only": True}


def _along(centre, half, quat, offset, z):
    """A point on a run: offset metres along it, at height z, from its centre."""
    c, s = 1.0 - 2.0 * quat[2] * quat[2], 2.0 * quat[2] * quat[3]
    return (centre[0] + c * offset, centre[1] + s * offset, z)


ALONG_X = _axis_quat((0.0, 1.0, 0.0), math.pi / 2)


def _wall_parts(o):
    h = o.get("height", 7.0)
    centre, half, q = _segment(o["x0"], o["y0"], o["x1"], o["y1"])
    if o["x0"] == o["x1"]:
        # Newton's raytracer returns noisy normals on a thin box turned by 90 degrees, so a wall along y stays unturned.
        return [_prim("box", (*centre, 0.6), NO_TURN, (0.14, half, 0.6), "concrete"), _prim("box", (*centre, h / 2 + 0.6), NO_TURN, (0.08, half, h / 2 - 0.6), "cladding")]
    return [_prim("box", (*centre, 0.6), q, (half, 0.14, 0.6), "concrete"), _prim("box", (*centre, h / 2 + 0.6), q, (half, 0.08, h / 2 - 0.6), "cladding")]


def _tank_parts(o):
    r, h, x, y = o["radius"], o.get("height", 3.5), o["x"], o["y"]
    legs = min(0.6, h * 0.2)
    body = h - legs
    shell_half = max(body / 2 - r, 0.01)
    z = legs + body / 2
    parts = [_prim("capsule", (x, y, z), NO_TURN, (r, shell_half), "tank")]
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        parts.append(_prim("box", (x + dx * r * 0.7, y + dy * r * 0.7, legs / 2 + 0.1), NO_TURN, (0.06, 0.06, legs / 2 + 0.1), "dark_steel"))
    for level in (-0.6, 0.0, 0.6):
        parts.append(_prim("cylinder", (x, y, z + level * shell_half), NO_TURN, (r + 0.012, 0.03), "flange"))
    # A ladder and a nozzle on the side that faces the walkway.
    ladder_y = y - r - 0.12
    for side in (-0.2, 0.2):
        parts.append(_prim("box", (x + side, ladder_y, legs + body / 2), NO_TURN, (0.015, 0.015, body / 2), "galvanised"))
    for i in range(int(body / 0.3)):
        parts.append(_prim("box", (x, ladder_y, legs + 0.2 + i * 0.3), NO_TURN, (0.2, 0.012, 0.012), "galvanised"))
    nozzle = (x + r * 0.8, y - r * 0.8, legs + body * 0.35)
    parts.append(_prim("cylinder", nozzle, _quat_mul(_axis_quat((0.0, 0.0, 1.0), math.radians(45.0)), ALONG_X), (0.07, 0.25), "steel"))
    parts.append(_prim("cylinder", (nozzle[0] + 0.18, nozzle[1] - 0.18, nozzle[2]), _quat_mul(_axis_quat((0.0, 0.0, 1.0), math.radians(45.0)), ALONG_X), (0.12, 0.02), "flange"))
    return parts


def _pipe_rack_parts(o):
    centre, half, q = _segment(o["x0"], o["y0"], o["x1"], o["y1"])
    z = o["height"]
    pipe_q = _quat_mul(q, ALONG_X)
    parts = []
    for j, (offset, r, material) in enumerate(((-0.42, 0.11, "clad_pipe"), (0.0, 0.07, "pipe_paint"), (0.34, 0.05, "steel"))):
        side = _quat_mul(q, (0.0, 0.0, 0.0, 1.0))
        c, s = 1.0 - 2.0 * side[2] * side[2], 2.0 * side[2] * side[3]
        cx, cy = centre[0] - s * offset, centre[1] + c * offset
        parts.append(_prim("cylinder", (cx, cy, z), pipe_q, (r, half), material))
        for k in range(int(half // 2.0) + 1):
            for sign in (-1, 1):
                parts.append(_prim("cylinder", _along((cx, cy), half, q, sign * (k * 2.0 + 0.7 + j * 0.3), z), pipe_q, (r * 1.45, 0.018), "flange"))
    for k in range(int(half // 2.5) + 1):
        for sign in (-1, 1):
            point = _along(centre, half, q, sign * k * 2.5, z - 0.16)
            parts.append(_prim("box", point, q, (0.03, 0.55, 0.02), "dark_steel"))
            for off in (-0.5, 0.5):
                c, s = 1.0 - 2.0 * q[2] * q[2], 2.0 * q[2] * q[3]
                parts.append(_prim("box", (point[0] - s * off, point[1] + c * off, z + 1.5), q, (0.012, 0.012, 1.66), "dark_steel"))
    return parts


def _railing_parts(o):
    centre, half, q = _segment(o["x0"], o["y0"], o["x1"], o["y1"])
    parts = [_prim("box", (*centre, 1.08), q, (half, 0.022, 0.022), "galvanised"), _prim("box", (*centre, 0.58), q, (half, 0.015, 0.015), "galvanised"), _prim("box", (*centre, 0.05), q, (half, 0.005, 0.05), "steel")]
    count = int(2 * half / 1.5) + 1
    for i in range(count + 1):
        parts.append(_prim("box", _along(centre, half, q, -half + i * 2 * half / count, 0.55), q, (0.022, 0.022, 0.55), "galvanised"))
    return parts


def _column_parts(o):
    h = o["height"]
    return [_prim("box", (o["x"], o["y"], h / 2), NO_TURN, (0.014, 0.15, h / 2), "column"), _prim("box", (o["x"] - 0.15, o["y"], h / 2), NO_TURN, (0.012, 0.15, h / 2), "column"),
            _prim("box", (o["x"] + 0.15, o["y"], h / 2), NO_TURN, (0.012, 0.15, h / 2), "column"), _prim("box", (o["x"], o["y"], 0.02), NO_TURN, (0.26, 0.26, 0.02), "dark_steel")]


def _beam_parts(o):
    centre, half, q = _segment(o["x0"], o["y0"], o["x1"], o["y1"])
    return [_prim("box", (*centre, o["height"]), q, (half, 0.09, 0.22), "column")]


def _light_parts(o):
    x, y, z = o["x"], o["y"], o["height"]
    return [_prim("cylinder", (x, y, z), NO_TURN, (0.22, 0.05), "lamp"), _prim("cylinder", (x, y, z + 0.13), NO_TURN, (0.26, 0.08), "dark_steel"), _prim("box", (x, y, z + 1.0), NO_TURN, (0.01, 0.01, 0.85), "dark_steel")]


def _floor_line_parts(o):
    centre, half, q = _segment(o["x0"], o["y0"], o["x1"], o["y1"])
    return [_prim("box", (*centre, 0.001), q, (half, 0.05, 0.001), "line")]


def _gauge_parts(o):
    x, y = o["x"], o["y"]
    return [_prim("box", (x, y, 0.6), NO_TURN, (0.025, 0.025, 0.6), "steel"), _prim("cylinder", (x, y - 0.05, 1.2), ALONG_Y, (0.09, 0.025), "flange"), _prim("cylinder", (x, y - 0.077, 1.2), ALONG_Y, (0.075, 0.003), "gauge")]


def _pump_parts(o):
    a = math.radians(o.get("yaw_deg", 0.0))
    q = _axis_quat((0.0, 0.0, 1.0), a)
    axis = _quat_mul(q, ALONG_X)
    c, s = math.cos(a), math.sin(a)

    def at(along, z):
        return (o["x"] + c * along, o["y"] + s * along, z)
    return [_prim("box", at(0.0, 0.08), q, (0.8, 0.3, 0.08), "dark_steel"), _prim("cylinder", at(-0.35, 0.42), axis, (0.2, 0.36), "motor"), _prim("box", at(0.08, 0.32), q, (0.07, 0.1, 0.1), "flange"),
            _prim("capsule", at(0.42, 0.4), NO_TURN, (0.18, 0.04), "valve_body"), _prim("cylinder", at(0.42, 0.75), NO_TURN, (0.05, 0.2), "pipe_paint"), _prim("cylinder", at(0.42, 0.65), NO_TURN, (0.09, 0.015), "flange")]


SCENERY_PARTS = {"wall": _wall_parts, "tank": _tank_parts, "pipe_rack": _pipe_rack_parts, "railing": _railing_parts, "column": _column_parts, "beam": _beam_parts, "light": _light_parts, "floor_line": _floor_line_parts, "gauge": _gauge_parts, "pump": _pump_parts}


def scenery_primitives(world):
    """Picture-only solids, for the picture and the replay. The physics model never reads this."""
    out = []
    for obj in world["scenery"]:
        for i, prim in enumerate(SCENERY_PARTS[obj["kind"]](obj)):
            out.append({"name": f"{obj['name']}_{i}", "object": obj["name"], **prim})
    return out


def lights(world):
    return [[o["x"], o["y"], o["height"] - 0.2] for o in world["scenery"] if o["kind"] == "light"]


def surface_height(world, x, y):
    """Height of the walkable surface under a point, for the fall check. Pipes do not count: nothing stands on them."""
    top = 0.0
    for obj in world["objects"]:
        if obj["kind"] in ("pipe", "cable_tray", "valve"):
            continue
        c, s = _cos_sin(obj)
        lx = c * (x - obj["x"]) + s * (y - obj["y"])
        ly = -s * (x - obj["x"]) + c * (y - obj["y"])
        x0, x1, hy = _local_extent(obj)
        if abs(ly) > hy or not x0 <= lx <= x1:
            continue
        kind = obj["kind"]
        if kind == "box":
            top = max(top, obj["sz"])
        elif kind == "wet_patch":
            top = max(top, WET_PATCH_THICK_M)
        elif kind == "grating":
            top = max(top, obj.get("bar_height", 0.02))
        elif kind == "ramp":
            along = min(lx, x1 - lx)
            top = max(top, obj["height"] * min(along / obj["length"], 1.0))
        else:
            along = min(lx, x1 - lx)
            top = max(top, obj["rise"] * min(math.floor(along / obj["depth"]) + 1, obj.get("count", 3)))
    return top
