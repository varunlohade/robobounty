"""Checks tasks 3 and 5 of docs/WORLD-PLAN.md. Run with policy/.venv/bin/python. Exit code 0 only if every check passes.

Part 1 calls every engine function with good and hostile arguments. Part 2 runs sim5 and compares it with the old sim.
"""
import copy
import json
import random
import sys
from pathlib import Path

import mujoco

HERE = Path(__file__).resolve().parent
OLD_DIR = HERE.parent / "highrise"
sys.path.insert(0, str(HERE))
sys.path.append(str(OLD_DIR))
import compile5 as C
import controller5
import engine5 as G
import run_trial5 as R5
import scene5 as E
import sim5 as S5
import world5 as W

failures = []
SEED = 0


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + str(detail) if detail != '' else ''}")
    if not ok:
        failures.append(label)


def nominal():
    return W.parse((OLD_DIR / "worlds" / "nominal.json").read_bytes())


def base_state():
    return G.new_state(nominal())


LEDGE = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 0.5, "depth_m": 0.05, "thick_m": 0.1}
FIN = {"x_m": 1.0, "below_top_m": 1.5, "thick_m": 0.1, "depth_m": 0.1, "height_m": 0.5}
SIGN = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 0.5, "depth_m": 0.05, "height_m": 0.3}
BALCONY = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 1.5, "depth_m": 0.8, "slab_m": 0.2}
STEP = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 0.5, "step_m": 0.02, "height_m": 0.5}
VENT = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 0.6, "height_m": 0.5, "open_frac": 0.5}
PATCH = {"x_m": 1.0, "below_top_m": 1.5, "width_m": 1.0, "height_m": 1.0}
CRADLE = {"x_m": 1.0, "below_top_m": 2.0, "width_m": 1.0, "height_m": 0.8, "travel_m": 1.0, "period_s": 30.0}
BOX = {"name": "box", "shape": "box", "size": [0.5, 0.05, 0.4], "x_m": 1.0, "below_top_m": 1.5, "out_m": 0.025, "solid": True}
SEEDED = [("add_object", BOX)]  # calls that need an object first

# Function: good calls. Each one changes something from the nominal world plus SEEDED.
GOOD = {
    "set_tower": [{"height": 170.0}, {"width": 60.0}, {"floor_m": 4.0}, {"height": 200.0, "width": 40.0, "floor_m": 3.0}],
    "set_panes": [{"w": 1.2}, {"h": 3.0}, {"offx": 0.3}, {"offz": 1.0}, {"joint_depth": 0.015}, {"joint_gap": 0.02}, {"skip": 2}],
    "set_work_area": [{"w": 2.0}, {"h": 2.5}, {"drop": 30.0}, {"margin": 0.5}],
    "add_ledge": [{"name": "n", **LEDGE}, {"name": "n", "material": "alu", **LEDGE}],
    "add_sill": [{"name": "n", **{**LEDGE, "depth_m": 0.03, "thick_m": 0.05}}],
    "add_fin": [{"name": "n", **FIN}],
    "add_sign": [{"name": "n", "material": "el_sign2", **SIGN}],
    "add_balcony": [{"name": "n", **BALCONY}],
    "add_vent": [{"name": "n", **VENT}],
    "add_frame_step": [{"name": "n", **STEP}],
    "add_wet_patch": [{"name": "n", "wetness": 0.9, **PATCH}],
    "add_dirt_patch": [{"name": "n", "level": 2.0, **PATCH}],
    "add_cradle": [{"name": "n", **CRADLE}],
    "set_corner": [{"x_m": 2.0, "side": 1}],
    "set_setback": [{"above_top_m": 0.8, "depth_m": 2.0}],
    "add_object": [
        {"name": "far", "shape": "box", "size": [1, 1, 200], "x_m": 1.0, "below_top_m": 40.0, "out_m": 5.0, "material": "alu", "solid": True},
        {"name": "cyl", "shape": "cyl", "size": [0.1, 0.5], "x_m": 1.0, "below_top_m": 2.0, "out_m": 0.1, "euler_deg": [90.0, 0.0, 0.0], "solid": True},
        {"name": "ball", "shape": "sphere", "size": [0.1], "x_m": 1.0, "below_top_m": 2.0, "out_m": 0.1, "solid": True},
        {"name": "cap", "shape": "capsule", "size": [0.05, 0.4], "x_m": 1.0, "below_top_m": 2.0, "out_m": 0.05, "solid": False}],
    "group": [{"name": "grp", "members": ["box", "ledge"]}],
    "repeat": [{"name": "box", "count": 3, "dx": 0.6, "dbelow": 0.1}, {"name": "ledge", "count": 1, "dbelow": 1.0}],
    "move_object": [{"name": "box", "dx": 0.5}, {"name": "box", "dout": 0.5}],
    "rotate_object": [{"name": "box", "delta_deg": [0.0, 30.0, 0.0]}],
    "remove_object": [{"name": "box"}, {"name": "ledge"}],
    "set_material": [{"name": "glass", "rgba": [0.1, 0.2, 0.3, 1.0]}, {"name": "new_paint", "rgba": [1.0, 0.0, 0.0, 1.0], "roughness": 0.3, "metal": 0.1}],
    "assign_material": [{"name": "box", "material": "cream"}],
    "add_part": [{"name": "part", "part": "ac_unit", "x_m": 1.0, "below_top_m": 2.0}, {"name": "part", "part": "crane", "x_m": 1.0}],
    "set_weather": [{"wetness": 0.5}, {"temperature_c": -5.0}, {"humidity_pct": 90.0}, {"dust_gm2": 20.0}],
    "set_wind": [{"steady_ms": 5.0}, {"gust_ms": 15.0}, {"gust_start_s": 10.0}, {"gust_duration_s": 20.0}, {"gust_count": 5}, {"gust_period_s": 40.0}, {"dir_deg": 90.0}],
    "set_robot": [{"suction_pa": 1500.0}, {"seal_leak_mm2": 800.0}, {"battery_start_frac": 0.5}, {"pad_force_n": 50.0}, {"clean_speed_ms": 0.2}],
    "set_dirt": [{"level": 1.5}],
    "set_robot_start": [{"x_m": 0.5}, {"above_top_m": 0.2}],
    "set_light": [{"sun_level": 0.3}, {"azimuth": 40.0}, {"haze": 0.9}, {"sky_top": [0.1, 0.1, 0.1]}, {"sky_bottom": [0.9, 0.9, 0.9]}, {"time": "night"}, {"fog": 1}],
    "set_surroundings": [{"city_seed": 7}, {"density": 0.5}, {"radius": 300.0}, {"city": "dubai"}],
    "set_look": [{"building": "#0a0a0a"}, {"glass_tint": "#1f5fbf"}, {"frames": "#f7f7f5"}, {"time": "dusk"}, {"fog": 2}, {"city": "dubai"}],
    "read_world": [{}], "read_result": [{}], "undo": [{}], "list_parts": [{}], "explain_limits": [{}],
}
PICTURE_ONLY = {"set_tower": [{"width": 60.0}], "add_object": [GOOD["add_object"][0], GOOD["add_object"][3]], "group": GOOD["group"], "set_look": GOOD["set_look"]}
READS = {"read_world", "read_result", "list_parts", "explain_limits", "undo"}


def seeded():
    state = base_state()
    for fn, args in SEEDED:
        out = G.call(state, fn, args)
        assert out["result"] == G.OK, out["result"]
        state = out["state"]
    return state


def outward(out):
    """What a caller sees of a reply, as text."""
    return json.dumps({k: v for k, v in out.items() if k != "state"}, default=str, allow_nan=True)


def part1_good():
    check("every function in the registry has a good call", set(GOOD) == set(G.REGISTRY), sorted(set(G.REGISTRY) ^ set(GOOD)))
    check("generate_object is not in the registry", "generate_object" not in G.REGISTRY)
    json.dumps(G.catalog())
    rows = G.catalog()
    check("the registry holds name, schema and re-run, as JSON", all(set(r) - {"note"} == {"name", "args", "rerun"} and r["rerun"] in ("yes", "no", "if_physics") for r in rows), f"{len(rows)} functions")
    start = seeded()
    calls = bad_results = 0
    problems = []
    for fn, cases in GOOD.items():
        if fn in READS:
            continue
        for args in cases:
            calls += 1
            before = copy.deepcopy(start["world"])
            given = copy.deepcopy(args)
            out = G.call(start, fn, args)
            where = f"{fn} {sorted(args)}"
            if start["world"] != before:
                problems.append(f"{where}: changed the old world")
            if args != given:
                problems.append(f"{where}: changed its arguments")
            if out["result"] not in (G.OK, G.PICTURE):
                bad_results += 1
                problems.append(f"{where}: {out['result']}")
                continue
            new = out["state"]
            physics_xml, view_xml, _ = C.compile(new["world"])
            mujoco.MjModel.from_xml_string(physics_xml)
            mujoco.MjModel.from_xml_string(view_xml)
            changed = C.physics_hash(new["world"]) != C.physics_hash(start["world"])
            if changed != (out["result"] == G.OK) or changed != out["rerun"]:
                problems.append(f"{where}: result does not fit the physics hash")
            rerun = G.REGISTRY[fn]["rerun"]
            picture = args in PICTURE_ONLY.get(fn, [])
            want = (rerun == "yes") or (rerun == "if_physics" and not picture)
            if changed != want:
                problems.append(f"{where}: registry says {rerun}, physics changed is {changed}")
            if new["world"] == start["world"] and fn != "group":
                problems.append(f"{where}: changed nothing in the world")
            undone = G.call(new, "undo")
            if undone["result"] != G.OK or undone["state"]["world"] != start["world"] or undone["state"]["physics_hash"] != start["physics_hash"]:
                problems.append(f"{where}: undo did not restore the world")
    check(f"{calls} good calls apply, recompile, load in MuJoCo, keep the old world and undo", not problems, problems[:12])
    for fn in sorted(READS - {"undo"}):
        out = G.call(start, fn, {})
        check(f"{fn} reads and changes nothing", out["result"] == G.OK and out["state"] is start and not out["rerun"] and out["data"] is not None)
    world_copy = G.call(start, "read_world")["data"]["world"]
    world_copy["tower"]["height_m"] = 1.0
    check("read_world gives a copy", start["world"]["tower"]["height_m"] != 1.0)

    limits = G.call(start, "explain_limits")["data"]["cannot_build"]
    text = " ".join(limits)
    check("explain_limits lists the five things", all(w in text for w in ("curved glass", "fluids", "cloth", "moving machinery", "people")), limits)

    # Picture and physics hash.
    picture = G.call(start, "set_material", {"name": "glass", "rgba": [1.0, 0.0, 0.0, 1.0]})
    check("a picture edit keeps the physics hash", picture["result"] == G.PICTURE and picture["state"]["physics_hash"] == start["physics_hash"])
    physics = G.call(start, "set_wind", {"steady_ms": 9.0})
    check("a physics edit changes the physics hash", physics["result"] == G.OK and physics["state"]["physics_hash"] != start["physics_hash"])

    # Floor joints.
    floor = G.call(start, "set_tower", {"floor_m": 4.0})["state"]["world"]
    zs = W.transom_zs(floor)
    gaps = {round(b - a, 6) for a, b in zip(zs, zs[1:])}
    check("set_tower floor_m sets panes.height_m and the compiled joint spacing", floor["tower"]["floor_m"] == 4.0 and floor["panes"]["height_m"] == 4.0 and gaps == {4.0}, gaps)
    pane = G.call(start, "set_panes", {"h": 2.5})["state"]["world"]
    zs = W.transom_zs(pane)
    gaps = {round(b - a, 6) for a, b in zip(zs, zs[1:])}
    check("set_panes h sets the spacing and leaves tower.floor_m", pane["tower"]["floor_m"] == start["world"]["tower"]["floor_m"] and gaps == {2.5}, gaps)

    for fn, args in (("set_corner", {"x_m": 2.0, "side": 1}), ("set_setback", {"above_top_m": 0.8, "depth_m": 2.0})):
        built = G.call(start, fn, args)["state"]
        removed = G.call(built, fn, {"remove": True})
        check(f"{fn} remove gives back the old physics hash", removed["result"] == G.OK and removed["state"]["physics_hash"] == start["physics_hash"], removed["result"])

    # Undo chain, result store and groups.
    s0 = G.record_result(base_state(), {"outcome": "pass"})
    s1 = G.call(s0, "set_wind", {"steady_ms": 9.0})["state"]
    s2 = G.call(s1, "set_material", {"name": "glass", "metal": 0.2})["state"]
    check("a physics edit clears the stored result", s1["last_result"] is None)
    u1 = G.call(s2, "undo")["state"]
    u0 = G.call(u1, "undo")["state"]
    check("undo walks back and brings the old result back", u1["world"] == s1["world"] and u0["world"] == s0["world"] and u0["last_result"] == {"outcome": "pass"})
    check("undo with no history refuses", G.call(u0, "undo")["result"] == "cannot_build:nothing_to_undo")
    long_state = start
    for i in range(G.MAX_HISTORY + 5):
        long_state = G.call(long_state, "set_light", {"haze": i / 100})["state"]
    check("history is capped", len(long_state["history"]) == G.MAX_HISTORY)
    grouped = G.call(start, "group", {"name": "grp", "members": ["box", "ledge"]})["state"]
    moved = G.call(grouped, "move_object", {"name": "grp", "dx": 0.1})["state"]
    deltas = {o["name"]: round(o["pos"]["x_m"] - p["pos"]["x_m"], 9) for o, p in zip(moved["world"]["objects"], grouped["world"]["objects"])}
    check("a group moves all its members", deltas == {"ledge": 0.1, "box": 0.1}, deltas)
    gone = G.call(grouped, "remove_object", {"name": "grp"})["state"]
    check("removing a group removes its members and the group", not gone["world"]["objects"] and not gone["groups"])
    many = G.call(grouped, "repeat", {"name": "grp", "count": 2, "dbelow": 3.0})
    check("a repeat of a group fits the fixed kinds", many["result"] == G.OK and set(many["state"]["groups"]["grp"]) == {"box", "ledge", "box_r1", "box_r2", "ledge_r1", "ledge_r2"}, many["result"])


HOSTILE_VALUES = [float("nan"), float("inf"), -float("inf"), True, 10 ** 400, -10 ** 400, 1e308, "../../etc/passwd", "<geom name='x'/>", "A" * 100000,
                  None, [], {}, [1] * 10000, {"$ref": "x"}, [[[]]], "__class__", "\x00"]
MARK = "ZZINJECTZZ"


def expect_refused(start, fn, args, problems):
    before = copy.deepcopy(start["world"])
    out = G.call(start, fn, args)
    res = out["result"]
    if not isinstance(res, str) or not res.startswith("cannot_build:") or res.split(":", 1)[1] not in G.CODES:
        problems.append(f"{fn}: accepted or bad code")
        return
    if out["state"] is not start or start["world"] != before or out["rerun"]:
        problems.append(f"{fn}: changed state on a refusal")
    if MARK in outward(out) or "passwd" in outward(out) or "geom" in outward(out):
        problems.append(f"{fn}: echoed input")


def part1_parts():
    """Each library part compiles and nothing in it floats, at every scale. A free object in the air refuses, and one on a mount does not."""
    from parts5 import PARTS
    start = seeded()
    bad = []
    for name in PARTS:
        for scale in (0.5, 1.0, 2.0):
            out = G.call(start, "add_part", {"name": "p", "part": name, "x_m": 3.0, "below_top_m": 2.0, "scale": scale})
            if out["result"].startswith("cannot_build"):
                bad.append((name, scale, out["result"]))
            else:
                C.compile(out["state"]["world"])
    check("every part at every scale builds with nothing floating", not bad, bad)
    air = G.call(start, "add_object", {"name": "air", "shape": "box", "size": [1.0, 1.0, 1.0], "x_m": 1.0, "below_top_m": 2.0, "out_m": 5.0, "solid": False})
    check("an object in the air is cannot_build:floating", air["result"] == "cannot_build:floating", air["result"])
    roof = W.area_rect(start["world"])["z1"] - start["world"]["tower"]["height_m"]
    high = G.call(start, "add_object", {"name": "high", "shape": "box", "size": [1.0, 1.0, 1.0], "x_m": 1.0, "below_top_m": roof - 3.0, "out_m": -3.0, "solid": False})
    check("an object above the roof and touching nothing is floating", high["result"] == "cannot_build:floating", high["result"])
    standing = G.call(start, "add_object", {"name": "pad", "shape": "box", "size": [1.0, 1.0, 1.0], "x_m": 1.0, "below_top_m": roof - 0.5, "out_m": -3.0, "solid": False})
    check("an object on the roof stands", not standing["result"].startswith("cannot_build"), standing["result"])
    on_pad = G.call(standing["state"], "add_object", {"name": "top", "shape": "box", "size": [1.0, 1.0, 1.0], "x_m": 1.0, "below_top_m": roof - 1.5, "out_m": -3.0, "solid": False})
    check("an object on a mount stands", not on_pad["result"].startswith("cannot_build"), on_pad["result"])
    gone = G.call(on_pad["state"], "remove_object", {"name": "pad"})
    check("removing the mount under an object refuses", gone["result"] == "cannot_build:floating", gone["result"])


def part1_hostile():
    start = seeded()
    problems = []
    for fn in (None, 5, [], {}, b"set_tower", "__class__", "generate_object", "exec", MARK + "<x/>", "set_tower ", "A" * 100000):
        try:
            expect_refused(start, fn, {}, problems)
        except TypeError:
            problems.append("a bad function name crashed the call")
    calls = 0
    for fn, row in G.REGISTRY.items():
        schema = row["args"]
        if schema["properties"]:
            good = GOOD[fn][0]
            for bad in ("x", 5, [], [1, 2], True, 1.5):
                calls += 1
                expect_refused(start, fn, bad, problems)
            calls += 1
            expect_refused(start, fn, {**good, MARK + "<geom/>": 1}, problems)
            expect_refused(start, fn, {**good, "__proto__": {}}, problems)
            for key, rule in schema["properties"].items():
                base = {**good}
                for value in HOSTILE_VALUES:
                    if value is True and rule["type"] == "boolean":
                        continue
                    if value == "__class__" and rule.get("pattern"):  # a name-shaped miss is the only other outcome
                        continue
                    calls += 1
                    expect_refused(start, fn, {**base, key: value}, problems)
                    if rule["type"] == "array":
                        expect_refused(start, fn, {**base, key: [value] * rule["minItems"]}, problems)
        else:
            for bad in ("x", 5, [], {MARK: 1}):
                calls += 1
                expect_refused(start, fn, bad, problems)
    check(f"{calls} hostile calls refuse with a fixed code, keep the state and echo nothing", not problems, problems[:12])

    specific = [
        ("set_tower", {"height": 40.0}, "glass_below_ground"), ("set_tower", {"width": 10.0, "floor_m": 1.0}, "out_of_range"),
        ("set_work_area", {"w": 5.0, "margin": 3.0, "drop": 80.0}, None),
        ("add_ledge", {"name": "box", **LEDGE}, "name_taken"), ("add_ledge", {"name": "Bad-Name", **LEDGE}, "bad_name"),
        ("add_ledge", {"name": "n", **LEDGE, "material": "missing"}, "no_such_material"), ("add_ledge", {"name": "n", **LEDGE, "material": "city0"}, "reserved_material"),
        ("add_ledge", {"name": "n", **{**LEDGE, "below_top_m": 0.0, "x_m": 0.15}}, "start_blocked"),
        ("add_cradle", {"name": "n", **CRADLE}, None),
        ("move_object", {"name": "ghost", "dx": 1.0}, "no_such_object"), ("move_object", {"name": "ledge", "dout": 0.1}, "fixed_by_kind"),
        ("rotate_object", {"name": "ledge", "delta_deg": [10.0, 0.0, 0.0]}, "fixed_by_kind"), ("move_object", {"name": "box", "dx": 300.0}, "out_of_range"),
        ("add_object", {**BOX, "name": "two", "size": [1.0, 1.0]}, "bad_shape"), ("set_corner", {"x_m": 1.0, "side": 0}, "out_of_range"),
        ("set_corner", {"x_m": 1.0}, "bad_args"), ("set_corner", {"x_m": 1.0, "side": 1, "remove": True}, "bad_args"), ("set_setback", {"remove": False}, "bad_args"),
        ("set_robot_start", {"x_m": 9.0}, "start_not_on_glass"), ("set_material", {"name": "fresh", "metal": 0.5}, "no_such_material"),
        ("repeat", {"name": "box", "count": 50, "dbelow": 200.0}, "out_of_range"), ("assign_material", {"name": "box", "material": "missing"}, "no_such_material"),
        ("group", {"name": "box", "members": ["ledge"]}, "name_taken"), ("group", {"name": "g", "members": ["ghost"]}, "no_such_object"),
    ]
    for fn, args, code in specific:
        out = G.call(start, fn, args)
        if code is None:
            print(f"INFO  {fn}: {out['result']}")
            continue
        check(f"{fn} refuses with {code}", out["result"] == f"cannot_build:{code}", out["result"])
    cover = {**BOX, "name": "wall", "size": [20.0, 0.05, 20.0], "below_top_m": 10.5}
    state = G.call(start, "set_work_area", {"h": 1.0})["state"]
    out = G.call(state, "add_object", {**cover, "x_m": 1.2, "below_top_m": 0.6 + 10.0 + 0.0})
    print(f"INFO  a wall under the start: {out['result']}")
    high_start = G.call(start, "set_robot_start", {"above_top_m": 0.6})["state"]
    near = G.call(high_start, "add_object", {**BOX, "name": "plate", "size": [40.0, 0.05, 4.0], "x_m": 1.0, "below_top_m": 1.7})
    check("a solid over all the glass to clean refuses", near["result"] == "cannot_build:no_glass_to_clean", near["result"])
    state, name = start, "box"
    for i in range(12):
        step = G.call(state, "repeat", {"name": name, "count": 50, "dbelow": 0.0})
        if step["result"] != G.OK:
            break
        state, name = step["state"], name + "_r1"
    check("the object cap holds under repeat", step["result"] == "cannot_build:too_many_objects", step["result"])
    state = start
    for i in range(G.MAX_GROUPS + 1):
        step = G.call(state, "group", {"name": f"g{i}", "members": ["box"]})
        state = step["state"]
    check("the group cap holds", step["result"] == "cannot_build:too_many_groups", step["result"])


def random_value(rng, rule):
    t = rule["type"]
    if t == "boolean":
        return rng.random() < 0.5
    if t == "integer":
        return rng.randint(rule["minimum"], rule["maximum"])
    if t == "number":
        return rng.uniform(rule["minimum"], rule["maximum"])
    if t == "array":
        return [random_value(rng, rule["items"]) for _ in range(rng.randint(rule["minItems"], rule["maxItems"]))]
    if "enum" in rule:
        return rng.choice(rule["enum"])
    return rng.choice(["box", "ledge", "n1", "n2", "grp", "glass", "alu", "cream", "ghost"])


def part1_fuzz(runs=1500):
    rng = random.Random(5)
    state = seeded()
    names = sorted(n for n in G.REGISTRY if n not in ("undo",))
    counts = {"ok": 0, "picture": 0, "refused": 0}
    problems = []
    for _ in range(runs):
        fn = rng.choice(names)
        schema = G.REGISTRY[fn]["args"]
        keys = sorted(schema["properties"])
        chosen = set(schema["required"]) | {k for k in keys if rng.random() < 0.4}
        args = {k: random_value(rng, schema["properties"][k]) for k in chosen}
        out = G.call(state, fn, args)
        res = out["result"]
        if res.startswith("cannot_build:"):
            counts["refused"] += 1
            if res.split(":", 1)[1] not in G.CODES:
                problems.append(res)
            continue
        counts["ok" if res == G.OK else "picture"] += 1
        new = out["state"]
        if new is not state:
            physics_xml, view_xml, _ = C.compile(new["world"])
            mujoco.MjModel.from_xml_string(physics_xml)
            mujoco.MjModel.from_xml_string(view_xml)
            state = new
        if rng.random() < 0.15 and state["history"]:
            state = G.call(state, "undo")["state"]
        if len(state["world"]["objects"]) > 60:
            state = seeded()
    check(f"{runs} random calls in range stay valid and compile", not problems, f"{counts} {problems[:5]}")


# Part 2.
def old_run(raw):
    import run_trial as OLD_R  # policy/highrise/run_trial.py, for comparison only
    import world as OLD_W
    return OLD_R.run(OLD_W.validate(raw), SEED)


def new_run(world):
    return R5.run(world, SEED)


NUMBERS = ("coverage", "time_s", "slip_m", "peak_tether_n", "peak_chassis_contact_n", "min_pressure_pa", "end_battery", "steps")


def brief(r):
    return f"{r['outcome']} failure={r['failure']} coverage={r['coverage']} t={r['time_s']} contact={r['peak_chassis_contact_n']} minP={float(r['min_pressure_pa'])}"


def diff_numbers(a, b):
    return {k: (float(a[k]), float(b[k])) for k in NUMBERS if float(a[k]) != float(b[k])}


def apply(world, fn, args):
    out = G.call(G.new_state(world), fn, args)
    if out["result"] not in (G.OK, G.PICTURE):
        raise RuntimeError(f"{fn} {args}: {out['result']}")
    return out["state"]["world"]


def lanes(world):
    return controller5.Controller({"area": W.area_rect(world), "start_x": 0.0, "start_z": 0.0, "anchor": (0, 0, 0), "clean_speed_ms": world["robot"]["clean_speed_ms"]}).lane_xs


def part2_old_vs_new():
    raw = json.loads((OLD_DIR / "worlds" / "nominal.json").read_text())
    old, new = old_run(raw), new_run(nominal())
    print(f"INFO  old nominal {brief(old)}")
    print(f"INFO  new nominal {brief(new)}")
    check("(a) nominal: same outcome as the old sim", old["outcome"] == new["outcome"] and old["failure"] == new["failure"])
    check("(a) nominal: every reported number the same", not diff_numbers(old, new), diff_numbers(old, new))
    print(f"INFO  (a) final state hash same: {old['final_state_sha256'] == new['final_state_sha256']}. action chain same: {old['action_chain_head'] == new['action_chain_head']}")
    check("(a) a new result carries the label and code hashes", new["label"].startswith("sim highrise5 ") and len(new["label"].split()[-1]) == 12 and set(new["code_sha256"]) == set(R5.CODE_FILES), new["label"])
    # The speed lines are the only allowed difference in the controller. The same-outcome runs below prove the default.
    old_lines, new_lines = (OLD_DIR / "controller.py").read_text().splitlines(), (HERE / "controller5.py").read_text().splitlines()
    extra = [line for line in new_lines if line not in old_lines]
    check("controller5.py differs from the old one only in speed lines", all("speed" in line or "scale" in line or "A copy of" in line or "-self.cross_speed" in line for line in extra), extra)
    check("judge5.py is a copy with one import changed", (HERE / "judge5.py").read_text().replace("import sim5 as S", "import sim as S") == (OLD_DIR / "judge.py").read_text())

    import check_world5  # raw_worlds holds every old world
    worlds = check_world5.raw_worlds()
    same = []
    moved = []
    for name, world_raw in worlds.items():
        if name == "nominal":
            continue
        o, n = old_run(world_raw), new_run(W.upgrade(world_raw))
        ok = o["outcome"] == n["outcome"] and o["failure"] == n["failure"]
        (same if ok and not diff_numbers(o, n) else moved).append((name, ok, brief(o), brief(n), diff_numbers(o, n), o["final_state_sha256"] == n["final_state_sha256"]))
    for row in moved:
        print(f"INFO  (a+) {row[0]} outcome same: {row[1]}\n        old {row[2]}\n        new {row[3]}\n        diff {row[4]}")
    hashes = sum(row[5] for row in same + moved)
    check("(a+) other old worlds: same outcome and numbers", not moved, f"{len(same)} of {len(same) + len(moved)} same in every reported number. Final state hash same in {hashes}")


def part2_box():
    world = nominal()
    base = new_run(world)
    lane = lanes(world)
    print(f"INFO  lanes x {[round(x, 2) for x in lane]}; area {W.area_rect(world)}; glass {W.glass_rect(world)}")
    # A box on lane 0, in the middle of the area, 5 cm proud of the glass. The nominal transoms and mullions do not sit here.
    args = {"name": "box", "shape": "box", "size": [0.5, 0.05, 0.4], "x_m": lane[0], "below_top_m": 1.5, "out_m": 0.025, "solid": True}
    on_lane = apply(world, "add_object", args)
    r = new_run(on_lane)
    print(f"INFO  (b) nominal {brief(base)}")
    print(f"INFO  (b) box on lane {brief(r)}")
    check("(b) a solid box on the lane changes the run", r["final_state_sha256"] != base["final_state_sha256"] and (r["outcome"] != base["outcome"] or r["coverage"] != base["coverage"]), diff_numbers(base, r))
    # Too high for the nose rule, so it must stop and leave the lane.
    low = apply(world, "add_object", {**args, "size": [0.5, 0.012, 0.4], "out_m": 0.006})
    rl = new_run(low)
    print(f"INFO  (b) low box 12 mm on lane {brief(rl)}")
    check("(b) a low box the robot may cross also changes the run", rl["final_state_sha256"] != base["final_state_sha256"], diff_numbers(base, rl))
    tall = apply(world, "add_object", {**args, "size": [0.5, 0.05, 0.4], "out_m": 0.05})  # inner face 2.5 cm off the glass, so no lip leak
    rt = new_run(tall)
    print(f"INFO  (b) box 2.5 cm off the glass on lane {brief(rt)}")
    check("(b) a box that floats 2.5 cm off the glass still changes the run", rt["final_state_sha256"] != base["final_state_sha256"], diff_numbers(base, rt))
    # 2 m clear: past the last lane, and on the same lane past its lower end.
    a = W.area_rect(world)
    half_w = args["size"][0] / 2
    reach = W.BODY_SIDE / 2 * 2 ** 0.5 + 0.24  # corner of a turning body, or nose ahead
    side_x = lane[-1] + reach + half_w + 2.0
    side = apply(world, "add_object", {**args, "x_m": side_x})
    rs = new_run(side)
    lowest = a["z0"] - controller5.PAD_BEHIND_CENTRE - controller5.LANE_OVERRUN_M - reach
    below = (a["z1"] - lowest) + args["size"][2] / 2 + 2.0
    under = apply(world, "add_object", {**args, "below_top_m": below}) if below <= 300 else None
    ru = new_run(under)
    print(f"INFO  (c) box at x={side_x:.2f}: {brief(rs)}")
    print(f"INFO  (c) box {below:.2f} below the area top on the lane line: {brief(ru)}")
    check("(c) a box 2 m past the last lane leaves the state hash the same", rs["final_state_sha256"] == base["final_state_sha256"], diff_numbers(base, rs))
    check("(c) a box 2 m below the lane leaves the state hash the same", ru["final_state_sha256"] == base["final_state_sha256"], diff_numbers(base, ru))
    check("(c) both worlds differ in their physics hash, so the box is really in the model", C.physics_hash(side) != C.physics_hash(world) and C.physics_hash(under) != C.physics_hash(world))
    return base


def part2_picture(base):
    world = nominal()
    state = G.new_state(world)
    for fn, args in (("set_material", {"name": "glass", "rgba": [1.0, 0.0, 0.0, 1.0], "metal": 0.0}), ("assign_material", {"name": "ledge", "material": "cream"}),
                     ("set_light", {"sun_level": 0.3, "haze": 0.9}), ("set_surroundings", {"city_seed": 9, "density": 0.3})):
        state = G.call(state, fn, args)["state"]
    r = new_run(state["world"])
    check("(d) colour, light and city edits give the same final state hash", r["final_state_sha256"] == base["final_state_sha256"] and r["action_chain_head"] == base["action_chain_head"], r["final_state_sha256"][:12])
    check("(d) the world hash differs, so the edit is real", r["world_sha256"] != base["world_sha256"])


# Function: calls the table says change physics. On top of the nominal world, or on the state named by a first call.
def physics_rows(lane0, second_lane):
    x, x2 = lane0, second_lane
    onlane = {"x_m": x, "below_top_m": 1.5}
    return [
        ("set_tower", {"height": 170.0}), ("set_tower", {"floor_m": 4.0}),
        ("set_panes", {"w": 1.2}), ("set_panes", {"h": 3.0}), ("set_panes", {"offx": 0.3}), ("set_panes", {"offz": 1.0}), ("set_panes", {"joint_depth": 0.015}),
        ("set_panes", {"joint_gap": 0.02}), ("set_panes", {"skip": 2}),
        ("set_work_area", {"w": 2.0}), ("set_work_area", {"h": 2.5}), ("set_work_area", {"drop": 30.0}),
        ("add_ledge", {"name": "n", **LEDGE, **onlane}), ("add_sill", {"name": "n", **LEDGE, **onlane, "depth_m": 0.03, "thick_m": 0.05}),
        ("add_fin", {"name": "n", **FIN, **onlane}), ("add_sign", {"name": "n", **SIGN, **onlane}), ("add_balcony", {"name": "n", **BALCONY, "x_m": 1.0, "below_top_m": 1.5}),
        ("add_vent", {"name": "n", **VENT, **onlane}), ("add_frame_step", {"name": "n", **STEP, **onlane}),
        ("add_wet_patch", {"name": "n", "wetness": 0.9, **PATCH, **onlane}), ("add_dirt_patch", {"name": "n", "level": 2.0, **PATCH, **onlane}),
        ("add_cradle", {"name": "n", **CRADLE, "x_m": 1.0}),
        ("set_corner", {"x_m": 2.0, "side": 1}),
        ("add_object", {**BOX, "x_m": x}),
        ("set_weather", {"wetness": 0.5}), ("set_weather", {"temperature_c": -5.0}), ("set_weather", {"humidity_pct": 90.0}), ("set_weather", {"dust_gm2": 20.0}),
        ("set_wind", {"steady_ms": 5.0}), ("set_wind", {"gust_ms": 15.0}), ("set_wind", {"gust_start_s": 10.0}), ("set_wind", {"gust_duration_s": 20.0}),
        ("set_wind", {"gust_count": 5}), ("set_wind", {"gust_period_s": 40.0}), ("set_wind", {"dir_deg": 90.0}),
        ("set_robot", {"suction_pa": 1500.0}), ("set_robot", {"seal_leak_mm2": 800.0}), ("set_robot", {"battery_start_frac": 0.5}), ("set_robot", {"pad_force_n": 50.0}), ("set_robot", {"clean_speed_ms": 0.2}),
        ("set_dirt", {"level": 1.5}), ("set_robot_start", {"x_m": 0.5}), ("set_robot_start", {"above_top_m": 0.2}),
    ]


def part2_every_function(base):
    world = nominal()
    lane = lanes(world)
    dead = []
    for fn, args in physics_rows(lane[0], lane[1]):
        r = new_run(apply(world, fn, args))
        same = r["final_state_sha256"] == base["final_state_sha256"]
        label = f"(e) {fn} {sorted(k for k in args if k not in ('name', 'x_m', 'below_top_m'))[:2]} changes the run"
        check(label, not same, f"{brief(r)}")
        if same:
            dead.append(label)
    # Object edits on a box that is already on the lane.
    box_world = apply(world, "add_object", {**BOX, "x_m": lane[0]})
    box_base = new_run(box_world)
    for fn, args in (("move_object", {"name": "box", "dbelow": 0.5}), ("rotate_object", {"name": "box", "delta_deg": [0.0, 45.0, 0.0]}),
                     ("repeat", {"name": "box", "count": 1, "dx": lane[1] - lane[0]}), ("remove_object", {"name": "box"})):
        r = new_run(apply(box_world, fn, args))
        check(f"(e) {fn} on a box on the lane changes the run", r["final_state_sha256"] != box_base["final_state_sha256"], brief(r))
    removed = new_run(apply(box_world, "remove_object", {"name": "box"}))
    check("(e) removing the box gives back the nominal state hash", removed["final_state_sha256"] == base["final_state_sha256"])
    # Height, with numbers.
    tall = apply(world, "set_tower", {"height": 170.0})
    print(f"INFO  (e) height 170: transoms in the area move. old {[round(z - W.area_rect(world)['z0'], 3) for z in W.transom_zs(world) if W.area_rect(world)['z0'] - 1 < z < W.area_rect(world)['z1'] + 1]}, new {[round(z - W.area_rect(tall)['z0'], 3) for z in W.transom_zs(tall) if W.area_rect(tall)['z0'] - 1 < z < W.area_rect(tall)['z1'] + 1]}")
    floors = apply(world, "set_tower", {"height": 160.0 + 10 * 3.6})
    rf = new_run(floors)
    print(f"INFO  (e) height 196 (ten floors up): same joints against the area. {brief(rf)}; numbers differ from nominal: {diff_numbers(base, rf)}; state hash same: {rf['final_state_sha256'] == base['final_state_sha256']}")
    width = G.call(G.new_state(world), "set_tower", {"width": 60.0})
    print(f"INFO  (e) width 60: {width['result']}. The table lists no physics for width.")
    return dead


def part2_edges_are_wired():
    """Margin and setback only move the glass edge. This reads the edge directly, since the nominal run never gets there."""
    world = nominal()
    top = W.area_rect(world)["z1"]
    for fn, args in (("set_work_area", {"margin": 0.4}), ("set_setback", {"above_top_m": 0.6, "depth_m": 2.0})):
        before, after = S5.Sim(world, SEED), S5.Sim(apply(world, fn, args), SEED)
        z = top + args.get("margin", args.get("above_top_m")) + 0.05
        check(f"{fn} moves the edge the nose sensor reads", not before._nose_reading(1.0, z)[1] and after._nose_reading(1.0, z)[1], f"at {z - top:.2f} above the area top")


def part2_edges_matter(base):
    """Margin and setback change nothing on nominal and the registry says so. They do change the run where the robot climbs past the area top."""
    world = nominal()
    for fn, args in (("set_work_area", {"margin": 0.4}), ("set_setback", {"above_top_m": 0.6, "depth_m": 2.0})):
        r = new_run(apply(world, fn, args))
        check(f"(e) {fn} {sorted(args)[0]} changes nothing on nominal, as its registry note says", r["final_state_sha256"] == base["final_state_sha256"] and not diff_numbers(base, r), brief(r))
        check(f"(e) {fn} carries the may-change-nothing note", "may change nothing" in (G.REGISTRY[fn]["note"] or ""))
    # In range for every value. Strong suction on dry glass with a tight seal: the tracks grip, the pivot sag the controller allows for does not happen,
    # and the body climbs past the area top. The numbers below are not chosen to pass: this world fails with or without the edit, for different reasons.
    strong = apply(apply(world, "set_weather", {"wetness": 0.0}), "set_robot", {"seal_leak_mm2": 20.0, "suction_pa": 5000.0})
    for seed in (0, 1, 2, 3):
        without = R5.run(strong, seed)
        again = R5.run(strong, seed)
        check(f"(e) strong suction seed {seed}: the same world repeats exactly", again["final_state_sha256"] == without["final_state_sha256"])
        for fn, args in (("set_work_area", {"margin": 0.4}), ("set_setback", {"above_top_m": 0.6, "depth_m": 2.0})):
            r = R5.run(apply(strong, fn, args), seed)
            check(f"(e) strong suction seed {seed}: {fn} {sorted(args)[0]} moves a reported number", (r["outcome"], r["failure"]) != (without["outcome"], without["failure"]) or r["coverage"] != without["coverage"],
                  f"without {brief(without)} | with {brief(r)}")
    # A world that passes either way: at 2.8 m wide the last lane overshoots the area side, so the nose reaches a 0.4 m margin and the side step ends early.
    wide = apply(world, "set_work_area", {"w": 2.8})
    narrow = apply(wide, "set_work_area", {"margin": 0.4})
    a, b = new_run(wide), new_run(narrow)
    check("(e) width 2.8: margin 0.4 ends a side step early and moves the time", a["passed"] and b["passed"] and a["time_s"] != b["time_s"] and a["final_state_sha256"] != b["final_state_sha256"], f"margin 1.0 t={a['time_s']}, margin 0.4 t={b['time_s']}")


def run_speed(world, speed, seed, **robot):
    w = copy.deepcopy(world)
    w["robot"].update(clean_speed_ms=speed, **robot)
    return R5.run(w, seed)


def part2_speed():
    """Clean speed. Dirt removal in sim5._clean is a rate per second under a pad, with no speed term, so a faster pass removes less."""
    world = nominal()
    same = G.call(G.new_state(world), "set_robot", {"clean_speed_ms": 0.15})
    check("speed: 0.15 is the default, so setting it changes nothing", same["result"] == G.PICTURE and world["robot"]["clean_speed_ms"] == W.DEFAULT_CLEAN_SPEED_MS, same["result"])
    check("speed: above the cap refuses", G.call(G.new_state(world), "set_robot", {"clean_speed_ms": W.MAX_CLEAN_SPEED_MS + 0.001})["result"] == "cannot_build:out_of_range")
    seeds = range(20)
    means = {}
    for speed in (0.15, 0.18, 0.20):
        rows = [run_speed(world, speed, s) for s in seeds]
        passed = sum(r["passed"] for r in rows)
        cov = [r["coverage"] for r in rows]
        means[speed] = sum(cov) / len(cov)
        contact = max(r["peak_chassis_contact_n"] for r in rows)
        check(f"speed {speed}: nominal passes on all {len(rows)} seeds", passed == len(rows),
              f"passed {passed}, mean t={sum(r['time_s'] for r in rows) / len(rows):.1f}, coverage {min(cov):.3f}-{max(cov):.3f}, contact {contact}, failures {sorted({str(r['failure']) for r in rows})}")
    check("speed: coverage falls as speed rises, the dwell effect", means[0.15] > means[0.18] > means[0.20], {k: round(v, 4) for k, v in means.items()})
    # Why the cap is here. The range is widened for these runs only.
    rule = W.BLOCKS["robot"]["clean_speed_ms"]
    W.BLOCKS["robot"]["clean_speed_ms"] = (W.NUM, 0.05, 0.35)
    try:
        for speed in (0.22, 0.25):
            over = [run_speed(world, speed, s) for s in seeds]
            print(f"INFO  speed {speed}, over the cap: passed {sum(r['passed'] for r in over)} of {len(over)}, mean t={sum(r['time_s'] for r in over) / len(over):.1f}, failures {sorted({str(r['failure']) for r in over})}, coverage {min(r['coverage'] for r in over)}-{max(r['coverage'] for r in over)}")
            check(f"speed: {speed} fails on some seed, so the cap has a reason", not all(r["passed"] for r in over))
    finally:
        W.BLOCKS["robot"]["clean_speed_ms"] = rule
    # Other worlds at the cap.
    lane = lanes(world)
    box = apply(world, "add_object", {**BOX, "x_m": lane[0]})
    print(f"INFO  speed 0.15 with a box on the lane: {brief(run_speed(box, 0.15, SEED))}")
    print(f"INFO  speed 0.20 with a box on the lane: {brief(run_speed(box, 0.20, SEED))}")
    heavy = apply(world, "set_dirt", {"level": 1.0})
    print(f"INFO  dirt level 1.0: at 0.15 {brief(run_speed(heavy, 0.15, SEED))}; at 0.20 {brief(run_speed(heavy, 0.20, SEED))}; at 0.20 with 50 N pads {brief(run_speed(heavy, 0.20, SEED, pad_force_n=50.0))}")


def part2_scene_matches_model():
    world = nominal()
    state = G.new_state(world)
    for fn, args in (("add_object", BOX), ("add_vent", {"name": "v", **VENT, "x_m": 2.0}), ("add_object", {**BOX, "name": "far", "out_m": 3.0, "x_m": 2.0})):
        state = G.call(state, fn, args)["state"]
    m = mujoco.MjModel.from_xml_string(C.compile(state["world"])[0])
    names = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(m.ngeom)}
    physics = {o["name"] for o in state["world"]["objects"] if o["solid"] and W.effect_of(o) == "physics"}
    check("each rect has a geom, and a far solid has neither", len(E.rects(state["world"])) == len(physics) and all(f"obj_{n}" in names for n in physics) and "obj_far" not in names, sorted(physics))


def main():
    print("== engine ==")
    part1_good()
    part1_parts()
    part1_hostile()
    part1_fuzz()
    print("== sim ==")
    part2_scene_matches_model()
    part2_old_vs_new()
    base = part2_box()
    part2_picture(base)
    dead = part2_every_function(base)
    part2_edges_are_wired()
    part2_edges_matter(base)
    part2_speed()
    print(f"Functions that changed nothing: {dead}")
    print(f"{len(failures)} failed" + (f": {failures}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
