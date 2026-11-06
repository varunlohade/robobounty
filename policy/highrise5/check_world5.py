"""Checks tasks 1 and 2 of docs/WORLD-PLAN.md. Run with policy/.venv/bin/python. Exit code 0 only if every check passes."""
import copy
import json
import os
import random
import sys
import tempfile
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
OLD_DIR = HERE.parent / "highrise"
sys.path.insert(0, str(HERE))
sys.path.append(str(OLD_DIR))
import compile5 as C
import world as OLD  # policy/highrise/world.py, for comparison only
import world5 as W

failures = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + str(detail) if detail != '' else ''}")
    if not ok:
        failures.append(label)


def raw_worlds():
    """Every world the old folder defines. benign.json holds changes to nominal, and moderate_ranges.json holds a range table."""
    out = {}
    wdir = OLD_DIR / "worlds"
    nominal = json.loads((wdir / "nominal.json").read_text())
    out["nominal"] = nominal
    for p in sorted((wdir / "samples").glob("*.json")):
        out["samples/" + p.stem] = json.loads(p.read_text())
    for entry in json.loads((wdir / "benign.json").read_text()):
        out["benign/" + entry["name"]] = {**nominal, **{k: v for k, v in entry.items() if k != "name"}}
    spec = json.loads((wdir / "moderate_ranges.json").read_text())
    for label, side in (("low", 0), ("high", 1)):
        out[f"moderate/{label}"] = {**nominal, **{k: v[side] for k, v in spec["ranges"].items()}, "gust_count": spec["gust_count"][side]}
    return out


def expect_reject(label, fn, results):
    try:
        fn()
    except W.WorldError as e:
        results.append((label, True, str(e)))
    except Exception as e:  # a crash is a failure: only a clean rejection counts
        results.append((label, False, f"crashed with {type(e).__name__}"))
    else:
        results.append((label, False, "accepted"))


def obj(name="thing", **over):
    base = {"name": name, "kind": "object", "shape": "box", "size": [0.5, 0.02, 0.5], "pos": {"x_m": 1.0, "below_top_m": 1.5, "out_m": 0.1},
            "euler_deg": [0.0, 0.0, 0.0], "material": "alu", "solid": True, "props": {}}
    base.update(over)
    return base


def hostile_v5(base):
    """(label, edit). Each edit breaks a deep copy of a valid world."""
    def s(path, value):
        def edit(w):
            node = w
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
        return edit

    def d(path):
        def edit(w):
            node = w
            for key in path[:-1]:
                node = node[key]
            del node[path[-1]]
        return edit

    def add(*objects):
        return lambda w: w["objects"].extend(objects)

    def many(n, **over):
        return add(*[obj(f"o{i}", **over) for i in range(n)])

    vent = dict(kind="vent", size=[0.5, 0.003, 1.0], material="el_dark", props={"open_frac": 0.3}, pos={"x_m": 3.0, "below_top_m": 2.0, "out_m": 0.0015})
    cradle = dict(kind="cradle", size=[1.0, 0.6, 0.5], material="el_cradle", props={"travel_m": 1.0, "period_s": 50.0}, pos={"x_m": 3.0, "below_top_m": 3.0, "out_m": 0.31})
    ledge = dict(kind="ledge", size=[0.5, 0.02, 0.1], material="concrete", pos={"x_m": 1.0, "below_top_m": 1.5, "out_m": 0.01})
    W.validate({**copy.deepcopy(base), "objects": base["objects"] + [obj("l1", **ledge), obj("v1", **vent), obj("c1", **cradle)]})  # the kinds below start valid
    rows = [
        ("type: string for number", s(["wind", "steady_ms"], "3")),
        ("type: bool for number", s(["wind", "steady_ms"], True)),
        ("type: null for number", s(["area", "width_m"], None)),
        ("type: list for number", s(["area", "width_m"], [2.0])),
        ("type: float for integer", s(["wind", "gust_count"], 2.0)),
        ("type: bool for integer", s(["panes", "skip_every"], True)),
        ("type: objects not a list", s(["objects"], {})),
        ("type: object is a string", s(["objects"], ["x"])),
        ("type: solid is a number", lambda w: w["objects"].append(obj(solid=1))),
        ("type: tower is a list", s(["tower"], [])),
        ("type: materials is a list", s(["materials"], [])),
        ("type: rgba is a string", s(["materials", "alu", "rgba"], "red")),
        ("type: shape is a list", lambda w: w["objects"].append(obj(shape=["box"]))),
        ("type: kind is a dict", lambda w: w["objects"].append(obj(kind={}))),
        ("NaN in wind", s(["wind", "steady_ms"], float("nan"))),
        ("Infinity in size", lambda w: w["objects"].append(obj(size=[float("inf"), 0.02, 0.5]))),
        ("-Infinity in pos", lambda w: w["objects"].append(obj(pos={"x_m": float("-inf"), "below_top_m": 1.5, "out_m": 0.1}))),
        ("NaN in rgba", s(["materials", "alu", "rgba"], [float("nan"), 0.0, 0.0, 1.0])),
        ("NaN in euler", lambda w: w["objects"].append(obj(euler_deg=[float("nan"), 0.0, 0.0]))),
        ("huge float in size", lambda w: w["objects"].append(obj(size=[1e308, 0.02, 0.5]))),
        ("huge integer in size", lambda w: w["objects"].append(obj(size=[10 ** 400, 0.02, 0.5]))),
        ("huge integer in pos", lambda w: w["objects"].append(obj(pos={"x_m": 10 ** 400, "below_top_m": 1.5, "out_m": 0.1}))),
        ("huge integer in field", s(["wind", "gust_count"], 10 ** 400)),
        ("huge euler", lambda w: w["objects"].append(obj(euler_deg=[1e9, 0.0, 0.0]))),
        ("huge tower", s(["tower", "height_m"], 1e6)),
        ("negative size", lambda w: w["objects"].append(obj(size=[-1.0, 0.02, 0.5]))),
        ("zero size", lambda w: w["objects"].append(obj(size=[0.0, 0.02, 0.5]))),
        ("object behind the glass", lambda w: w["objects"].append(obj(pos={"x_m": 1.0, "below_top_m": 1.5, "out_m": -1.0}))),
        ("wrong size length", lambda w: w["objects"].append(obj(size=[0.5, 0.5]))),
        ("unknown key: top", s(["extra"], 1)),
        ("unknown key: block", s(["wind", "extra"], 1)),
        ("unknown key: tower", s(["tower", "extra"], 1)),
        ("unknown key: material", s(["materials", "alu", "extra"], 1)),
        ("unknown key: object", lambda w: w["objects"].append({**obj(), "file": "/etc/passwd"})),
        ("unknown key: pos", lambda w: w["objects"].append(obj(pos={"x_m": 1.0, "below_top_m": 1.5, "out_m": 0.1, "y": 1}))),
        ("unknown key: props", lambda w: w["objects"].append(obj(props={"open_frac": 0.3}))),
        ("missing key: top", d(["wind"])),
        ("missing key: field", d(["robot", "suction_pa"])),
        ("missing key: built-in material", d(["materials", "glass"])),
        ("bad schema", s(["schema"], "highrise.world.v6")),
        ("unknown tower shape", s(["tower", "shape"], "curved")),
        ("unknown object shape", lambda w: w["objects"].append(obj(shape="mesh"))),
        ("unknown object kind", lambda w: w["objects"].append(obj(kind="crane"))),
        ("XML in object name", lambda w: w["objects"].append(obj(name='x"/><include file="/etc/passwd"/>'))),
        ("newline in object name", lambda w: w["objects"].append(obj(name="thing\n"))),
        ("dot in object name", lambda w: w["objects"].append(obj(name="a.rail"))),
        ("capital in object name", lambda w: w["objects"].append(obj(name="Thing"))),
        ("unicode in object name", lambda w: w["objects"].append(obj(name="thïng"))),
        ("long object name", lambda w: w["objects"].append(obj(name="a" * 33))),
        ("empty object name", lambda w: w["objects"].append(obj(name=""))),
        ("XML in material name", s(["materials", 'x"><a b="'], {"rgba": [0.0, 0.0, 0.0, 1.0], "roughness": 0.5, "metal": 0.5})),
        ("XML in object material", lambda w: w["objects"].append(obj(material='alu"/><a b="'))),
        ("material that does not exist", lambda w: w["objects"].append(obj(material="nope"))),
        ("material the view skips", lambda w: w["objects"].append(obj(material="city0"))),
        ("repeated object name", add(obj("same"), obj("same"))),
        ("over cap: 121 objects", many(121, pos={"x_m": 3.0, "below_top_m": 3.0, "out_m": 0.1})),
        ("over cap: over 600 geoms from 119 vents", many(119, **vent)),
        ("over cap: 65 materials", lambda w: w["materials"].update({f"m{i}": {"rgba": [0.0, 0.0, 0.0, 1.0], "roughness": 0.5, "metal": 0.5} for i in range(60)})),
        ("over cap: 2 cradles", add(obj("c1", **cradle), obj("c2", **cradle))),
        ("kind: rotated ledge", lambda w: w["objects"].append(obj(**{**ledge, "euler_deg": [0.0, 0.0, 10.0]}))),
        ("kind: sphere ledge", lambda w: w["objects"].append(obj(**{**ledge, "shape": "sphere", "size": [0.2]}))),
        ("kind: non-solid ledge", lambda w: w["objects"].append(obj(**{**ledge, "solid": False}))),
        ("kind: solid patch", lambda w: w["objects"].append(obj(**{**ledge, "kind": "wet_patch", "props": {"wetness": 0.5}}))),
        ("kind: ledge away from glass", lambda w: w["objects"].append(obj(**{**ledge, "pos": {"x_m": 1.0, "below_top_m": 1.5, "out_m": 5.0}}))),
        ("kind: ledge wider than its kind", lambda w: w["objects"].append(obj(**{**ledge, "size": [50.0, 0.02, 0.1]}))),
        ("kind: vent narrower than its bars", lambda w: w["objects"].append(obj(**{**vent, "size": [0.001, 0.003, 1.0]}))),
        ("kind: vent without props", lambda w: w["objects"].append(obj(**{**vent, "props": {}}))),
        ("kind: vent open_frac too high", lambda w: w["objects"].append(obj(**{**vent, "props": {"open_frac": 5.0}}))),
        ("geometry: glass below ground", lambda w: (w["tower"].update(height_m=40.0), w["area"].update(drop_below_roof_m=30.0))),
        ("geometry: setback reaches the roof", lambda w: (w["area"].update(drop_below_roof_m=5.0), w["tower"].update(setback={"above_top_m": 5.0, "depth_m": 1.0}))),
        ("geometry: glass wider than tower", lambda w: (w["tower"].update(width_m=10.0), w["area"].update(width_m=5.0, margin_m=3.0))),
        ("geometry: robot start off glass", s(["robot_start", "x_m"], 9.0)),
        ("geometry: solid blocks the start", lambda w: w["objects"].append(obj(pos={"x_m": 0.15, "below_top_m": -0.13, "out_m": 0.05}))),
        ("geometry: rotated solid blocks the start", lambda w: w["objects"].append(obj(size=[3.0, 0.02, 0.02], euler_deg=[0.0, 90.0, 0.0], pos={"x_m": 0.15, "below_top_m": 1.0, "out_m": 0.05}))),
        ("geometry: corner removes the glass", s(["tower", "corner"], {"x_m": -3.0, "side": 1})),
        ("geometry: corner side 0", s(["tower", "corner"], {"x_m": 2.0, "side": 0})),
    ]
    return rows


def hostile_bytes(nominal):
    good = json.dumps(nominal)
    return [
        ("JSON: 1e999", good.replace('"wetness": 0.2', '"wetness": 1e999').encode()),
        ("JSON: NaN token", good.replace('"wetness": 0.2', '"wetness": NaN').encode()),
        ("JSON: Infinity token", good.replace('"wetness": 0.2', '"wetness": Infinity').encode()),
        ("JSON: repeated key", good.replace('"wetness": 0.2', '"wetness": 0.2, "wetness": 0.9').encode()),
        ("JSON: 5000 digit integer", good.replace('"gust_count": 2', '"gust_count": 1' + "0" * 5000).encode()),
        ("JSON: deep nesting", b"[" * 200000),
        ("JSON: bad UTF-8", b'{"schema": "\xff"}'),
        ("JSON: not JSON", b"<mujoco/>"),
        ("JSON: empty", b""),
        ("JSON: top-level null", b"null"),
        ("JSON: top-level list", b"[]"),
        ("JSON: over 1 MiB", b" " * (W.MAX_WORLD_FILE_BYTES + 1)),
    ]


def hostile_upgrade(nominal):
    fin = {"type": "fin", "x_m": 1.0, "below_top_m": 1.0, "height_m": 1.0, "depth_m": 0.1, "thick_m": 0.05}
    v4 = {**nominal, "schema": W.SCHEMA_V4}
    wdir = OLD_DIR / "worlds"
    return [
        ("upgrade: unknown schema", {**nominal, "schema": "highrise.world.v2"}),
        ("upgrade: v5 input", {**nominal, "schema": W.SCHEMA}),
        ("upgrade: no schema", {k: v for k, v in nominal.items() if k != "schema"}),
        ("upgrade: elements in v3", {**nominal, "elements": []}),
        ("upgrade: unknown field", {**nominal, "extra": 1}),
        ("upgrade: missing field", {k: v for k, v in nominal.items() if k != "wetness"}),
        ("upgrade: NaN field", {**nominal, "wetness": float("nan")}),
        ("upgrade: out of range", {**nominal, "suction_pa": 1e9}),
        ("upgrade: huge integer", {**nominal, "gust_count": 10 ** 400}),
        ("upgrade: elements not a list", {**v4, "elements": {}}),
        ("upgrade: 25 elements", {**v4, "elements": [fin] * 25}),
        ("upgrade: 9 fins over the type cap", {**v4, "elements": [fin] * 9}),
        ("upgrade: unknown element", {**v4, "elements": [{**fin, "type": "crane"}]}),
        ("upgrade: unhashable element type", {**v4, "elements": [{**fin, "type": []}]}),
        ("upgrade: extra element field", {**v4, "elements": [{**fin, "z": 1}]}),
        ("upgrade: NaN element field", {**v4, "elements": [{**fin, "x_m": float("nan")}]}),
        ("upgrade: element blocks the start", {**v4, "elements": [{**fin, "x_m": 0.15, "below_top_m": 0.0}]}),
        ("upgrade: corner side 0", {**v4, "elements": [{"type": "corner", "x_m": 2.0, "side": 0}]}),
        ("upgrade: range table is not a world", json.loads((wdir / "moderate_ranges.json").read_text())),
        ("upgrade: overlay list is not a world", json.loads((wdir / "benign.json").read_text())),
    ]


def task1():
    print("\n== Task 1: upgrade and validation")
    raws = raw_worlds()
    upgraded = {}
    for label, raw in raws.items():
        try:
            upgraded[label] = W.upgrade(raw)
        except Exception as e:
            check(f"upgrade {label}", False, repr(e))
    check("every old world upgrades and validates", len(upgraded) == len(raws), f"{len(upgraded)} of {len(raws)}: nominal, 8 samples, benign overlays, moderate low and high")
    print("      note: benign.json is a list of overlays and moderate_ranges.json is a range table, so neither is a world by itself. Both expand above and both reject as raw input below.")

    bad = 0
    for label, raw in raws.items():
        w = upgraded[label]
        old = OLD.validate(raw)
        g, og = W.glass_rect(w), OLD.glass_rect(old)
        same = (g == og and W.area_rect(w) == OLD.area(old) and W.mullion_xs(w) == OLD.mullion_xs(old) and W.transom_zs(w) == OLD.transom_zs(old)
                and W.friction(w) == OLD.friction(old) and W.air(w) == OLD.air(old) and W.start_pose(w) == OLD.start_pose(old))
        moved = all(w[b][k] == old[f] for f, (b, k) in W.LEGACY_MOVES.items() if not f.startswith("mullion_"))
        kept = sum(e["type"] not in ("pane_grid", "corner", "setback") for e in old.get("elements", ()))
        if not (same and moved and len(w["objects"]) == kept + 1):
            bad += 1
            print(f"      mismatch in {label}: geometry {same}, fields {moved}, objects {len(w['objects'])} for {kept + 1}")
    check("glass, joints, friction, start and fields match the old functions", bad == 0, f"{len(raws) - bad} of {len(raws)}")

    unmapped = set(W.LEGACY_FIELDS) - set(W.LEGACY_MOVES) - {"ledge_depth_m", "ledge_below_top_m", "ledge_x_m", "ledge_width_m"}
    check("every legacy field has a target", not unmapped, sorted(unmapped) or "")
    check("the legacy tables match policy/highrise", {k: v[1:] for k, v in W.LEGACY_FIELDS.items()} == OLD.FIELDS
          and {k: (v[0], {f: r[1:] for f, r in v[1].items()}) for k, v in W.LEGACY_ELEMENTS.items()} == {k: (v["cap"], v["fields"]) for k, v in OLD.E.SPECS.items()})

    base = upgraded["nominal"]
    check("validate is stable", W.validate(base) == base and W.validate(json.loads(json.dumps(base))) == base)
    results = []
    rows = hostile_v5(base)
    for label, edit in rows:
        def run(edit=edit):
            w = copy.deepcopy(base)
            edit(w)
            W.validate(w)
        expect_reject(label, run, results)
    nominal = raws["nominal"]
    for label, data in hostile_bytes(nominal):
        expect_reject(label, lambda data=data: W.parse(data), results)
    for label, raw in hostile_upgrade(nominal):
        expect_reject(label, lambda raw=raw: W.upgrade(raw), results)
    with tempfile.TemporaryDirectory() as tmp:
        link = Path(tmp) / "link.json"
        os.symlink(OLD_DIR / "worlds" / "nominal.json", link)
        expect_reject("file: symlink", lambda: W.load(link), results)
    if "-v" in sys.argv:
        for label, ok, why in results:
            print(f"      {label}: {why}")
    wrong = [r for r in results if not r[1]]
    for label, _, why in wrong:
        print(f"      not rejected: {label}: {why}")
    check("hostile set all rejected cleanly", not wrong, f"{len(results) - len(wrong)} of {len(results)}")

    cap = W.MAX_SOLIDS
    W.MAX_SOLIDS = 9
    try:
        W.validate(base)
        check("solid cap fires (cap lowered for this test)", False)
    except W.WorldError:
        check("solid cap fires (cap lowered for this test)", True, "objects alone cannot reach 300 under the 120 object cap")
    finally:
        W.MAX_SOLIDS = cap

    secret = 'SECRET"<x>'
    leaks = []
    for label, edit in (("name", lambda w: w["objects"].append(obj(name=secret))), ("key", lambda w: w["materials"].update({secret: {}})), ("top", lambda w: w.update({secret: 1}))):
        w = copy.deepcopy(base)
        edit(w)
        try:
            W.validate(w)
        except W.WorldError as e:
            if "SECRET" in str(e):
                leaks.append(label)
    check("reasons never quote file text", not leaks, leaks or "")
    return raws, upgraded


def fuzz(base, runs=600):
    """Replace one random leaf with a hostile value. Each result must be a clean rejection, or a world that compiles."""
    rng = random.Random(5)
    values = ["x", None, True, [], {}, -1, 0, 1, 1e308, -1e308, float("nan"), float("inf"), 10 ** 400, '"/><a b="', "a", 0.0005, 300.0]
    def leaves(node, path=()):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from leaves(v, path + (k,))
        elif isinstance(node, list) and node and not isinstance(node[0], dict):
            for i in range(len(node)):
                yield path + (i,)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from leaves(v, path + (i,))
        else:
            yield path
    accepted = rejected = 0
    problems = []
    all_leaves = list(leaves(base))
    for _ in range(runs):
        w = copy.deepcopy(base)
        path = rng.choice(all_leaves)
        node = w
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = rng.choice(values)
        try:
            physics, view, _ = C.compile(w)
        except W.WorldError:
            rejected += 1
            continue
        except Exception as e:
            problems.append((path, type(e).__name__))
            continue
        try:
            mujoco.MjModel.from_xml_string(physics)
            mujoco.MjModel.from_xml_string(view)
            accepted += 1
        except Exception as e:
            problems.append((path, "mujoco: " + str(e)[:80]))
    return accepted, rejected, problems


def random_world(rng, base):
    """Every field drawn across its full legal range, with random corner, setback and objects."""
    def draw(rule):
        kind, lo, hi = rule
        return rng.randint(lo, hi) if kind == W.INT else rng.uniform(lo, hi)
    def num(rule):
        return rng.choice([rule[1], rule[2], draw(rule), draw(rule)])
    w = copy.deepcopy(base)
    for block, rules in W.BLOCKS.items():
        w[block] = {k: num(r) for k, r in rules.items()}
    w["tower"].update({k: num(r) for k, r in W.TOWER_FIELDS.items()})
    w["tower"]["corner"] = rng.choice([None, {k: num(r) for k, r in W.CORNER_FIELDS.items()}])
    w["tower"]["setback"] = rng.choice([None, {k: num(r) for k, r in W.SETBACK_FIELDS.items()}])
    if rng.random() < 0.7:  # most draws start on the glass, so the compiler gets real work
        w["robot_start"] = {"x_m": 0.15, "above_top_m": 0.13}
        w["area"]["drop_below_roof_m"] = rng.uniform(5.0, 20.0)
        w["tower"]["height_m"] = rng.uniform(60.0, 300.0)
        w["tower"]["width_m"] = 80.0
    objects = []
    for i in range(rng.randint(0, 40)):
        kind = rng.choice(list(W.KINDS))
        shape = "box" if kind != "object" else rng.choice(list(W.SHAPES))
        o = {"name": f"o{i}", "kind": kind, "shape": shape, "material": rng.choice(["alu", "el_wet", "concrete"]), "props": {k: num(r) for k, r in W.KINDS[kind][1].items()}}
        pos = {"x_m": rng.uniform(1.0, 200.0), "below_top_m": rng.uniform(1.0, 300.0)}
        if kind == "object":
            o["size"] = [rng.choice([0.0005, 100.0, rng.uniform(0.0005, 3.0)]) for _ in range(W.SHAPES[shape])]
            o["euler_deg"] = [rng.uniform(-180.0, 180.0) for _ in range(3)]
            o["solid"] = rng.random() < 0.5
            pos["out_m"] = rng.choice([0.0, 300.0, rng.uniform(0.0, 3.0)])
        else:
            wr, dr, hr, gap = W.KIND_BOXES[kind]
            o["size"] = [rng.uniform(*wr), rng.uniform(*dr), rng.uniform(*hr)]
            o["euler_deg"] = [0.0, 0.0, 0.0]
            o["solid"] = W.KINDS[kind][0]
            pos["out_m"] = gap + o["size"][1] / 2
        o["pos"] = pos
        objects.append(o)
    w["objects"] = objects
    return w


def range_sweep(base, runs=1500):
    """Worlds that pass validation must always load in MuJoCo, with both models, and match the geom count."""
    rng = random.Random(55)
    accepted, rejected = 0, 0
    problems = []
    for _ in range(runs):
        w = random_world(rng, base)
        try:
            physics, view, _ = C.compile(w)
        except W.WorldError:
            rejected += 1
            continue
        except Exception as e:
            problems.append(type(e).__name__ + ": " + str(e)[:100])
            continue
        try:
            pm, vm = mujoco.MjModel.from_xml_string(physics), mujoco.MjModel.from_xml_string(view)
            if vm.ngeom != W.geom_counts(W.validate(w))[0] or pm.nq != vm.nq or compare_solids(pm, vm):
                problems.append("model mismatch")
            accepted += 1
        except Exception as e:
            problems.append("mujoco: " + str(e)[:100])
    return accepted, rejected, problems


def geom_rows(m):
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    rows = []
    for i in range(m.ngeom):
        rows.append({"name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or "", "type": int(m.geom_type[i]), "size": m.geom_size[i].copy(),
                     "xpos": d.geom_xpos[i].copy(), "xmat": d.geom_xmat[i].copy(), "friction": m.geom_friction[i].copy(), "priority": int(m.geom_priority[i]),
                     "contype": int(m.geom_contype[i]), "conaffinity": int(m.geom_conaffinity[i]), "solref": m.geom_solref[i].copy(), "solimp": m.geom_solimp[i].copy(),
                     "condim": int(m.geom_condim[i]), "margin": float(m.geom_margin[i]), "rgba": (m.mat_rgba[m.geom_matid[i]] if m.geom_matid[i] >= 0 else m.geom_rgba[i]).copy(),
                     "body": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[i]) or ""})
    return rows


def solid_rows(rows):
    return [r for r in rows if r["contype"] or r["conaffinity"]]


GEOM_FIELDS = ("type", "size", "xpos", "xmat", "friction", "priority", "contype", "conaffinity", "solref", "solimp", "condim", "margin")


def differ(a, b, tol=1e-9):
    return not np.allclose(a, b, atol=tol, rtol=0)


def compare_solids(old_model, new_model):
    """Differences in collidable geoms, in order, with each one named."""
    diffs = []
    old, new = solid_rows(geom_rows(old_model)), solid_rows(geom_rows(new_model))
    if len(old) != len(new):
        diffs.append(f"solid count {len(old)} old, {len(new)} new")
    for a, b in zip(old, new):
        label = a["name"] or f"unnamed->{b['name']}"
        for field in GEOM_FIELDS:
            if differ(a[field], b[field]):
                diffs.append(f"{label}.{field}: old {np.round(a[field], 6).tolist()} new {np.round(b[field], 6).tolist()}")
    return diffs


def compare_model(old, new):
    diffs = []
    for f in ("nq", "nv", "nu", "ntendon", "nmocap", "nsite"):
        if getattr(old, f) != getattr(new, f):
            diffs.append(f"{f}: old {getattr(old, f)} new {getattr(new, f)}")
    for f in ("qpos0", "actuator_gainprm", "actuator_biasprm", "actuator_forcerange", "dof_armature", "dof_damping", "tendon_range", "tendon_solref_lim", "tendon_solimp_lim", "site_pos"):
        if differ(getattr(old, f), getattr(new, f)):
            diffs.append(f"{f} differs")
    for f in ("timestep", "impratio", "noslip_iterations", "iterations", "ls_iterations", "integrator", "cone", "solver"):
        if getattr(old.opt, f) != getattr(new.opt, f):
            diffs.append(f"opt.{f}")
    names = ["robot"] + [f"roller_{n}" for n in ("lf", "lb", "rf", "rb")]
    for name in names:
        a, b = old.body(name), new.body(name)
        for f in ("mass", "inertia", "pos", "quat", "ipos", "iquat"):
            if differ(getattr(a, f), getattr(b, f)):
                diffs.append(f"body {name}.{f}: old {getattr(a, f).tolist()} new {getattr(b, f).tolist()}")
    if differ(old.stat.meaninertia, new.stat.meaninertia):
        diffs.append(f"stat.meaninertia old {old.stat.meaninertia} new {new.stat.meaninertia}")
    return diffs


def step_gap(old, new, steps=1500):
    """Same push and drive on both models, over 3 s. Largest qpos difference."""
    states = []
    for m in (old, new):
        d = mujoco.MjData(m)
        body = m.body("robot").id
        d.xfrc_applied[body, 1] = 200.0
        d.ctrl[:] = [0.3, 0.3, -0.2, -0.2]
        for _ in range(steps):
            mujoco.mj_step(m, d)
        states.append(d.qpos.copy())
    return float(np.max(np.abs(states[0] - states[1]))), states[1]


def compare_view(old, new):
    """Every old geom must exist in the view model: same type, size, world position, colour. Order may differ."""
    left = geom_rows(new)
    missing = []
    for a in geom_rows(old):
        hit = next((b for b in left if b["type"] == a["type"] and not differ(a["size"], b["size"], 1e-4) and not differ(a["xpos"], b["xpos"], 1e-4)
                    and not differ(a["xmat"], b["xmat"], 1e-6) and not differ(a["rgba"], b["rgba"], 1e-6)), None)
        if hit is None:
            missing.append(a["name"] or f"unnamed type {a['type']} at {np.round(a['xpos'], 3).tolist()} size {np.round(a['size'], 4).tolist()}")
        else:
            left.remove(hit)
    return missing, [b["name"] for b in left]


def task2(raws, upgraded):
    print("\n== Task 2: compiler, mujoco", mujoco.__version__)
    check("mujoco is 3.8.1", mujoco.__version__ == "3.8.1", mujoco.__version__)
    compiled = {}
    wrong = []
    for label, w in upgraded.items():
        physics, view, effects = C.compile(w)
        pm, vm = mujoco.MjModel.from_xml_string(physics), mujoco.MjModel.from_xml_string(view)
        compiled[label] = (physics, view, effects, pm, vm)
        if vm.ngeom != W.geom_counts(w)[0]:
            wrong.append(f"{label}: counted {W.geom_counts(w)[0]} geoms, built {vm.ngeom}")
    check("all upgraded worlds compile, physics and view", len(compiled) == len(upgraded), f"{len(compiled)} of {len(upgraded)}")
    check("geom counter equals the built model", not wrong, wrong or "")

    forbid = ("material", "rgba", "<light", "texture", "scenery", 'class="vis"', "statistic")
    leaks = [(k, t) for k, v in compiled.items() for t in forbid if t in v[0]]
    check("physics_xml has no picture content", not leaks, leaks or "")
    extras = [(k, r["name"]) for k, v in compiled.items() for r in geom_rows(v[3]) if not (r["contype"] or r["conaffinity"])]
    check("every geom in physics_xml collides", not extras, extras or "")
    drawn = {0, 2, 3, 5, 6}
    undrawable = [(k, int(t)) for k, v in compiled.items() for t in v[4].geom_type if int(t) not in drawn]
    check("view_xml uses only geom types view.ts draws", not undrawable, undrawable or "")
    needed = [("geom", n) for n in ("tower", "glass", "ground")] + [("site", n) for n in ("anchor", "tether_point")] + [("body", "robot")] + [("material", n) for n in ("city0", "city1")]
    absent = []
    for k, v in compiled.items():
        for what, n in needed:
            if mujoco.mj_name2id(v[4], getattr(mujoco.mjtObj, f"mjOBJ_{what.upper()}"), n) < 0:
                absent.append((k, n))
    check("view_xml has the names view.ts looks up", not absent, absent or "")
    mismatch = [k for k, v in compiled.items() if compare_solids(v[3], v[4]) or v[3].nq != v[4].nq]
    check("view model solids equal physics model solids", not mismatch, mismatch or "")

    print("\n-- nominal: compiled physics against policy/highrise")
    old_xml = OLD.build_xml(OLD.validate(raws["nominal"]))
    old_nominal = mujoco.MjModel.from_xml_string(old_xml)
    _, _, _, pm, vm = compiled["nominal"]
    old_rows, new_rows = geom_rows(old_nominal), geom_rows(pm)
    pairs = solid_rows(old_rows)
    names = [(a["name"], b["name"]) for a, b in zip(pairs, solid_rows(new_rows)) if a["name"] != b["name"]]
    solid_diffs = compare_solids(old_nominal, pm)
    model_diffs = compare_model(old_nominal, pm)
    check("nominal solids match on type, size, position, rotation, friction, contact", not solid_diffs, f"{len(pairs)} geoms compared")
    for line in solid_diffs:
        print("      DIFF", line)
    check("nominal model matches on robot, actuators, tether, options", not model_diffs)
    for line in model_diffs:
        print("      DIFF", line)
    gap, q = step_gap(old_nominal, pm)
    check("nominal 3 s of stepping gives the same qpos", gap < 1e-9, f"largest difference {gap:.3e}")
    print("      name differences:", names or "none")
    absent = [a for a in old_rows if not (a["contype"] or a["conaffinity"])]
    named = [a["name"] for a in absent if a["name"]]
    print(f"      geoms absent from physics_xml by design: {len(old_rows) - len(new_rows)} of {len(old_rows)}, none collide: {named}, "
          f"{sum(a['body'] == 'scenery' and not a['name'] for a in absent)} unnamed city blocks, {sum(a['body'] == 'robot' for a in absent)} unnamed robot picture geoms")
    print(f"      other: physics_xml drops <statistic>, <visual>, <asset>, the light and tendon material. nbody old {old_nominal.nbody}, new {pm.nbody} (no scenery body).")
    print(f"      other: robot geoms have names in view_xml only. view_xml has {vm.nmat - old_nominal.nmat} extra unused materials.")
    missing, added = compare_view(old_nominal, vm)
    check("nominal view model holds every old geom", not missing, missing or f"{old_nominal.ngeom} geoms")
    check("nominal view model adds no geom", not added, added or "")

    print("\n-- all worlds: against policy/highrise")
    bad = {}
    worst = 0.0
    for label, raw in raws.items():
        old = mujoco.MjModel.from_xml_string(OLD.build_xml(OLD.validate(raw)))
        pm, vm = compiled[label][3], compiled[label][4]
        missing, added = compare_view(old, vm)
        gap, _ = step_gap(old, pm)
        worst = max(worst, gap)
        d = compare_solids(old, pm) + compare_model(old, pm) + [f"view missing {m}" for m in missing] + [f"view added {m}" for m in added]
        if gap > 1e-9:
            d.append(f"stepping gap {gap:.3e}")
        if d:
            bad[label] = d
    for label, d in bad.items():
        print(f"      {label}: {len(d)} differences")
        for line in d[:12]:
            print("        DIFF", line)
    check("every world matches the old model, solids, robot, view, stepping", not bad, f"{len(raws) - len(bad)} of {len(raws)}, worst stepping gap {worst:.3e}")

    print("\n-- the comparison can see a real change")
    moved = {**raws["nominal"], "ledge_x_m": raws["nominal"]["ledge_x_m"] + 0.01}
    moved_diffs = compare_solids(old_nominal, mujoco.MjModel.from_xml_string(C.compile(W.upgrade(moved))[0]))
    check("a 1 cm ledge move shows as a named difference", any("ledge" in d and "xpos" in d for d in moved_diffs), moved_diffs[:1])

    print("\n-- physics hash")
    base = upgraded["nominal"]
    h0, xml0, view0 = C.physics_hash(base), *C.compile(base)[:2]

    def edited(fn):
        w = copy.deepcopy(base)
        fn(w)
        return w

    picture_edits = {
        "colour of a material": lambda w: w["materials"]["concrete"].update(rgba=[0.9, 0.1, 0.1, 1.0]),
        "glass colour and roughness": lambda w: w["materials"]["glass"].update(rgba=[0.1, 0.9, 0.1, 0.5], roughness=0.9),
        "robot colour": lambda w: w["materials"]["cream"].update(rgba=[0.0, 0.0, 0.0, 1.0]),
        "assign another material": lambda w: w["objects"][0].update(material="alu"),
        "light": lambda w: w["light"].update(sun_level=0.3, azimuth_deg=90.0, haze=0.9),
        "sky": lambda w: w["sky"].update(top=[0.1, 0.1, 0.1]),
        "surroundings": lambda w: w["surroundings"].update(city_seed=9, density=0.5),
        "tower width": lambda w: w["tower"].update(width_m=60.0),
        "solid far from the glass": lambda w: w["objects"].append(obj(size=[1.0, 1.0, 1.0], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 5.0})),
        "solid at 0.131 m": lambda w: w["objects"].append(obj(pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 0.141})),
        "the same box, not rotated": lambda w: w["objects"].append(obj(size=[0.05, 0.05, 2.0], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 1.05})),
        "non-solid on the glass": lambda w: w["objects"].append(obj(solid=False, pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 0.0})),
    }
    for label, fn in picture_edits.items():
        w = edited(fn)
        p, v, _ = C.compile(w)
        check(f"picture edit keeps physics hash: {label}", C.physics_hash(w) == h0 and p == xml0 and v != view0)
    physics_edits = {
        "solid at 0.09 m": lambda w: w["objects"].append(obj(pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 0.1})),
        "solid at exactly 0.13 m": lambda w: w["objects"].append(obj(size=[0.5, 0.02, 0.5], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 0.14})),
        "box rotated to reach the glass": lambda w: w["objects"].append(obj(size=[0.05, 0.05, 2.0], euler_deg=[90.0, 0.0, 0.0], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 1.05})),
        "tilted cylinder": lambda w: w["objects"].append(obj(shape="cyl", size=[0.05, 2.0], euler_deg=[90.0, 0.0, 0.0], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 1.05})),
        "solid past the glass edge": lambda w: w["objects"].append(obj(pos={"x_m": 3.5, "below_top_m": 3.0, "out_m": 0.1})),
    }
    for label, fn in physics_edits.items():
        w = edited(fn)
        check(f"solid near glass changes physics hash: {label}", C.physics_hash(w) != h0 and C.compile(w)[0] != xml0 and C.compile(w)[2][-1]["effect"] == "physics")
    no_xml_change = {
        "wind": lambda w: w["wind"].update(steady_ms=9.0),
        "suction": lambda w: w["robot"].update(suction_pa=1000.0),
        "joint gap": lambda w: w["panes"].update(joint_gap_m=0.01),
    }
    for label, fn in no_xml_change.items():
        w = edited(fn)
        check(f"sim input changes hash with the same XML: {label}", C.physics_hash(w) != h0 and C.compile(w)[0] == xml0)
    patch = obj("patch", kind="wet_patch", solid=False, size=[1.0, 0.0006, 1.0], material="el_wet", props={"wetness": 0.5}, pos={"x_m": 1.0, "below_top_m": 2.0, "out_m": 0.0009})
    a = edited(lambda w: w["objects"].append(copy.deepcopy(patch)))
    b = edited(lambda w: w["objects"].append({**copy.deepcopy(patch), "props": {"wetness": 0.9}}))
    check("a wet patch is physics, and its wetness changes the hash", C.compile(a)[2][-1]["effect"] == "physics" and len({h0, C.physics_hash(a), C.physics_hash(b)}) == 3)
    glass_friction = edited(lambda w: w["weather"].update(wetness=0.9))
    check("weather changes glass friction in physics_xml", C.compile(glass_friction)[0] != xml0)
    tall = edited(lambda w: w["tower"].update(height_m=200.0))
    check("tower height changes physics_xml", C.compile(tall)[0] != xml0)
    check("the same world hashes the same twice", C.physics_hash(copy.deepcopy(base)) == h0)

    print("\n-- free objects")
    shapes = edited(lambda w: w["objects"].extend([
        obj("box_rot", size=[0.4, 0.1, 0.2], euler_deg=[20.0, 35.0, -50.0], pos={"x_m": 1.0, "below_top_m": 2.0, "out_m": 0.2}),
        obj("cyl_rot", shape="cyl", size=[0.1, 0.5], euler_deg=[60.0, 10.0, 30.0], pos={"x_m": 1.0, "below_top_m": 3.0, "out_m": 0.3}),
        obj("cap_rot", shape="capsule", size=[0.1, 0.5], euler_deg=[-40.0, 70.0, 15.0], pos={"x_m": 1.0, "below_top_m": 4.0, "out_m": 0.3}),
        obj("ball", shape="sphere", size=[0.2], pos={"x_m": 1.0, "below_top_m": 5.0, "out_m": 0.3}),
        obj("far_rot", solid=False, size=[0.4, 0.1, 0.2], euler_deg=[120.0, -35.0, 170.0], pos={"x_m": 1.0, "below_top_m": 2.0, "out_m": 20.0})]))
    _, v, _ = C.compile(shapes)
    vm = mujoco.MjModel.from_xml_string(v)
    rows = {r["name"]: r for r in geom_rows(vm)}
    errors = []
    for o in shapes["objects"][1:]:
        r = rows[f"obj_{o['name']}"]
        if differ(np.array(W._rotation(o["euler_deg"])).ravel(), r["xmat"], 1e-5):
            errors.append(f"{o['name']} rotation")
        # MuJoCo's own world-axis half width of the same shape, from its rotation and size.
        R = r["xmat"].reshape(3, 3)
        s = r["size"]
        if o["shape"] == "box":
            ey = float(np.abs(R[1]) @ s)
        elif o["shape"] == "sphere":
            ey = float(s[0])
        elif o["shape"] == "capsule":
            ey = float(abs(R[1, 2]) * s[1] + s[0])
        else:
            ey = float(abs(R[1, 2]) * s[1] + s[0] * np.sqrt(1 - R[1, 2] ** 2))
        if abs(ey - W.half_extents(o)[1]) > 1e-5:
            errors.append(f"{o['name']} extent {ey} {W.half_extents(o)[1]}")
    check("rotation and reach to the glass match MuJoCo", not errors, errors or "4 shapes")

    accepted, rejected, problems = fuzz(base)
    for path, why in problems[:12]:
        print("      fuzz problem:", path, why)
    check("fuzz: every mutation rejects cleanly or compiles", not problems, f"{accepted} compiled, {rejected} rejected, {len(problems)} problems")
    accepted, rejected, problems = range_sweep(base)
    for why in problems[:12]:
        print("      sweep problem:", why)
    check("sweep: legal ranges and objects never break MuJoCo", not problems and accepted > 100, f"{accepted} compiled, {rejected} rejected, {len(problems)} problems")


def main():
    raws, upgraded = task1()
    task2(raws, upgraded)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
