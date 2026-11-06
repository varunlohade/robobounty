"""The typed functions that edit a v5 world. Function names and arguments are untrusted.

call(state, fn, args) checks the arguments, builds a new world and never changes the old one. It returns
{"result", "rerun", "data", "state"}. The result is "ok", "picture only, no re-run" or "cannot_build:<code>".
A code comes from CODES, so no text from the call reaches the result. The physics hash decides ok or picture only.

Floor joints: world.panes.height_m is the one value that compile5 and sim5 read for joint spacing. set_tower floor_m
writes tower.floor_m and panes.height_m. set_panes h writes panes.height_m only, for a pane shorter than a floor.
The later call wins.

Groups live in the engine state and not in the world file, because the v5 schema has no field for them.
"""
import copy

import compile5 as C
import scene5 as E
import world5 as W

OK = "ok"
PICTURE = "picture only, no re-run"
MAX_HISTORY = 64
MAX_GROUPS = 32
MAX_REPEAT = 50
MAX_DELTA_M = 300.0

CODES = frozenset({
    "bad_args", "bad_name", "bad_shape", "fixed_by_kind", "glass_below_ground", "glass_wider_than_tower", "invalid_world",
    "name_taken", "no_glass_to_clean", "no_such_material", "no_such_object", "nothing_to_undo", "one_cradle_only", "out_of_range",
    "reserved_material", "setback_above_roof", "start_blocked", "start_not_on_glass", "too_many_geoms", "too_many_groups",
    "too_many_materials", "too_many_objects", "too_many_solids", "unknown_function",
})
LIMITS = {
    "cannot_build": ["curved glass", "fluids", "cloth", "moving machinery, except the cradle", "people"],
    "not_built_yet": ["add_part", "generate_object"],
    "caps": {"objects": W.MAX_OBJECTS, "solids": W.MAX_SOLIDS, "geoms": W.MAX_GEOMS, "materials": W.MAX_MATERIALS, "cradles": 1},
    "note": "Results are simulated with hand-built physics. The robot heading stays fixed.",
}
PLANNED_PARTS = ["crane", "antenna", "ac_unit", "billboard", "cradle_parked", "tree", "car"]

# Fragments of the fixed text in world5, in match order. A WorldError holds no input, but only the code leaves this file.
WORLD_ERRORS = (
    ("runs below the ground", "glass_below_ground"), ("wider than the tower", "glass_wider_than_tower"),
    ("start pose is not on glass", "start_not_on_glass"), ("blocks the start pose", "start_blocked"),
    ("setback must stay", "setback_above_roof"), ("more than one cradle", "one_cradle_only"),
    (f"more than {W.MAX_GEOMS} geoms", "too_many_geoms"), (f"more than {W.MAX_SOLIDS} solids", "too_many_solids"),
    (f"more than {W.MAX_OBJECTS} objects", "too_many_objects"), (f"more than {W.MAX_MATERIALS} materials", "too_many_materials"),
    ("names must be unique", "name_taken"), ("material is reserved", "reserved_material"), ("material does not exist", "no_such_material"),
    ("must sit at the fixed distance", "fixed_by_kind"), ("must be an unrotated box", "fixed_by_kind"), ("must be -1 or 1", "out_of_range"),
    ("is outside", "out_of_range"), ("no glass to clean", "no_glass_to_clean"),
)


class Refuse(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# Argument schemas are a small subset of JSON Schema, so the AI loop can pass them on as they are.
def _num(lo, hi):
    return {"type": "number", "minimum": lo, "maximum": hi}


def _int(lo, hi):
    return {"type": "integer", "minimum": lo, "maximum": hi}


def _rule(rule):
    kind, lo, hi = rule
    return _int(lo, hi) if kind == W.INT else _num(lo, hi)


NAME = {"type": "string", "pattern": W.NAME_RE.pattern}
BOOL = {"type": "boolean"}


def _vec(n, lo, hi):
    return {"type": "array", "items": _num(lo, hi), "minItems": n, "maxItems": n}


def _schema(props, required=(), some=False):
    schema = {"type": "object", "properties": props, "required": sorted(required), "additionalProperties": False}
    if some:
        schema["minProperties"] = 1
    return schema


def _block_schema(rules):
    return _schema({k: _rule(r) for k, r in rules.items()}, some=True)


def _check_value(rule, v):
    t = rule["type"]
    if t == "boolean":
        if not isinstance(v, bool):
            raise Refuse("bad_args")
        return v
    if t == "string":
        if not isinstance(v, str):
            raise Refuse("bad_args")
        if "enum" in rule:
            if v not in rule["enum"]:
                raise Refuse("bad_args")
        elif not W.NAME_RE.fullmatch(v):
            raise Refuse("bad_name")
        return v
    if t == "array":
        if not isinstance(v, list):
            raise Refuse("bad_args")
        if not rule["minItems"] <= len(v) <= rule["maxItems"]:
            raise Refuse("bad_args")
        return [_check_value(rule["items"], item) for item in v]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (t == "integer" and not isinstance(v, int)):
        raise Refuse("bad_args")
    if not rule["minimum"] <= v <= rule["maximum"]:  # exact for huge integers, and False for NaN
        raise Refuse("out_of_range")
    return int(v) if t == "integer" else float(v)


def check_args(schema, args):
    """A new dict of checked values, or Refuse. None means no arguments."""
    args = {} if args is None else args
    if not isinstance(args, dict):
        raise Refuse("bad_args")
    props = schema["properties"]
    if any(not isinstance(k, str) or k not in props for k in args):
        raise Refuse("bad_args")
    if any(k not in args for k in schema["required"]) or len(args) < schema.get("minProperties", 0):
        raise Refuse("bad_args")
    return {k: _check_value(props[k], v) for k, v in args.items()}


def _update(block, a, moves):
    for arg, field in moves.items():
        if arg in a:
            block[field] = a[arg]


def _name_free(w, groups, name):
    if any(o["name"] == name for o in w["objects"]) or name in groups:
        raise Refuse("name_taken")


def _material(w, name):
    if name not in w["materials"]:
        raise Refuse("no_such_material")
    return name


def _targets(w, groups, name):
    """Objects named directly or through a group, in world order."""
    wanted = set(groups.get(name, ())) or {name}
    found = [o for o in w["objects"] if o["name"] in wanted]
    if not found:
        raise Refuse("no_such_object")
    return found


# Each edit changes the copies it gets. _edit validates the copy and only then accepts it.
def set_tower(w, a, groups):
    _update(w["tower"], a, {"height": "height_m", "width": "width_m", "floor_m": "floor_m"})
    if "floor_m" in a:
        w["panes"]["height_m"] = a["floor_m"]


def set_panes(w, a, groups):
    _update(w["panes"], a, {"w": "width_m", "h": "height_m", "offx": "offset_x_m", "offz": "offset_z_m", "joint_depth": "joint_depth_m",
                            "joint_gap": "joint_gap_m", "skip": "skip_every"})


def set_work_area(w, a, groups):
    _update(w["area"], a, {"w": "width_m", "h": "height_m", "drop": "drop_below_roof_m", "margin": "margin_m"})


def _kind_adder(kind, material, fields, fixed=None):
    """fields maps the three box sides (w, out, h) to argument names. A side in `fixed` has one allowed size."""
    fixed = fixed or {}

    def add(w, a, groups):
        _name_free(w, groups, a["name"])
        size = [fixed[i] if i in fixed else a[fields[i]] for i in range(3)]
        props = {k: a[k] for k in W.KINDS[kind][1]}
        w["objects"].append({
            "name": a["name"], "kind": kind, "shape": "box", "size": size, "euler_deg": [0.0, 0.0, 0.0],
            "pos": {"x_m": a["x_m"], "below_top_m": a["below_top_m"], "out_m": W.KIND_BOXES[kind][3] + size[1] / 2},
            "material": _material(w, a.get("material", material)), "solid": W.KINDS[kind][0], "props": props})
    return add


def _kind_schema(kind, fields):
    boxes = W.KIND_BOXES[kind]
    props = {"name": NAME, "material": NAME, "x_m": _num(-6.0, 9.0), "below_top_m": _num(-3.0, 14.0)}
    for i, field in fields.items():
        props[field] = _num(*boxes[i])
    props.update({k: _rule(r) for k, r in W.KINDS[kind][1].items()})
    return _schema(props, set(props) - {"material"})


def set_corner(w, a, groups):
    if a.get("remove"):
        w["tower"]["corner"] = None
    else:
        w["tower"]["corner"] = {"x_m": a["x_m"], "side": a["side"]}


def set_setback(w, a, groups):
    if a.get("remove"):
        w["tower"]["setback"] = None
    else:
        w["tower"]["setback"] = {"above_top_m": a["above_top_m"], "depth_m": a["depth_m"]}


def _removable(rules):
    return _schema({**{k: _rule(r) for k, r in rules.items()}, "remove": BOOL}, some=True)


def _all_or_remove(fields):
    """A pre check: every field together, or remove=true alone."""
    def check(a):
        if set(a) != ({"remove"} if a.get("remove") else fields):
            raise Refuse("bad_args")
    return check


def add_object(w, a, groups):
    _name_free(w, groups, a["name"])
    if len(a["size"]) != W.SHAPES[a["shape"]]:
        raise Refuse("bad_shape")
    w["objects"].append({
        "name": a["name"], "kind": "object", "shape": a["shape"], "size": a["size"],
        "pos": {"x_m": a["x_m"], "below_top_m": a["below_top_m"], "out_m": a["out_m"]},
        "euler_deg": a.get("euler_deg", [0.0, 0.0, 0.0]), "material": _material(w, a.get("material", "concrete")), "solid": a["solid"], "props": {}})


def group(w, a, groups):
    _name_free(w, groups, a["name"])
    if len(groups) >= MAX_GROUPS:
        raise Refuse("too_many_groups")
    names = {o["name"] for o in w["objects"]}
    if any(m not in names for m in a["members"]):
        raise Refuse("no_such_object")
    groups[a["name"]] = sorted(set(a["members"]))


def repeat(w, a, groups):
    targets = _targets(w, groups, a["name"])
    if len(w["objects"]) + len(targets) * a["count"] > W.MAX_OBJECTS:
        raise Refuse("too_many_objects")
    for o in targets:
        for i in range(1, a["count"] + 1):
            name = f"{o['name']}_r{i}"
            if not W.NAME_RE.fullmatch(name):
                raise Refuse("bad_name")
            _name_free(w, groups, name)
            copy_of = copy.deepcopy(o)
            copy_of["name"] = name
            copy_of["pos"]["x_m"] += a.get("dx", 0.0) * i
            copy_of["pos"]["below_top_m"] += a.get("dbelow", 0.0) * i
            copy_of["pos"]["out_m"] += a.get("dout", 0.0) * i
            w["objects"].append(copy_of)
            if a["name"] in groups:
                groups[a["name"]].append(name)
    if a["name"] in groups:
        groups[a["name"]].sort()


def move_object(w, a, groups):
    for o in _targets(w, groups, a["name"]):
        o["pos"]["x_m"] += a.get("dx", 0.0)
        o["pos"]["below_top_m"] += a.get("dbelow", 0.0)
        o["pos"]["out_m"] += a.get("dout", 0.0)


def rotate_object(w, a, groups):
    """Adds degrees to each Euler angle. Group members turn about their own centres."""
    for o in _targets(w, groups, a["name"]):
        o["euler_deg"] = [((v + d + 180.0) % 360.0) - 180.0 for v, d in zip(o["euler_deg"], a["delta_deg"])]


def remove_object(w, a, groups):
    gone = {o["name"] for o in _targets(w, groups, a["name"])}
    w["objects"] = [o for o in w["objects"] if o["name"] not in gone]
    for key in list(groups):
        groups[key] = [m for m in groups[key] if m not in gone]
        if not groups[key]:
            del groups[key]


def set_material(w, a, groups):
    old = w["materials"].get(a["name"])
    if old is None and {"rgba", "roughness", "metal"} - set(a):
        raise Refuse("no_such_material")
    w["materials"][a["name"]] = {**(old or {}), **{k: a[k] for k in ("rgba", "roughness", "metal") if k in a}}


def assign_material(w, a, groups):
    _material(w, a["material"])
    for o in _targets(w, groups, a["name"]):
        o["material"] = a["material"]


def _block_setter(block):
    def setter(w, a, groups):
        w[block].update(a)
    return setter


def set_dirt(w, a, groups):
    w["area"]["dirt_level"] = a["level"]


def set_light(w, a, groups):
    _update(w["light"], a, {"sun_level": "sun_level", "azimuth": "azimuth_deg", "haze": "haze"})
    _update(w["sky"], a, {"sky_top": "top", "sky_bottom": "bottom"})


def set_surroundings(w, a, groups):
    _update(w["surroundings"], a, {"city_seed": "city_seed", "density": "density", "radius": "radius_m"})


def read_world(state, a):
    world = copy.deepcopy(state["world"])
    return {"world": world, "effects": C.compile(world)[2], "groups": copy.deepcopy(state["groups"]), "physics_hash": state["physics_hash"]}


def read_result(state, a):
    return {"last_result": copy.deepcopy(state["last_result"])}


def list_parts(state, a):
    return {"parts": [], "planned": list(PLANNED_PARTS)}


def explain_limits(state, a):
    return copy.deepcopy(LIMITS)


def _registry():
    """name: args schema, rerun (yes, no or if_physics) and either an edit or a read. A pre check runs before the edit."""
    rows = {}

    def row(name, args, rerun, edit=None, read=None, pre=None):
        rows[name] = {"args": args, "rerun": rerun, "edit": edit, "read": read, "pre": pre}

    t, p, a = W.TOWER_FIELDS, W.BLOCKS["panes"], W.BLOCKS["area"]
    # A width edit moves no solid, so set_tower re-runs only when the physics hash says so.
    row("set_tower", _block_schema({"height": t["height_m"], "width": t["width_m"], "floor_m": t["floor_m"]}), "if_physics", set_tower)
    row("set_panes", _block_schema({"w": p["width_m"], "h": p["height_m"], "offx": p["offset_x_m"], "offz": p["offset_z_m"],
                                    "joint_depth": p["joint_depth_m"], "joint_gap": p["joint_gap_m"], "skip": p["skip_every"]}), "yes", set_panes)
    row("set_work_area", _block_schema({"w": a["width_m"], "h": a["height_m"], "drop": a["drop_below_roof_m"], "margin": a["margin_m"]}), "yes", set_work_area)
    kinds = {
        "ledge": ("concrete", {0: "width_m", 1: "depth_m", 2: "thick_m"}),
        "sill": ("concrete", {0: "width_m", 1: "depth_m", 2: "thick_m"}),
        "fin": ("alu", {0: "thick_m", 1: "depth_m", 2: "height_m"}),
        "sign": ("el_sign0", {0: "width_m", 1: "depth_m", 2: "height_m"}),
        "balcony": ("concrete", {0: "width_m", 1: "depth_m", 2: "slab_m"}),
        "vent": ("el_dark", {0: "width_m", 2: "height_m"}),
        "frame_step": ("alu", {0: "width_m", 1: "step_m", 2: "height_m"}),
        "wet_patch": ("el_wet", {0: "width_m", 2: "height_m"}),
        "dirt_patch": ("el_wet", {0: "width_m", 2: "height_m"}),
        "cradle": ("el_cradle", {0: "width_m", 2: "height_m"}),
    }
    for kind, (material, fields) in kinds.items():
        fixed = {1: W.KIND_BOXES[kind][1][0]} if 1 not in fields else None
        row(f"add_{kind}", _kind_schema(kind, fields), "yes", _kind_adder(kind, material, fields, fixed))
    row("set_corner", _removable(W.CORNER_FIELDS), "yes", set_corner, pre=_all_or_remove(set(W.CORNER_FIELDS)))
    row("set_setback", _removable(W.SETBACK_FIELDS), "yes", set_setback, pre=_all_or_remove(set(W.SETBACK_FIELDS)))
    pos = W.POS_FIELDS
    row("add_object", _schema({
        "name": NAME, "shape": {"type": "string", "enum": sorted(W.SHAPES)},
        "size": {"type": "array", "items": _num(*W.SIZE_RANGE), "minItems": 1, "maxItems": 3},
        "x_m": _rule(pos["x_m"]), "below_top_m": _rule(pos["below_top_m"]), "out_m": _rule(pos["out_m"]),
        "euler_deg": _vec(3, -180.0, 180.0), "material": NAME, "solid": BOOL,
    }, {"name", "shape", "size", "x_m", "below_top_m", "out_m", "solid"}), "if_physics", add_object)
    row("group", _schema({"name": NAME, "members": {"type": "array", "items": NAME, "minItems": 1, "maxItems": W.MAX_OBJECTS}}, {"name", "members"}), "if_physics", group)
    deltas = {"dx": _num(-MAX_DELTA_M, MAX_DELTA_M), "dbelow": _num(-MAX_DELTA_M, MAX_DELTA_M), "dout": _num(-MAX_DELTA_M, MAX_DELTA_M)}
    row("repeat", _schema({"name": NAME, "count": _int(1, MAX_REPEAT), **deltas}, {"name", "count"}), "if_physics", repeat)
    row("move_object", _schema({"name": NAME, **deltas}, {"name"}), "if_physics", move_object)
    row("rotate_object", _schema({"name": NAME, "delta_deg": _vec(3, -360.0, 360.0)}, {"name", "delta_deg"}), "if_physics", rotate_object)
    row("remove_object", _schema({"name": NAME}, {"name"}), "if_physics", remove_object)
    row("set_material", _schema({"name": NAME, "rgba": _vec(4, 0.0, 1.0), "roughness": _rule(W.MATERIAL_FIELDS["roughness"]),
                                 "metal": _rule(W.MATERIAL_FIELDS["metal"])}, {"name"}), "no", set_material)
    row("assign_material", _schema({"name": NAME, "material": NAME}, {"name", "material"}), "no", assign_material)
    for name, block in (("set_weather", "weather"), ("set_wind", "wind"), ("set_robot", "robot"), ("set_robot_start", "robot_start")):
        row(name, _block_schema(W.BLOCKS[block]), "yes", _block_setter(block))
    row("set_dirt", _schema({"level": _rule(a["dirt_level"])}, {"level"}), "yes", set_dirt)
    light, around = W.BLOCKS["light"], W.BLOCKS["surroundings"]
    row("set_light", _schema({"sun_level": _rule(light["sun_level"]), "azimuth": _rule(light["azimuth_deg"]), "haze": _rule(light["haze"]),
                              "sky_top": _vec(3, 0.0, 1.0), "sky_bottom": _vec(3, 0.0, 1.0)}, some=True), "no", set_light)
    row("set_surroundings", _schema({"city_seed": _rule(around["city_seed"]), "density": _rule(around["density"]), "radius": _rule(around["radius_m"])}, some=True), "no", set_surroundings)
    empty = _schema({})
    for name, read in (("read_world", read_world), ("read_result", read_result), ("list_parts", list_parts), ("explain_limits", explain_limits)):
        row(name, empty, "no", read=read)
    row("undo", empty, "no")
    return rows


REGISTRY = _registry()


def catalog():
    """The registry as plain JSON data, for the AI loop."""
    return [{"name": name, "args": copy.deepcopy(r["args"]), "rerun": r["rerun"]} for name, r in REGISTRY.items()]


def new_state(world):
    """Raises WorldError on a bad world. Only the code that loads a world file calls this."""
    world = W.validate(world)
    return {"world": world, "groups": {}, "history": (), "last_result": None, "physics_hash": C.physics_hash(world)}


def record_result(state, result):
    """A new state that holds the result of the run on this world, for read_result."""
    return {**state, "last_result": copy.deepcopy(result)}


def _world_code(error):
    text = str(error)
    for fragment, code in WORLD_ERRORS:
        if fragment in text:
            return code
    return "invalid_world"


def _reply(result, state, rerun=False, data=None):
    return {"result": result, "rerun": rerun, "data": data, "state": state}


def _edit(state, row, args):
    world, groups = copy.deepcopy(state["world"]), copy.deepcopy(state["groups"])
    row["edit"](world, args, groups)
    world = W.validate(world)
    if not E.clean_mask(world).any():
        raise Refuse("no_glass_to_clean")
    physics = C.physics_hash(world)
    changed = physics != state["physics_hash"]
    snapshot = {k: state[k] for k in ("world", "groups", "last_result", "physics_hash")}
    return {"world": world, "groups": groups, "history": (state["history"] + (snapshot,))[-MAX_HISTORY:],
            "last_result": None if changed else state["last_result"], "physics_hash": physics}, changed


def call(state, fn, args=None):
    if not isinstance(fn, str) or fn not in REGISTRY:
        return _reply("cannot_build:unknown_function", state)
    row = REGISTRY[fn]
    try:
        checked = check_args(row["args"], args)
        if row["read"]:
            return _reply(OK, state, data=row["read"](state, checked))
        if fn == "undo":
            if not state["history"]:
                raise Refuse("nothing_to_undo")
            # The result of the restored world comes back with it, so an undo needs no new run.
            return _reply(OK, {**state["history"][-1], "history": state["history"][:-1]})
        if row["pre"]:
            row["pre"](checked)
        new, changed = _edit(state, row, checked)
    except Refuse as e:
        return _reply(f"cannot_build:{e.code}", state)
    except W.WorldError as e:
        return _reply(f"cannot_build:{_world_code(e)}", state)
    return _reply(OK if changed else PICTURE, new, rerun=changed)
