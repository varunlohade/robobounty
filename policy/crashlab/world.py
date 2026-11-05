"""World spec schema v2 and BDDL writer. Standard library only, so a bad file dies before the sim starts.

{
  "schema": 2,
  "arena": "kitchen",                       token from ARENAS
  "style": "base",                          token from the arena's styles (optional)
  "seed": 1,                                integer, 0 to 2^31-1
  "fixtures": [{"type": "flat_stove", "region": [x0, y0, x1, y1], "yaw": [a, b], "state": "on"}],   yaw, state optional
  "objects": [{"type": "plate", "region": [x0, y0, x1, y1], "yaw": [a, b]}],                        yaw optional
  "goal": {"predicate": "on", "object": "akita_black_bowl_1", "target": "plate_1", "part": "contain_region"},
  "light": 1.0,                             scale on all lights, 0.2-2.0 (optional)
  "clutter": [{"x": 0.1, "y": 0.1, "yaw": 0.0, "half_size": 0.02, "rgb": [0.2, 0.6, 0.2]}]
}
surface_z values were measured by settling a box in each arena.
Regions are metres relative to the arena's workspace centre. Instances are named type_1, type_2 in listing order.
Goals use only names from that listing. There is no text field: instruction() builds the words from tables below.
An out-of-range value is rejected, not clamped. The LLM cannot widen a range by asking for more.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from scene import _fields, _reject_constant, _reject_duplicates, SceneError

MAX_FILE_BYTES = 16_384
MAX_SEED = 2**31 - 1
MAX_FIXTURES, MAX_OBJECTS, MAX_CLUTTER = 4, 8, 3
MIN_REGION_M, MAX_REGION_M = 0.01, 0.40  # MuJoCo refuses a zero-size region site
MAX_INSTRUCTION = 120
RANGES = {
    "yaw": (-math.pi, math.pi),
    "light": (0.2, 2.0),
    "rgb": (0.0, 1.0),
    "half_size": (0.01, 0.05),
}

ARENAS = {
    "tabletop": {"problem": "LIBERO_Tabletop_Manipulation", "workspace": "main_table", "fixture": "table",
                 "x": (-0.45, 0.30), "y": (-0.40, 0.40), "surface_z": 0.90,
                 "styles": {"base": "libero_tabletop_base_style", "blue": "libero_tabletop_blue_style",
                            "warm": "libero_tabletop_warm_style"}},
    "kitchen": {"problem": "LIBERO_Kitchen_Tabletop_Manipulation", "workspace": "kitchen_table", "fixture": "kitchen_table",
                "x": (-0.45, 0.30), "y": (-0.40, 0.40), "surface_z": 0.90,
                "styles": {"base": "libero_kitchen_tabletop_base_style"}},
    "living_room": {"problem": "LIBERO_Living_Room_Tabletop_Manipulation", "workspace": "living_room_table",
                    "fixture": "living_room_table", "x": (-0.30, 0.25), "y": (-0.38, 0.38), "surface_z": 0.4367, "fixtures": False,
                    "styles": {"base": "libero_living_room_tabletop_base_style"}},
    "study": {"problem": "LIBERO_Study_Tabletop_Manipulation", "workspace": "study_table", "fixture": "study_table",
              "x": (-0.28, 0.25), "y": (-0.30, 0.30), "surface_z": 0.8851,
              "styles": {"base": "libero_study_base_style"}},
    "coffee_table": {"problem": "LIBERO_Coffee_Table_Manipulation", "workspace": "coffee_table", "fixture": "coffee_table",
                     "x": (-0.25, 0.25), "y": (-0.35, 0.40), "surface_z": 0.4239, "fixtures": False,
                     "styles": {"base": "libero_coffee_table_base_style", "blue": "libero_coffee_table_blue_style",
                                "warm": "libero_coffee_table_warm_style"}},
    "floor": {"problem": "LIBERO_Floor_Manipulation", "workspace": "floor", "fixture": "floor",
              "x": (-0.25, 0.20), "y": (-0.30, 0.30), "surface_z": 0.0, "fixtures": False,
              "styles": {"base": "libero_floor_base_style", "blue": "libero_floor_blue_style",
                         "warm": "libero_floor_warm_style", "coffee": "libero_floor_coffee_style"}},
}

# Words are what instruction() may say. Parts are the named sites each asset carries.
MOVABLE = {
    "akita_black_bowl": "black bowl",
    "alphabet_soup": "alphabet soup",
    "basket": "basket",
    "bbq_sauce": "bbq sauce",
    "black_book": "black book",
    "butter": "butter",
    "chefmate_8_frypan": "frying pan",
    "chocolate_pudding": "chocolate pudding",
    "cookies": "cookies",
    "cream_cheese": "cream cheese",
    "glazed_rim_porcelain_ramekin": "ramekin",
    "ketchup": "ketchup",
    "macaroni_and_cheese": "macaroni and cheese",
    "milk": "milk",
    "moka_pot": "moka pot",
    "new_salad_dressing": "salad dressing",
    "orange_juice": "orange juice",
    "plate": "plate",
    "popcorn": "popcorn",
    "porcelain_mug": "white mug",
    "red_coffee_mug": "red mug",
    "salad_dressing": "salad dressing",
    "tomato_sauce": "tomato sauce",
    "white_bowl": "white bowl",
    "white_yellow_mug": "yellow and white mug",
    "wine_bottle": "wine bottle",
    "wooden_tray": "tray",
    "yellow_book": "yellow book",
}
FIXED = {
    "desk_caddy": "caddy",
    "flat_stove": "stove",
    "microwave": "microwave",
    "white_cabinet": "cabinet",
    "wine_rack": "wine rack",
    "wooden_cabinet": "cabinet",
    "wooden_two_layer_shelf": "shelf",
}
DRAWERS = {"top_region": "top drawer", "middle_region": "middle drawer", "bottom_region": "bottom drawer"}
# part -> (predicate it serves, words after the verb)
PARTS = {
    "basket": {"contain_region": ("in", "the basket")},
    "wooden_tray": {"contain_region": ("in", "the tray")},
    "desk_caddy": {f"{s}_contain_region": ("in", f"the {s} compartment of the caddy") for s in ("back", "front", "left", "right")},
    "flat_stove": {"cook_region": ("on", "the stove")},
    "microwave": {"heating_region": ("in", "the microwave"), "top_side": ("on", "top of the microwave")},
    "wine_rack": {"top_region": ("on", "the wine rack")},
    "wooden_two_layer_shelf": {"top_region": ("in", "the top of the shelf"), "bottom_region": ("in", "the bottom of the shelf"),
                               "top_side": ("on", "top of the shelf")},
    "wooden_cabinet": {**{p: ("in", f"the {w} of the cabinet") for p, w in DRAWERS.items()}, "top_side": ("on", "top of the cabinet")},
    "white_cabinet": {**{p: ("in", f"the {w} of the cabinet") for p, w in DRAWERS.items()}, "top_side": ("on", "top of the cabinet")},
}
PLACE_ON = {"plate", "akita_black_bowl", "white_bowl"}  # movable targets stock tasks stack on
# Fixture start states: token -> (BDDL predicate, part or None).
STATES = {
    "wooden_cabinet": {f"open_{p.split('_')[0]}": ("Open", p) for p in DRAWERS},
    "white_cabinet": {f"open_{p.split('_')[0]}": ("Open", p) for p in DRAWERS},
    "microwave": {"open": ("Open", None), "closed": ("Close", None)},
    "flat_stove": {"on": ("Turnon", None), "off": ("Turnoff", None)},
}
PREDICATES = {"on": "On", "in": "In", "open": "Open", "close": "Close", "turnon": "Turnon", "turnoff": "Turnoff"}
BINARY = {"on", "in"}
SAFE_BDDL = re.compile(r"[A-Za-z0-9_ :.()\n-]+")
SAFE_INSTRUCTION = re.compile(r"[a-z0-9 ]+")


class WorldError(SceneError):
    pass


def _token(value, name, allowed):
    if type(value) is not str or value not in allowed:
        raise WorldError(f"{name}: unknown token")
    return value


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorldError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _number(value, name, low, high):
    if type(value) not in (int, float):
        raise WorldError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise WorldError(f"{name} must be finite")
    if not low <= value <= high:
        raise WorldError(f"{name}={value} out of range [{low}, {high}]")
    return value + 0.0


def _numbers(value, name, length, low, high):
    if not isinstance(value, list) or len(value) != length:
        raise WorldError(f"{name} must be a list of {length} numbers")
    return [_number(v, f"{name}[{i}]", low, high) for i, v in enumerate(value)]


def _region(value, name, arena):
    if not isinstance(value, list) or len(value) != 4:
        raise WorldError(f"{name} must be [x0, y0, x1, y1]")
    x0, x1 = (_number(value[i], f"{name}[{i}]", *arena["x"]) for i in (0, 2))
    y0, y1 = (_number(value[i], f"{name}[{i}]", *arena["y"]) for i in (1, 3))
    if not all(MIN_REGION_M - 1e-9 <= side <= MAX_REGION_M for side in (x1 - x0, y1 - y0)):
        raise WorldError(f"{name}: each side must span {MIN_REGION_M} to {MAX_REGION_M} m, low value first")
    return [x0, y0, x1, y1]


def _yaw(value, name):
    low, high = _numbers(value, name, 2, *RANGES["yaw"])
    if low > high:
        raise WorldError(f"{name}: low value first")
    return [low, high]


def _list(raw, name, max_len):
    if not isinstance(raw, list) or len(raw) > max_len:
        raise WorldError(f"{name} must be a list of at most {max_len}")
    return raw


def _name_instances(entries):
    """Adds type_1, type_2 in listing order. The name comes from the token, never from the spec."""
    counts = {}
    for e in entries:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        e["name"] = f"{e['type']}_{counts[e['type']]}"


def _check_unique_word(name, types):
    if sum(_word(t) == _word(types[name]) for t in types.values()) > 1:
        raise WorldError("the template cannot tell two look-alike objects apart")


def _goal(raw, world):
    _fields(raw, "goal", {"predicate", "object"}, {"target", "part"})
    predicate = _token(raw["predicate"], "goal.predicate", PREDICATES)
    types = {e["name"]: e["type"] for e in world["objects"] + world["fixtures"]}
    subject = _token(raw["object"], "goal.object", types)
    goal = {"predicate": predicate, "object": subject}
    _check_unique_word(subject, types)

    if predicate in BINARY:
        if subject not in {e["name"] for e in world["objects"]}:
            raise WorldError("goal.object must be a movable object")
        if "target" not in raw:
            raise WorldError("goal.target missing")
        target = _token(raw["target"], "goal.target", types)
        if target == subject:
            raise WorldError("goal.target must differ from goal.object")
        goal["target"] = target
        parts = PARTS.get(types[target], {})
        if "part" in raw:
            part = _token(raw["part"], "goal.part", parts)
            if parts[part][0] != predicate:
                raise WorldError("goal.part does not serve this predicate")
            goal["part"] = part
        elif predicate != "on" or types[target] not in PLACE_ON:
            raise WorldError("goal.part missing")
        _check_unique_word(target, types)
        return goal

    if "target" in raw:
        raise WorldError("this predicate takes no goal.target")
    state = next(e.get("state") for e in world["fixtures"] + world["objects"] if e["name"] == subject)
    if predicate in ("turnon", "turnoff"):
        if types[subject] != "flat_stove" or "part" in raw:
            raise WorldError("this predicate works only on a whole stove")
        if (predicate == "turnoff") != (state == "on"):
            raise WorldError("this goal already holds at the start")
        return goal
    if types[subject] == "microwave":
        if "part" in raw:
            raise WorldError("a microwave has no drawer parts")
        if (predicate == "close") != (state == "open"):
            raise WorldError("this goal already holds at the start")
        return goal
    if types[subject] not in ("wooden_cabinet", "white_cabinet"):
        raise WorldError("this predicate needs a cabinet or a microwave")
    part = _token(raw.get("part"), "goal.part", DRAWERS)
    is_open = state == f"open_{part.split('_')[0]}"
    if (predicate == "close") != is_open:
        raise WorldError("this goal already holds at the start")
    goal["part"] = part
    return goal


def validate(raw):
    _fields(raw, "world", {"schema", "arena", "seed", "objects", "goal"}, {"style", "fixtures", "light", "clutter"})
    if type(raw["schema"]) is not int or raw["schema"] != 2:
        raise WorldError("schema must be 2")
    arena_name = _token(raw["arena"], "arena", ARENAS)
    arena = ARENAS[arena_name]
    world = {
        "schema": 2,
        "arena": arena_name,
        "style": _token(raw.get("style", "base"), "style", arena["styles"]),
        "seed": _integer(raw["seed"], "seed", 0, MAX_SEED),
        "light": _number(raw.get("light", 1.0), "light", *RANGES["light"]),
    }

    # Stock tasks place no fixture in these arenas, so LIBERO's fixture height there is unproven.
    fixture_cap = MAX_FIXTURES if arena.get("fixtures", True) else 0
    fixtures = []
    for i, e in enumerate(_list(raw.get("fixtures", []), "fixtures", fixture_cap)):
        n = f"fixtures[{i}]"
        _fields(e, n, {"type", "region"}, {"yaw", "state"})
        kind = _token(e["type"], f"{n}.type", FIXED)
        item = {"type": kind, "region": _region(e["region"], f"{n}.region", arena),
                "yaw": _yaw(e.get("yaw", [0.0, 0.0]), f"{n}.yaw")}
        if "state" in e:
            item["state"] = _token(e["state"], f"{n}.state", STATES.get(kind, {}))
        fixtures.append(item)
    _name_instances(fixtures)
    world["fixtures"] = fixtures

    objects = []
    for i, e in enumerate(_list(raw["objects"], "objects", MAX_OBJECTS)):
        n = f"objects[{i}]"
        _fields(e, n, {"type", "region"}, {"yaw"})
        objects.append({"type": _token(e["type"], f"{n}.type", MOVABLE),
                        "region": _region(e["region"], f"{n}.region", arena),
                        "yaw": _yaw(e.get("yaw", [0.0, 0.0]), f"{n}.yaw")})
    if not objects:
        raise WorldError("objects must not be empty")
    _name_instances(objects)
    world["objects"] = objects

    clutter = []
    for i, e in enumerate(_list(raw.get("clutter", []), "clutter", MAX_CLUTTER)):
        n = f"clutter[{i}]"
        _fields(e, n, {"x", "y", "half_size"}, {"yaw", "rgb"})
        clutter.append({
            "x": _number(e["x"], f"{n}.x", *arena["x"]),
            "y": _number(e["y"], f"{n}.y", *arena["y"]),
            "yaw": _number(e.get("yaw", 0.0), f"{n}.yaw", *RANGES["yaw"]),
            "half_size": _number(e["half_size"], f"{n}.half_size", *RANGES["half_size"]),
            "rgb": _numbers(e.get("rgb", [0.5, 0.5, 0.5]), f"{n}.rgb", 3, *RANGES["rgb"]),
        })
    world["clutter"] = clutter

    if not isinstance(raw["goal"], dict):
        raise WorldError("goal must be an object")
    world["goal"] = _goal(raw["goal"], world)
    instruction(world)
    return world


def parse(text):
    """Strict parse: rejects NaN, Infinity, 1e999, duplicate keys and absurdly long integers."""
    if len(text) > MAX_FILE_BYTES:
        raise WorldError(f"world file over {MAX_FILE_BYTES} bytes")
    try:
        raw = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_reject_duplicates)
    except (ValueError, RecursionError) as e:
        raise WorldError(f"not valid JSON: {e}") from e
    return validate(raw)


def load(path):
    data = Path(path).read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise WorldError(f"world file over {MAX_FILE_BYTES} bytes")
    try:
        return parse(data.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise WorldError("world file is not UTF-8") from e


def canonical(world):
    return json.dumps(world, sort_keys=True, separators=(",", ":"), allow_nan=False)


def world_hash(world):
    return hashlib.sha256(canonical(world).encode()).hexdigest()


def _word(kind):
    return MOVABLE.get(kind) or FIXED[kind]


def _kind(name):
    return name.rsplit("_", 1)[0]


def instruction(world):
    """The only source of task words. Every word comes from the tables above."""
    g = world["goal"]
    subject = _word(_kind(g["object"]))
    predicate = g["predicate"]
    if predicate == "on":
        if "part" in g:
            where = PARTS[_kind(g["target"])][g["part"]][1]
        else:
            where = f"the {_word(_kind(g['target']))}"
        text = f"put the {subject} on {where}"
    elif predicate == "in":
        where = PARTS[_kind(g["target"])][g["part"]][1]
        text = f"pick up the {subject} and place it in {where}"
    elif predicate in ("open", "close"):
        where = f"{DRAWERS[g['part']]} of the {subject}" if "part" in g else subject
        text = f"{predicate} the {where}"
    else:
        text = f"turn {predicate[4:]} the {subject}"
    if len(text) > MAX_INSTRUCTION or not SAFE_INSTRUCTION.fullmatch(text):
        raise WorldError("instruction failed the template check")
    return text


def _fmt(x):
    return format(x, ".6f")


def _goal_atom(g):
    predicate = PREDICATES[g["predicate"]]
    if g["predicate"] in BINARY:
        target = f"{g['target']}_{g['part']}" if "part" in g else g["target"]
        return f"({predicate} {g['object']} {target})"
    target = f"{g['object']}_{g['part']}" if "part" in g else g["object"]
    return f"({predicate} {target})"


def write_bddl(world):
    """Emits BDDL from validated values only. Never writes yaw_rotation, because bddl_utils.py:36 evals it.
    Yaw goes into the sim as numbers in build_world.py. Regions here only satisfy LIBERO's first placement."""
    arena = ARENAS[world["arena"]]
    workspace = arena["workspace"]
    placed = world["fixtures"] + world["objects"]
    lines = [f"(define (problem {arena['problem']})", "  (:domain robosuite)", f"  (:language {instruction(world)})", "  (:regions"]
    for e in placed:
        x0, y0, x1, y1 = e["region"]
        lines += [f"    ({e['name']}_init_region", f"      (:target {workspace})",
                  f"      (:ranges (({_fmt(x0)} {_fmt(y0)} {_fmt(x1)} {_fmt(y1)})))", "    )"]
    for e in placed:
        for part in PARTS.get(e["type"], {}):
            lines += [f"    ({part}", f"      (:target {e['name']})", "    )"]
    lines += ["  )", "  (:fixtures", f"    {workspace} - {arena['fixture']}"]
    lines += [f"    {e['name']} - {e['type']}" for e in world["fixtures"]]
    lines += ["  )", "  (:objects"]
    lines += [f"    {e['name']} - {e['type']}" for e in world["objects"]]
    g = world["goal"]
    interest = [g["object"]] + ([g["target"]] if "target" in g else [])
    lines += ["  )", "  (:obj_of_interest"] + [f"    {n}" for n in interest] + ["  )", "  (:init"]
    lines += [f"    (On {e['name']} {workspace}_{e['name']}_init_region)" for e in placed]
    for e in world["fixtures"]:
        if "state" in e:
            predicate, part = STATES[e["type"]][e["state"]]
            lines.append(f"    ({predicate} {e['name']}_{part})" if part else f"    ({predicate} {e['name']})")
    lines += ["  )", "  (:goal", f"    (And {_goal_atom(g)})", "  )", ")", ""]
    text = "\n".join(lines)
    if not SAFE_BDDL.fullmatch(text) or "yaw_rotation" in text:
        raise WorldError("BDDL failed the output check")
    return text
