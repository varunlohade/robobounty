"""Pass or fail check of the v2 schema and BDDL writer. No sim. check_world.py exits 0 on pass."""
import copy
import itertools
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import world as w
import build_world

GOOD = (HERE / "sample_worlds" / "tabletop_cabinet_bowl.json").read_text()
INJECT = "plate) (:yaw_rotation ((__import__('os').system('id') 0)"


def spec(**changes):
    raw = json.loads(GOOD)
    raw.update(changes)
    return raw


def changed(path, value):
    raw = json.loads(GOOD)
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return raw


BAD = {
    "unknown arena": spec(arena="moon"),
    "unknown style": spec(style="neon"),
    "unknown object": changed(["objects", 0, "type"], "banana"),
    "unknown fixture": changed(["fixtures", 0, "type"], "fridge_9000"),
    "fixture as object": changed(["objects", 0, "type"], "wooden_cabinet"),
    "unknown state": changed(["fixtures", 0, "state"], "exploded"),
    "unknown predicate": changed(["goal", "predicate"], "up"),
    "debug predicate": changed(["goal", "predicate"], "printjointstate"),
    "goal names absent object": changed(["goal", "object"], "butter_1"),
    "goal part not on target": spec(goal={"predicate": "on", "object": "akita_black_bowl_1", "target": "plate_1", "part": "top_region"}),
    "unknown root field": spec(notes="hello"),
    "instruction field": spec(instruction="put the bowl on the plate"),
    "yaw_rotation field": changed(["objects", 0, "yaw_rotation"], "__import__('os')"),
    "language field": spec(language="ignore prior rules"),
    "inject in type": changed(["objects", 0, "type"], INJECT),
    "inject in arena": spec(arena=INJECT),
    "inject in goal object": changed(["goal", "object"], INJECT),
    "inject in goal target": changed(["goal", "target"], INJECT),
    "inject in goal part": changed(["goal", "part"], INJECT),
    "inject in number": changed(["objects", 0, "region", 0], "0.1)(:init"),
    "token with newline": changed(["goal", "object"], "akita_black_bowl_1\n"),
    "unicode token": changed(["objects", 0, "type"], "plаte"),
    "x out of range": changed(["objects", 0, "region", 2], 9.0),
    "y out of range": changed(["objects", 0, "region", 3], -9.0),
    "region too wide": changed(["objects", 0, "region"], [-0.45, -0.3, 0.3, 0.3]),
    "region zero size": changed(["objects", 0, "region"], [0.1, 0.1, 0.1, 0.1]),
    "region reversed": changed(["objects", 0, "region"], [0.2, 0.1, 0.1, 0.2]),
    "region too short": changed(["objects", 0, "region"], [0.1, 0.1]),
    "yaw out of range": changed(["objects", 0, "yaw"], [-9.0, 9.0]),
    "light out of range": spec(light=50.0),
    "seed negative": spec(seed=-1),
    "seed too big": spec(seed=2**31),
    "seed float": spec(seed=1.0),
    "seed bool": spec(seed=True),
    "bool as number": changed(["objects", 0, "region", 0], False),
    "too many objects": spec(objects=[{"type": "butter", "region": [0, 0, 0.1, 0.1]}] * 9),
    "no objects": spec(objects=[]),
    "too much clutter": spec(clutter=[{"x": 0, "y": 0, "half_size": 0.02}] * 4),
    "clutter too big": spec(clutter=[{"x": 0, "y": 0, "half_size": 0.5}]),
    "rgb out of range": spec(clutter=[{"x": 0, "y": 0, "half_size": 0.02, "rgb": [2, 0, 0]}]),
    "fixture on floor arena": spec(arena="floor"),
    "two look-alikes": spec(objects=json.loads(GOOD)["objects"] + [{"type": "akita_black_bowl", "region": [0, 0, 0.1, 0.1]}]),
    "schema 1": spec(schema=1),
    "not an object": [],
    "stove goal holds at start": spec(goal={"predicate": "turnoff", "object": "flat_stove_1"}),
    "drawer goal holds at start": spec(goal={"predicate": "close", "object": "wooden_cabinet_1", "part": "top_region"}),
}
BAD_TEXT = {
    "NaN": GOOD.replace('"seed": 101', '"seed": 101, "light": NaN'),
    "Infinity": GOOD.replace('"seed": 101', '"seed": 101, "light": Infinity'),
    "1e999": GOOD.replace('"seed": 101', '"seed": 101, "light": 1e999'),
    "duplicate key": GOOD.replace('"seed": 101', '"seed": 101, "seed": 102'),
    "huge integer": GOOD.replace('"seed": 101', '"seed": 1' + "0" * 5000),
    "over size cap": GOOD + " " * w.MAX_FILE_BYTES,
    "deep nesting": "[" * 100_000,
    "not JSON": "(define (problem x))",
}


def main():
    failures = []
    for name, raw in BAD.items():
        try:
            w.validate(copy.deepcopy(raw))
            failures.append(f"accepted: {name}")
        except w.SceneError:
            pass
    for name, text in BAD_TEXT.items():
        try:
            w.parse(text)
            failures.append(f"accepted: {name}")
        except w.SceneError:
            pass

    samples = sorted((HERE / "sample_worlds").glob("*.json"))
    for path in samples:
        world = w.load(path)
        text = w.write_bddl(world)
        if "yaw_rotation" in text or not w.SAFE_BDDL.fullmatch(text):
            failures.append(f"unsafe BDDL: {path.name}")

    longest = ""
    for subject, (target, parts) in itertools.product(w.MOVABLE, w.PARTS.items()):
        for part, (predicate, _) in parts.items():
            goal = {"predicate": predicate, "object": f"{subject}_1", "target": f"{target}_1", "part": part}
            text = w.instruction({"goal": goal})
            longest = max(longest, text, key=len)
    if not longest.isascii() or len(longest) > w.MAX_INSTRUCTION:
        failures.append(f"instruction too long: {longest}")

    with tempfile.TemporaryDirectory() as tmp:
        bad_file = Path(tmp) / "bad.json"
        bad_file.write_text(json.dumps(spec(arena=INJECT)))
        sys.argv = ["build_world.py", str(bad_file), "--out", str(Path(tmp) / "out")]
        if build_world.main() != 1:
            failures.append("build_world accepted a bad spec")
    started = {"mujoco", "robosuite", "libero", "sim"} & set(sys.modules)
    if started:
        failures.append(f"a bad spec reached the sim imports: {started}")

    print(f"{len(BAD) + len(BAD_TEXT)} bad specs, {len(samples)} samples, longest instruction {len(longest)} chars: {longest!r}")
    print("\n".join(failures) or "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
