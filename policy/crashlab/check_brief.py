"""Pass or fail check of brief.py with no LLM and no sim. Exits 0 on pass.

check_brief.py                  a hostile LLM reply cannot get past the plan check, and expansion stays numeric and repeatable.
check_brief.py --scan DIR ...   on real campaigns: every world file re-validates, each BDDL is exactly what our writer
                                makes from its spec, and no brief word outside the catalog reaches a world file or BDDL.
"""
import copy
import inspect
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brief
import brief_highrise as hr
import brief_libero as lb
import world as w
from scene import SceneError

CANARY = "CANARYZULU"
HR_PLAN = {"gust_speed_ms": {"min": 15.0, "max": 25.0}, "mullion_depth_m": {"min": 0.02, "max": 0.04}}
HR_MAPPED = [{"factor": "element_vent"}, {"factor": "element_ledge"}, {"factor": "gust_speed_ms"}, {"factor": "mullion_depth_m"}, {"factor": "gust_count"},
             {"factor": "cable_length_m"}, {"factor": "fan_power_n"}, {"factor": "brush_pressure_n"}]
LB_PLAN = {"arenas": ["kitchen"], "styles": ["base"],
           "goals": [{"predicate": "on", "object_type": "akita_black_bowl", "target_type": "plate", "part": "none",
                      "object_zones": ["edge_left"], "target_zones": ["anywhere"]}],
           "required": [{"type": "cookies", "role": "blocker", "zones": ["anywhere"]}], "fixtures": [],
           "distractor_pool": ["milk", "butter", "ketchup"], "distractors": {"min": 1, "max": 3}, "distractor_zones": ["anywhere"],
           "boxes": {"min": 0, "max": 2}, "light": {"min": 0.8, "max": 1.2}, "yaw_spread": {"min": 0.0, "max": 0.8}}


def lb_changed(key, value):
    plan = copy.deepcopy(LB_PLAN)
    plan[key] = value
    return plan


def lb_goal(key, value):
    plan = copy.deepcopy(LB_PLAN)
    plan["goals"][0][key] = value
    return plan


BAD_HR = {
    "text field": {**HR_PLAN, "notes": CANARY},
    "yaw_rotation field": {**HR_PLAN, "yaw_rotation": "__import__('os')"},
    "string as number": {"gust_speed_ms": {"min": "15", "max": 25.0}},
    "over limit": {"gust_speed_ms": {"min": 1.0, "max": 9000.0}},
    "reversed": {"gust_speed_ms": {"min": 25.0, "max": 15.0}},
    "bool as number": {"gust_speed_ms": {"min": False, "max": 25.0}},
    "extra key": {"gust_speed_ms": {"min": 1.0, "max": 2.0, "note": CANARY}},
    "float as integer": {"gust_count": {"min": 1.5, "max": 2.5}},
    "uncited field": {"suction_pa": {"min": 1000.0, "max": 2000.0}},
    "unknown element": {"elements": {"forklift": {"count": {"min": 1, "max": 1}}}},
    "code as an element type": {"elements": {"__import__('os')": {"count": {"min": 1, "max": 1}}}},
    "xml in an element type": {"elements": {"<geom/>": {"count": {"min": 1, "max": 1}}}},
    "uncited element": {"elements": {"fin": {"count": {"min": 1, "max": 1}}}},
    "element over its cap": {"elements": {"vent": {"count": {"min": 1, "max": 99}}}},
    "element count zero": {"elements": {"vent": {"count": {"min": 0, "max": 1}}}},
    "element without a count": {"elements": {"vent": {}}},
    "text on an element": {"elements": {"vent": {"count": {"min": 1, "max": 1}, "note": CANARY}}},
    "unknown element field": {"elements": {"vent": {"count": {"min": 1, "max": 1}, "fields": {"file": {"min": 1, "max": 2}}}}},
    "string as an element value": {"elements": {"vent": {"count": {"min": 1, "max": 1}, "fields": {"width_m": {"min": CANARY, "max": 1.0}}}}},
    "element value over limit": {"elements": {"ledge": {"count": {"min": 1, "max": 1}, "fields": {"depth_m": {"min": 0.1, "max": 900.0}}}}},
    "nan element value": {"elements": {"ledge": {"count": {"min": 1, "max": 1}, "fields": {"depth_m": {"min": float("nan"), "max": 0.2}}}}},
    "elements not an object": {"elements": [CANARY]},
    "no elements": {"elements": {}},
    "removed field cable_length_m": {"cable_length_m": {"min": 10.0, "max": 18.0}},
    "removed field fan_power_n": {"fan_power_n": {"min": 100.0, "max": 200.0}},
    "removed field brush_pressure_n": {"brush_pressure_n": {"min": 50.0, "max": 70.0}},
    "mullion over the v3 limit": {"mullion_depth_m": {"min": 0.08, "max": 0.12}},
    "no fields": {},
    "not an object": [CANARY],
}
BAD_LB = {
    "text field": {**LB_PLAN, "notes": CANARY},
    "yaw_rotation field": {**LB_PLAN, "yaw_rotation": "__import__('os')"},
    "unknown arena": lb_changed("arenas", ["moon"]),
    "no arena": lb_changed("arenas", []),
    "inject in arena": lb_changed("arenas", ["kitchen) (:yaw_rotation"]),
    "unknown object": lb_goal("object_type", "forklift"),
    "inject in predicate": lb_goal("predicate", "printjointstate"),
    "inject in part": lb_goal("part", "top_region) (:init"),
    "unknown zone": lb_goal("object_zones", ["space"]),
    "too many distractors": lb_changed("distractors", {"min": 0, "max": 99}),
    "too many boxes": lb_changed("boxes", {"min": 0, "max": 99}),
    "light over limit": lb_changed("light", {"min": 0.1, "max": 50.0}),
    "no goals": lb_changed("goals", []),
    "fixture in arena without fixtures": {**lb_changed("arenas", ["floor"]), "goals": [
        {"predicate": "on", "object_type": "butter", "target_type": "flat_stove", "part": "cook_region",
         "object_zones": [], "target_zones": []}]},
}


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings_in(v)


def offline():
    failures = []
    for name, plan in BAD_HR.items():
        try:
            hr.validate_plan(plan, HR_MAPPED)
            failures.append(f"highrise accepted: {name}")
        except SceneError:
            pass
    for name, plan in BAD_LB.items():
        try:
            lb.validate_plan(plan, [])
            failures.append(f"libero accepted: {name}")
        except SceneError:
            pass

    for plugin in (hr, lb):
        if list(inspect.signature(plugin.expand).parameters) != ["plan", "seed"]:
            failures.append(f"{plugin.__name__}.expand can see more than the plan and seed")

    for name, f in hr.FIELDS.items():
        if not f[0] <= hr.GUIDE[name][0] <= hr.GUIDE[name][1] <= f[1]:
            failures.append(f"default range outside the highrise limits: {name}")
    if set(hr.GUIDE) != set(hr.FIELDS) or set(hr.VOCABULARY) != set(hr.FACTORS):
        failures.append("highrise guide or vocabulary does not match the world fields")
    nominal = hr.validate(json.loads((HERE.parent / "highrise" / "worlds" / "nominal.json").read_text()))
    for name in hr.FIELDS:
        if not hr.GUIDE[name][0] <= nominal[name] <= hr.GUIDE[name][1]:
            failures.append(f"default range misses the nominal world: {name}")
    plan = hr.validate_plan(HR_PLAN, HR_MAPPED)
    specs = hr.expand(plan, 7)
    first = [next(specs) for _ in range(50)]
    specs = hr.expand(plan, 7)
    if first != [next(specs) for _ in range(50)]:
        failures.append("highrise expansion is not repeatable")
    for spec in first:
        hr.validate(spec)
        if set(strings_in(spec)) - set(spec) - {hr.hw.SCHEMA}:
            failures.append("highrise world holds a free string")

    plan = lb.validate_plan(LB_PLAN, [])
    allowed = catalog_tokens()
    specs = lb.expand(plan, 7)
    good = 0
    for _ in range(50):
        spec, _meta = next(specs)
        if spec is None:
            continue
        world = w.validate(spec)
        good += 1
        extra = {t.strip("_") for t in re.findall(r"[a-z_]+", " ".join(strings_in(spec)))} - allowed
        if extra:
            failures.append(f"libero world holds strings outside the catalog: {sorted(extra)}")
        if "yaw_rotation" in w.write_bddl(world):
            failures.append("yaw_rotation in BDDL")
    if good < 30:
        failures.append(f"libero expansion made only {good}/50 specs")

    words = brief.words_of("a b c")
    for bad_reply in ({"verdict": "build", "reject_reason": "none", "plan": {}, "mapped": [{"first_word": 0, "last_word": 99, "factor": "dirt_level"}], "unbuildable": []},
                      {"verdict": "build", "reject_reason": "none", "plan": {}, "mapped": [{"first_word": 0, "last_word": 0, "factor": CANARY}], "unbuildable": []},
                      {"verdict": CANARY, "reject_reason": "none", "plan": {}, "mapped": [], "unbuildable": []},
                      {"verdict": "build", "reject_reason": "none", "plan": {CANARY: {"min": 1, "max": 2}}, "mapped": [], "unbuildable": [], CANARY: 1}):
        with tempfile.TemporaryDirectory() as tmp:
            reply = Path(tmp) / "reply.json"
            reply.write_text(json.dumps({"llm_reply": bad_reply}))
            subprocess.run([sys.executable, str(HERE / "brief.py"), " ".join(words), "--schema", "highrise", "--n", "2",
                            "--out", tmp, "--plan", str(reply)], capture_output=True, check=True)
            text = (Path(tmp) / "campaign.json").read_text()
            if CANARY in text or json.loads(text)["worlds"]:
                failures.append("a hostile LLM reply reached the campaign file")
    for text, code in (("x" * 3000, "brief_too_long"), ("a‮b", "brief_has_control_characters"), ("  ", "brief_empty")):
        try:
            brief.words_of(text)
            failures.append(f"brief accepted, expected {code}")
        except brief.Rejected:
            pass
    failures += element_checks()
    print(f"{len(BAD_HR)} bad highrise plans, {len(BAD_LB)} bad libero plans, {good}/50 libero specs")
    return failures


def element_checks():
    failures = []
    plan = hr.validate_plan({"elements": {"vent": {"count": {"min": 3, "max": 4}}, "ledge": {"count": {"min": 1, "max": 1}, "fields": {"depth_m": {"min": 0.2, "max": 0.3}}}}}, HR_MAPPED)
    specs = hr.expand(plan, 7)
    good = 0
    names = {*hr.E.SPECS, *(n for s_ in hr.E.SPECS.values() for n in s_["fields"]), "type", "elements"}
    for _ in range(40):
        spec = next(specs)
        if set(strings_in(spec)) - set(spec) - names - {hr.hw.SCHEMA_V4}:
            failures.append("an element holds a free string")
        try:
            world = hr.validate(spec)
        except SceneError:
            continue
        good += 1
        if world["schema"] != hr.hw.SCHEMA_V4 or not 4 <= len(world["elements"]) <= 5:
            failures.append("element count wrong")
        if not all(0.2 <= e["depth_m"] <= 0.3 for e in world["elements"] if e["type"] == "ledge"):
            failures.append("an element range was ignored")
    if good < 20:
        failures.append(f"only {good}/40 element worlds valid")
    if set(hr.E.SPECS) != set(hr.elements_plan.MEANING) or not all(f"element_{k}" in hr.VOCABULARY for k in hr.E.SPECS):
        failures.append("an allowlisted element has no catalog row")
    text = hr.catalog_text()
    if "not a finding" not in text or not all(k in text for k in hr.E.SPECS):
        failures.append("catalog text misses elements or the controller note")
    if not any("not a finding" in x for x in hr.LIMITS):
        failures.append("limits miss the controller note")
    return failures


def catalog_tokens():
    tokens = {*hr.E.SPECS, *(n for s_ in hr.E.SPECS.values() for n in s_["fields"]), "elements", hr.hw.SCHEMA_V4,*w.ARENAS, *w.MOVABLE, *w.FIXED, *w.PARTS, *w.DRAWERS, *w.PREDICATES, *lb.STATE_TOKENS, *lb.PART_TOKENS,
              "schema", "arena", "style", "seed", "light", "fixtures", "objects", "clutter", "goal", "type", "region", "yaw", "state",
              "predicate", "object", "target", "part", "x", "y", "half_size", "rgb", *hr.FIELDS, hr.hw.SCHEMA}
    for arena in w.ARENAS.values():
        tokens.update(arena["styles"])
    tokens.update(re.findall(r"[a-z_]+", " ".join(tokens)))
    tokens.update(w._word(k) for k in [*w.MOVABLE, *w.FIXED])
    for table in (w.MOVABLE, w.FIXED):
        tokens.update(word for v in table.values() for word in v.split())
    return tokens


def scan(folders):
    failures = []
    allowed = {t.lower() for t in catalog_tokens()}
    grammar = {"define", "problem", "domain", "robosuite", "language", "regions", "target", "ranges", "fixtures", "objects",
               "obj_of_interest", "init", "goal", "and", "on", "in", "open", "close", "turnon", "turnoff", "put", "pick", "up",
               "place", "it", "the", "turn", "of", "top", "front", "back", "left", "right", "compartment", "drawer"}
    for folder in map(Path, folders):
        campaign = json.loads((folder / "campaign.json").read_text())
        brief_words = {w_ for w_ in re.findall(r"[a-z_]{4,}", campaign["brief"].lower())}
        worlds = sorted((folder / "worlds").glob("*")) if (folder / "worlds").is_dir() else []
        specs = [p for p in worlds if p.suffix == ".json"]
        bddls = [p for p in worlds if p.suffix == ".bddl"]
        for path in specs + bddls:
            text = path.read_text().lower()
            if "yaw_rotation" in text or "__import__" in text:
                failures.append(f"{path}: unsafe text")
            present = set(re.findall(r"[a-z_]{4,}", text))
            leaked = (brief_words & present) - allowed - grammar - {p.lower() for arena in w.ARENAS.values() for p in (arena["problem"],)}
            leaked = {word for word in leaked if not any(word in part for part in allowed)}
            if leaked:
                failures.append(f"{path}: brief words in the world: {sorted(leaked)}")
        if campaign["world_schema"] == "libero":
            for path in specs:
                world = w.load(path)
                bddl = path.parent / f"{world['arena']}_{w.world_hash(world)[:12]}.bddl"
                if bddl.read_text() != w.write_bddl(world):
                    failures.append(f"{bddl}: not what our writer makes from the spec")
        else:
            for path in specs:
                hr.validate(json.loads(path.read_text()))
        print(f"{folder.name}: verdict={campaign['verdict']} rejection={campaign['rejection']} world files={len(specs)} "
              f"bddl={len(bddls)} could_not_build={len(campaign['could_not_build'])}")
    return failures


def main():
    failures = scan(sys.argv[2:]) if sys.argv[1:2] == ["--scan"] else offline()
    print("\n".join(failures) or "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
