"""LIBERO world schema for brief.py: the plan picks tokens and numeric ranges, and our code places everything.

Zones are fixed table entries. Left and right are as seen by the main camera, where +y is on the right.
Robot base positions and table sizes were measured with one env per arena (2026-11-06).
"""
import hashlib
import json
import math
import random
from pathlib import Path

import world as w
from world import WorldError

BASE_X = {"tabletop": -0.66, "kitchen": -0.66, "living_room": -0.51, "study": -0.55, "coffee_table": -0.51, "floor": -0.60}
REACH_LIMIT_M, NEAR_LIMIT_M = 0.75, 0.25  # geometry guess for a Panda working down at base height, never tested in motion
USABLE_Y_M = 0.36  # past this the main camera crops a bowl at mid-table
ZONES = {  # u along the robot-to-far axis, v along left-to-right, both as fractions of the usable area
    "anywhere": (0.15, 1.0, 0.0, 1.0),
    "center": (0.40, 0.80, 0.35, 0.65),
    "near_robot": (0.15, 0.40, 0.25, 0.75),
    "far": (0.75, 1.0, 0.25, 0.75),
    "left": (0.30, 0.85, 0.05, 0.28),
    "right": (0.30, 0.85, 0.72, 0.95),
    "edge_left": (0.30, 0.85, 0.0, 0.07),
    "edge_right": (0.30, 0.85, 0.93, 1.0),
    "edge_robot_side": (0.0, 0.08, 0.20, 0.80),
}
ROLES = ("plain", "blocker", "beside_object")
FACTORS = ("arena", "style", "light", "goal", "goal_object", "goal_target", "placement", "blocker", "required_object",
           "fixture", "fixture_state", "clutter")
MAX_ARENAS, MAX_GOALS, MAX_REQUIRED, MAX_PLAN_FIXTURES, MAX_POOL = 3, 3, 4, 2, 12
SIZE_M = {"plate": 0.11, "chefmate_8_frypan": 0.13, "basket": 0.12, "wooden_tray": 0.13, "akita_black_bowl": 0.08, "white_bowl": 0.08,
          "black_book": 0.09, "yellow_book": 0.09, "wooden_cabinet": 0.20, "white_cabinet": 0.20, "microwave": 0.18,
          "flat_stove": 0.16, "wine_rack": 0.15, "wooden_two_layer_shelf": 0.20, "desk_caddy": 0.10}
DEFAULT_SIZE_M = 0.05
GAP_M = 0.012
PART_TOKENS = sorted({p for parts in w.PARTS.values() for p in parts} | set(w.DRAWERS))
STATE_TOKENS = sorted({s for states in w.STATES.values() for s in states})
LIMITS = [
    "Edge means the schema's arena bound. On tabletop and kitchen the robot-side bound is 5 cm from the real table edge. "
    "The left and right bounds are 20 cm from it, because the main camera does not see further.",
    "likely_out_of_reach and too_close_to_base are geometry guesses. No arm moved.",
    "Whether a goal judges properly in motion is unknown. No policy ran.",
    "When a brief names no task, the planner picks the goal. The mapped list then has no goal entry.",
]


def plan_schema():
    def tokens(allowed, extra=()):
        return {"type": "string", "enum": sorted(allowed) + list(extra)}

    def many(item, cap):
        return {"type": "array", "maxItems": cap, "items": item}

    def obj(**props):
        return {"type": "object", "additionalProperties": False, "required": sorted(props), "properties": props}

    def bounds(low, high, kind="number"):
        return obj(min={"type": kind, "minimum": low, "maximum": high}, max={"type": kind, "minimum": low, "maximum": high})
    zones = many(tokens(ZONES), len(ZONES))
    items = sorted(w.MOVABLE) + sorted(w.FIXED)
    return obj(
        arenas=many(tokens(w.ARENAS), MAX_ARENAS),
        styles=many(tokens({s for a in w.ARENAS.values() for s in a["styles"]}), 4),
        goals=many(obj(predicate=tokens(w.PREDICATES), object_type=tokens(items), target_type=tokens(items, ["none"]),
                       part=tokens(PART_TOKENS, ["none"]), object_zones=zones, target_zones=zones), MAX_GOALS),
        required=many(obj(type=tokens(w.MOVABLE), role=tokens(ROLES), zones=zones), MAX_REQUIRED),
        fixtures=many(obj(type=tokens(w.FIXED), state=tokens(STATE_TOKENS, ["none"]), zones=zones), MAX_PLAN_FIXTURES),
        distractor_pool=many(tokens(w.MOVABLE), MAX_POOL),
        distractors=bounds(0, w.MAX_OBJECTS - 1, "integer"),
        distractor_zones=zones,
        boxes=bounds(0, w.MAX_CLUTTER, "integer"),
        light=bounds(*w.RANGES["light"]),
        yaw_spread=bounds(0.0, math.pi))


def catalog_text():
    arenas = ", ".join(f"{name} (styles: {', '.join(a['styles'])}{'; no fixtures' if not a.get('fixtures', True) else ''})"
                       for name, a in w.ARENAS.items())
    movable = ", ".join(f"{k} = {v}" for k, v in w.MOVABLE.items())
    fixed = ", ".join(f"{k} = {v}" for k, v in w.FIXED.items())
    parts = "; ".join(f"{k}: {', '.join(f'{p} ({v[0]})' for p, v in ps.items())}" for k, ps in w.PARTS.items())
    return f"""Catalog: one Panda arm on one table-like surface. A kitchen counter or worktop means the kitchen arena.
Arenas: {arenas}.
Movable objects: {movable}.
Fixtures: {fixed}.
Parts for goals, with the predicate each serves: {parts}.
A goal "on" with target plate, akita_black_bowl or white_bowl takes part "none". Open, close, turnon and turnoff work on a fixture \
and take target "none". Cabinet drawer goals need a drawer part.
Zones, as seen by the main camera: {', '.join(ZONES)}. Edge zones sit at the limit of the usable area. "edge_robot_side" is next to the \
real table edge and close to the arm base.
Roles for required objects: blocker sits on the straight line between the goal object and its target. beside_object sits next to the \
goal object. plain uses its zones. A thing "in the way" is a blocker.
The plan: goals lists what the arm must do (pick a simple goal if the brief names none). required lists objects the brief names beyond \
the goal. distractor_pool, distractors and distractor_zones add other objects, and boxes adds plain boxes. A cluttered scene has \
4 to 5 distractors and 1 to 3 boxes. Use light 0.8 to 1.2, one arena, base style, zone anywhere and yaw_spread up to 0.8 unless the brief says more.
At most {w.MAX_OBJECTS} movable objects and {w.MAX_CLUTTER} boxes fit in one world. Light has limits {w.RANGES['light']}. \
There is nothing else: no other robots, objects, rooms, people, fluids, weather, moved cameras, or light direction or colour."""


def vocabulary(factor):
    if factor not in ("goal_object", "goal_target", "required_object", "fixture"):
        return None
    words = {word for table in (w.MOVABLE, w.FIXED) for k, v in table.items() for word in (k.split("_") + v.split())}
    return words - {"and", "of", "the", "new", "8"}


def _exact(entry, keys):
    if not isinstance(entry, dict) or set(entry) != set(keys):
        raise WorldError("plan fields wrong")


def _tokens(raw, name, allowed, cap):
    if not isinstance(raw, list) or len(raw) > cap:
        raise WorldError(f"{name} list wrong")
    return [w._token(t, name, allowed) for t in raw]


def _bounds(raw, name, low, high, integer=False):
    _exact(raw, ("min", "max"))
    check = w._integer if integer else w._number
    a, b = check(raw["min"], name, low, high), check(raw["max"], name, low, high)
    if a > b:
        raise WorldError(f"{name} reversed")
    return {"min": a, "max": b}


def _goal_world(arena, goal):
    """Smallest spec that holds this goal, so a bad token pair dies here and not in the sim."""
    fixtures, objects = [], []
    for kind in (goal["object_type"], goal["target_type"]):
        if kind in w.FIXED:
            fixtures.append({"type": kind, "region": [0.0, 0.2, 0.01, 0.21]})
        elif kind in w.MOVABLE:
            objects.append({"type": kind, "region": [0.0, -0.2 + 0.1 * len(objects), 0.01, -0.19 + 0.1 * len(objects)]})
    if not objects:
        objects = [{"type": "plate", "region": [0.0, -0.2, 0.01, -0.19]}]
    if fixtures:
        state = _goal_state(goal)
        if state:
            fixtures[0]["state"] = state
    return {"schema": 2, "arena": arena, "seed": 1, "fixtures": fixtures, "objects": objects, "goal": _goal_atom(goal)}


def _goal_atom(goal):
    atom = {"predicate": goal["predicate"], "object": f"{goal['object_type']}_1"}
    if goal["target_type"] != "none":
        atom["target"] = f"{goal['target_type']}_1"
    if goal["part"] != "none":
        atom["part"] = goal["part"]
    return atom


def _goal_state(goal):
    p, kind = goal["predicate"], goal["object_type"]
    if p == "turnon":
        return "off"
    if p == "turnoff":
        return "on"
    if kind == "microwave":
        return {"open": "closed", "close": "open"}.get(p)
    if p == "close" and kind in ("wooden_cabinet", "white_cabinet") and goal["part"] in w.DRAWERS:
        return f"open_{goal['part'].split('_')[0]}"
    return None


def _pairs(plan):
    pairs = []
    for arena in plan["arenas"]:
        for goal in plan["goals"]:
            try:
                w.validate(_goal_world(arena, goal))
                pairs.append((arena, goal))
            except WorldError:
                pass
    return pairs


def validate_plan(raw, mapped):
    _exact(raw, ("arenas", "styles", "goals", "required", "fixtures", "distractor_pool", "distractors",
                 "distractor_zones", "boxes", "light", "yaw_spread"))
    items = {*w.MOVABLE, *w.FIXED}
    plan = {"arenas": _tokens(raw["arenas"], "arenas", w.ARENAS, MAX_ARENAS),
            "styles": _tokens(raw["styles"], "styles", {s for a in w.ARENAS.values() for s in a["styles"]}, 4),
            "distractor_pool": _tokens(raw["distractor_pool"], "pool", w.MOVABLE, MAX_POOL),
            "distractors": _bounds(raw["distractors"], "distractors", 0, w.MAX_OBJECTS - 1, integer=True),
            "distractor_zones": _tokens(raw["distractor_zones"], "zones", ZONES, len(ZONES)),
            "boxes": _bounds(raw["boxes"], "boxes", 0, w.MAX_CLUTTER, integer=True),
            "light": _bounds(raw["light"], "light", *w.RANGES["light"]),
            "yaw_spread": _bounds(raw["yaw_spread"], "yaw", 0.0, math.pi)}
    if not isinstance(raw["goals"], list) or not 1 <= len(raw["goals"]) <= MAX_GOALS:
        raise WorldError("goals list wrong")
    plan["goals"] = []
    for g in raw["goals"]:
        _exact(g, ("predicate", "object_type", "target_type", "part", "object_zones", "target_zones"))
        plan["goals"].append({"predicate": w._token(g["predicate"], "predicate", w.PREDICATES),
                              "object_type": w._token(g["object_type"], "object", items),
                              "target_type": w._token(g["target_type"], "target", items | {"none"}),
                              "part": w._token(g["part"], "part", {*PART_TOKENS, "none"}),
                              "object_zones": _tokens(g["object_zones"], "zones", ZONES, len(ZONES)),
                              "target_zones": _tokens(g["target_zones"], "zones", ZONES, len(ZONES))})
    if not isinstance(raw["required"], list) or len(raw["required"]) > MAX_REQUIRED:
        raise WorldError("required list wrong")
    plan["required"] = []
    for r in raw["required"]:
        _exact(r, ("type", "role", "zones"))
        plan["required"].append({"type": w._token(r["type"], "type", w.MOVABLE), "role": w._token(r["role"], "role", ROLES),
                                 "zones": _tokens(r["zones"], "zones", ZONES, len(ZONES))})
    if not isinstance(raw["fixtures"], list) or len(raw["fixtures"]) > MAX_PLAN_FIXTURES:
        raise WorldError("fixtures list wrong")
    plan["fixtures"] = []
    for f in raw["fixtures"]:
        _exact(f, ("type", "state", "zones"))
        plan["fixtures"].append({"type": w._token(f["type"], "type", w.FIXED), "state": w._token(f["state"], "state", {*STATE_TOKENS, "none"}),
                                 "zones": _tokens(f["zones"], "zones", ZONES, len(ZONES))})
    if not _pairs(plan):
        raise WorldError("no arena can hold any goal")
    return plan


def unbacked(plan, factor):
    """A factor the planner cited but the plan does not hold, so the mapping would be a pretence."""
    return {"blocker": not any(r["role"] == "blocker" for r in plan["required"]),
            "required_object": not plan["required"],
            "fixture": not plan["fixtures"] and not any(k in w.FIXED for g in plan["goals"] for k in (g["object_type"], g["target_type"])),
            "clutter": plan["distractors"]["max"] == 0 and plan["boxes"]["max"] == 0}.get(factor, False)


def _size(kind):
    return SIZE_M.get(kind, DEFAULT_SIZE_M)


def _area(arena):
    a = w.ARENAS[arena]
    x0, x1 = a["x"][0], min(a["x"][1], BASE_X[arena] + REACH_LIMIT_M - 0.03)
    y0, y1 = max(a["y"][0], -USABLE_Y_M), min(a["y"][1], USABLE_Y_M)
    return x0, x1, y0, y1


def zone_box(arena, zone):
    x0, x1, y0, y1 = _area(arena)
    u0, u1, v0, v1 = ZONES[zone]
    return x0 + (x1 - x0) * u0, x0 + (x1 - x0) * u1, y0 + (y1 - y0) * v0, y0 + (y1 - y0) * v1


class _Layout:
    def __init__(self, rng, arena):
        self.rng, self.arena, self.placed = rng, arena, []

    def fits(self, x, y, r):
        return all(math.dist((x, y), (px, py)) >= r + pr + GAP_M for px, py, pr in self.placed)

    def add(self, x, y, r):
        self.placed.append((x, y, r))
        return x, y

    def in_zones(self, zones, r, far_from=None, min_gap=0.0):
        for _ in range(60):
            x0, x1, y0, y1 = zone_box(self.arena, self.rng.choice(zones or ["anywhere"]))
            x, y = self.rng.uniform(x0, x1), self.rng.uniform(y0, y1)
            if self.fits(x, y, r) and (far_from is None or math.dist((x, y), far_from) >= min_gap):
                return self.add(x, y, r)
        return None


def _region(xy, arena):
    a = w.ARENAS[arena]
    half = w.MIN_REGION_M / 2
    x = min(max(xy[0], a["x"][0] + half), a["x"][1] - half)
    y = min(max(xy[1], a["y"][0] + half), a["y"][1] - half)
    return [round(x - half, 5), round(y - half, 5), round(x + half, 5), round(y + half, 5)]


def _sample(plan, pairs, rng):
    arena, goal = rng.choice(pairs)
    layout = _Layout(rng, arena)
    styles = [s for s in plan["styles"] if s in w.ARENAS[arena]["styles"]] or ["base"]
    spread = rng.uniform(plan["yaw_spread"]["min"], plan["yaw_spread"]["max"])
    spec = {"schema": 2, "arena": arena, "style": rng.choice(styles), "seed": rng.randrange(w.MAX_SEED),
            "light": round(rng.uniform(plan["light"]["min"], plan["light"]["max"]), 4),
            "fixtures": [], "objects": [], "clutter": [], "goal": _goal_atom(goal)}
    meta = {"arena": arena, "object_zones": goal["object_zones"], "target_zones": goal["target_zones"], "blockers": []}
    fail = WorldError("no room in this layout")

    def add_object(kind, xy):
        spec["objects"].append({"type": kind, "region": _region(xy, arena), "yaw": [round(-spread, 4), round(spread, 4)]})

    def add_fixture(kind, zones, state):
        xy = layout.in_zones(zones, _size(kind))
        if xy is None:
            raise fail
        item = {"type": kind, "region": _region(xy, arena), "yaw": [-0.1, 0.1]}
        if state:
            item["state"] = state
        spec["fixtures"].append(item)
        return xy

    if goal["object_type"] in w.FIXED:
        subject_xy = add_fixture(goal["object_type"], goal["object_zones"], _goal_state(goal))
    else:
        subject_xy = None
    if goal["target_type"] in w.FIXED:
        target_xy = add_fixture(goal["target_type"], goal["target_zones"], None)
    else:
        target_xy = None
    goal_kinds = {goal["object_type"], goal["target_type"]}
    if w.ARENAS[arena].get("fixtures", True):
        for f in plan["fixtures"]:
            if f["type"] not in goal_kinds and f["type"] not in [e["type"] for e in spec["fixtures"]]:
                state = f["state"] if f["state"] in w.STATES.get(f["type"], {}) else None
                add_fixture(f["type"], f["zones"], state)

    blockers = [r for r in plan["required"] if r["role"] == "blocker"]
    need = sum(2 * _size(r["type"]) for r in blockers) + GAP_M * (len(blockers) + 1)
    if goal["object_type"] in w.MOVABLE:
        subject_xy = layout.in_zones(goal["object_zones"], _size(goal["object_type"]))
        if subject_xy is None:
            raise fail
        add_object(goal["object_type"], subject_xy)
    if goal["target_type"] in w.MOVABLE:
        gap = _size(goal["object_type"]) + _size(goal["target_type"]) + need
        target_xy = layout.in_zones(goal["target_zones"], _size(goal["target_type"]), subject_xy, gap)
        if target_xy is None:
            raise fail
        add_object(goal["target_type"], target_xy)
    words = {w._word(k) for k in goal_kinds if k != "none"}

    for r in plan["required"]:
        kind, size = r["type"], _size(r["type"])
        if w._word(kind) in words or kind in [e["type"] for e in spec["objects"]]:
            continue
        xy = None
        if r["role"] == "blocker" and target_xy is not None:
            t = rng.uniform(0.42, 0.58)
            x, y = subject_xy[0] + (target_xy[0] - subject_xy[0]) * t, subject_xy[1] + (target_xy[1] - subject_xy[1]) * t
            if layout.fits(x, y, size):
                xy = layout.add(x, y, size)
                meta["blockers"].append(kind)
        elif r["role"] == "beside_object" and subject_xy is not None:
            for _ in range(30):
                angle = rng.uniform(-math.pi, math.pi)
                reach = _size(goal["object_type"]) + size + GAP_M + 0.01
                x, y = subject_xy[0] + reach * math.cos(angle), subject_xy[1] + reach * math.sin(angle)
                x0, x1, y0, y1 = _area(arena)
                if x0 <= x <= x1 and y0 <= y <= y1 and layout.fits(x, y, size):
                    xy = layout.add(x, y, size)
                    break
        else:
            xy = layout.in_zones(r["zones"], size)
        if xy is None:
            raise fail
        add_object(kind, xy)

    used_words = words | {w._word(e["type"]) for e in spec["objects"]}
    pool = [k for k in plan["distractor_pool"] if w._word(k) not in used_words]
    rng.shuffle(pool)
    count = rng.randint(plan["distractors"]["min"], plan["distractors"]["max"])
    for kind in pool:
        if count <= 0 or len(spec["objects"]) >= w.MAX_OBJECTS:
            break
        xy = layout.in_zones(plan["distractor_zones"], _size(kind))
        if xy is not None and w._word(kind) not in {w._word(e["type"]) for e in spec["objects"]}:
            add_object(kind, xy)
            count -= 1
    for _ in range(rng.randint(plan["boxes"]["min"], plan["boxes"]["max"])):
        half = round(rng.uniform(0.015, 0.03), 4)
        xy = layout.in_zones(plan["distractor_zones"], half * 1.5)
        if xy is not None:
            spec["clutter"].append({"x": round(xy[0], 5), "y": round(xy[1], 5), "half_size": half,
                                    "yaw": round(rng.uniform(-1.5, 1.5), 4), "rgb": [round(rng.random(), 3) for _ in range(3)]})
    return spec, meta


def expand(plan, seed):
    pairs = _pairs(plan)
    index = 0
    while True:
        rng = random.Random(f"{seed}/{index}")
        index += 1
        try:
            yield _sample(plan, pairs, rng)
        except WorldError:
            yield None, None


def _in_frame(np, sim, point, margin=0.47):
    cam = sim.model.camera_name2id("agentview")
    v = sim.data.cam_xmat[cam].reshape(3, 3).T @ (np.array(point) - sim.data.cam_xpos[cam])
    if v[2] >= 0:
        return False
    focal = 0.5 / math.tan(math.radians(float(sim.model.cam_fovy[cam])) / 2)
    return abs(focal * v[0] / -v[2]) < margin and abs(focal * v[1] / -v[2]) < margin


def _point_to_segment(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    t = ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / max((bx - ax) ** 2 + (by - ay) ** 2, 1e-9)
    t = max(0.0, min(1.0, t))
    return math.dist(p, (ax + t * (bx - ax), ay + t * (by - ay))), t


def _facts(builder, world, meta, result):
    """Numbers measured from the settled sim, for flags and for the reflected summary."""
    np, inner = builder.np, builder.inner
    sim = inner.sim
    ox, oy = inner.workspace_offset[:2]
    base = inner.robots[0].base_pos

    def position(name):
        if name in result["objects"]:
            return result["objects"][name]["pos"]
        return [result["layout"][name]["xy"][0], result["layout"][name]["xy"][1], result["layout"][name]["z"]]
    goal = world["goal"]
    names = [goal["object"]] + ([goal["target"]] if "target" in goal else [])
    reach = {n: math.dist(position(n)[:2], base[:2]) for n in names}
    frame = {n: bool(_in_frame(np, sim, position(n))) for n in names}
    subject = position(goal["object"])
    sx, sy = subject[0] - ox, subject[1] - oy
    in_zone = any(x0 - 0.02 <= sx <= x1 + 0.02 and y0 - 0.02 <= sy <= y1 + 0.02
                  for x0, x1, y0, y1 in (zone_box(meta["arena"], z) for z in (meta["object_zones"] or ["anywhere"])))
    a = w.ARENAS[meta["arena"]]
    facts = {"reach_m": {n: round(d, 3) for n, d in reach.items()},
             "likely_out_of_reach": sorted(n for n, d in reach.items() if d > REACH_LIMIT_M),
             "too_close_to_base": sorted(n for n, d in reach.items() if d < NEAR_LIMIT_M),
             "in_main_camera": frame, "object_in_planned_zone": in_zone,
             "object_margin_to_arena_bound_m": round(min(sx - a["x"][0], a["x"][1] - sx, sy - a["y"][0], a["y"][1] - sy), 3),
             "movable_count": len(world["objects"]), "box_count": len(world["clutter"])}
    if "target" in goal and meta["blockers"]:
        target = position(goal["target"])
        off = [_point_to_segment(position(f"{k}_1")[:2], subject[:2], target[:2]) for k in meta["blockers"]]
        facts["blocker_off_line_m"] = round(max(d for d, _ in off), 3)
        facts["blocker_between"] = all(0.15 < t < 0.85 for _, t in off)
    return facts


def open_builder(out):
    import build_world
    folder = Path(out) / "worlds"
    folder.mkdir(parents=True, exist_ok=True)
    image_size = 360  # sim.IMAGE_SIZE: the size the policy sees, not Builder's 128 default

    def build(item, index):
        spec, meta = item
        if spec is None:
            return None, "no_room_at_sampling"
        world = w.validate(spec)
        bddl = build_world._bddl_path(world, folder)
        builder = None
        try:
            builder = build_world.Builder(world, bddl, image_size)
            _, result = builder.prepare()
            if not result["valid"]:
                bddl.unlink(missing_ok=True)
                return None, "failed_settle_check"
            facts = _facts(builder, world, meta, result)
            if not all(facts["in_main_camera"].values()):
                bddl.unlink(missing_ok=True)
                return None, "goal_outside_main_camera"
            stem = str(folder / f"{index:03d}_{world['arena']}")
            stills = builder.still(stem)
        except Exception as e:  # LIBERO's first placement can raise on a crowded spec
            bddl.unlink(missing_ok=True)
            return None, f"build_failed_{type(e).__name__}"
        finally:
            if builder is not None:
                builder.close()
        spec_path = folder / f"{index:03d}_{world['arena']}.json"
        spec_path.write_text(json.dumps(spec, indent=1, sort_keys=True, allow_nan=False))
        return {"spec": str(spec_path), "world_hash": w.world_hash(world), "arena": world["arena"], "seed": world["seed"],
                "instruction": w.instruction(world), "bddl": str(bddl),
                "bddl_sha256": hashlib.sha256(bddl.read_bytes()).hexdigest(), "stills": stills, "attempts": result["attempts"],
                **facts}, None
    return build


def _contact_sheet(worlds, out):
    from PIL import Image, ImageDraw
    if not worlds:
        return None
    cell, cols = 300, 6
    rows = math.ceil(len(worlds) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), "white")
    pen = ImageDraw.Draw(sheet)
    for i, report in enumerate(worlds):
        x, y = (i % cols) * cell, (i // cols) * (cell + 30)
        with Image.open(report["stills"][0]) as still:
            sheet.paste(still.convert("RGB").resize((cell, cell)), (x, y))
        flag = " REACH?" if report["likely_out_of_reach"] or report["too_close_to_base"] else ""
        pen.text((x + 3, y + cell + 2), f"{i} {report['arena']} n={report['movable_count']}+{report['box_count']}{flag}", fill="black")
        pen.text((x + 3, y + cell + 15), report["instruction"][:46], fill="black")
    path = Path(out) / "contact_sheet.png"
    sheet.save(path)
    return str(path)


def finish(worlds, plan, out):
    n = len(worlds)
    summary = {"worlds": n, "contact_sheet": _contact_sheet(worlds, out)}
    if not n:
        return summary
    summary.update(
        object_in_planned_zone=sum(r["object_in_planned_zone"] for r in worlds),
        mean_movable=round(sum(r["movable_count"] for r in worlds) / n, 2),
        mean_boxes=round(sum(r["box_count"] for r in worlds) / n, 2),
        object_margin_to_arena_bound_m=[min(r["object_margin_to_arena_bound_m"] for r in worlds),
                                        max(r["object_margin_to_arena_bound_m"] for r in worlds)],
        blocker_between=sum(r.get("blocker_between", False) for r in worlds),
        likely_out_of_reach=sum(bool(r["likely_out_of_reach"]) for r in worlds),
        too_close_to_base=sum(bool(r["too_close_to_base"]) for r in worlds))
    print(json.dumps(summary, sort_keys=True))
    return summary
