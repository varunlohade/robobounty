"""Scene file schema. Numeric JSON only. No sim imports, so a bad file dies before the sim starts.

{
  "schema": 1,
  "task_id": 1,                 libero_spatial task, 0-9
  "init_state": 0,              stock init state, 0-49
  "seed": 1,                    integer, 0 to 2^31-1
  "objects": [{"object": 0, "dx": 0.04, "dy": 0.0, "dyaw": 0.0}],   metres, radians (optional)
  "light": 1.0,                 scale on all lights, 0.2-2.0 (optional)
  "colours": [{"object": 0, "rgb": [1.0, 0.0, 0.0]}],               replaces the texture (optional)
  "clutter": [{"x": 0.1, "y": 0.1, "yaw": 0.0, "half_size": 0.02, "rgb": [0.2, 0.6, 0.2]}]
                                plain box on the table, table frame, max 3 (optional)
}
Objects are indexes into OBJECTS. An out-of-range value is rejected, not clamped.
"""
import hashlib
import json
import math
from pathlib import Path

OBJECTS = (
    "akita_black_bowl_1",  # the target in every libero_spatial task
    "akita_black_bowl_2",
    "cookies_1",
    "glazed_rim_porcelain_ramekin_1",
    "plate_1",  # the goal in every libero_spatial task
)
TARGET_OBJECT, GOAL_OBJECT = 0, 4

MAX_FILE_BYTES = 16_384
MAX_SEED = 2**31 - 1
RANGES = {
    "dx": (-0.15, 0.15),
    "dy": (-0.15, 0.15),
    "dyaw": (-math.pi, math.pi),
    "light": (0.2, 2.0),
    "rgb": (0.0, 1.0),
    "x": (-0.4, 0.4),
    "y": (-0.5, 0.5),
    "yaw": (-math.pi, math.pi),
    "half_size": (0.01, 0.05),
}
ROOT_REQUIRED = {"schema", "task_id", "init_state", "seed"}
ROOT_OPTIONAL = {"objects", "light", "colours", "clutter"}


class SceneError(ValueError):
    pass


def _reject_constant(name):
    raise SceneError(f"non-finite number: {name}")


def _reject_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise SceneError(f"duplicate field: {k}")
        out[k] = v
    return out


def _integer(value, name, low, high):
    if type(value) is not int:
        raise SceneError(f"{name} must be an integer")
    if not low <= value <= high:
        raise SceneError(f"{name}={value} out of range [{low}, {high}]")
    return value


def _number(value, name, key=None):
    low, high = RANGES[key or name.rsplit(".", 1)[-1]]
    if type(value) not in (int, float):
        raise SceneError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise SceneError(f"{name} must be finite")
    if not low <= value <= high:
        raise SceneError(f"{name}={value} out of range [{low}, {high}]")
    return value + 0.0  # turns -0.0 into 0.0 so the hash does not fork


def _fields(entry, name, required, optional=frozenset()):
    if not isinstance(entry, dict):
        raise SceneError(f"{name} must be an object")
    unknown = set(entry) - set(required) - set(optional)
    if unknown:
        raise SceneError(f"{name}: unknown field {sorted(unknown)}")
    missing = set(required) - set(entry)
    if missing:
        raise SceneError(f"{name}: missing field {sorted(missing)}")


def _rgb(value, name):
    if not isinstance(value, list) or len(value) != 3:
        raise SceneError(f"{name} must be a list of 3 numbers")
    return [_number(v, f"{name}[{i}]", "rgb") for i, v in enumerate(value)]


def _object_list(raw, name, max_len):
    if not isinstance(raw, list) or len(raw) > max_len:
        raise SceneError(f"{name} must be a list of at most {max_len}")
    return raw


def _unique_objects(entries, name):
    ids = [e["object"] for e in entries]
    if len(set(ids)) != len(ids):
        raise SceneError(f"{name}: an object appears twice")


def validate(raw):
    _fields(raw, "scene", ROOT_REQUIRED, ROOT_OPTIONAL)
    if raw["schema"] != 1 or type(raw["schema"]) is not int:
        raise SceneError("schema must be 1")
    scene = {
        "schema": 1,
        "task_id": _integer(raw["task_id"], "task_id", 0, 9),
        "init_state": _integer(raw["init_state"], "init_state", 0, 49),
        "seed": _integer(raw["seed"], "seed", 0, MAX_SEED),
    }

    objects = []
    for i, e in enumerate(_object_list(raw.get("objects", []), "objects", len(OBJECTS))):
        n = f"objects[{i}]"
        _fields(e, n, {"object"}, {"dx", "dy", "dyaw"})
        objects.append({
            "object": _integer(e["object"], f"{n}.object", 0, len(OBJECTS) - 1),
            **{k: _number(e.get(k, 0.0), f"{n}.{k}") for k in ("dx", "dy", "dyaw")},
        })
    _unique_objects(objects, "objects")
    scene["objects"] = sorted(objects, key=lambda e: e["object"])

    scene["light"] = _number(raw.get("light", 1.0), "light")

    colours = []
    for i, e in enumerate(_object_list(raw.get("colours", []), "colours", len(OBJECTS))):
        n = f"colours[{i}]"
        _fields(e, n, {"object", "rgb"})
        colours.append({
            "object": _integer(e["object"], f"{n}.object", 0, len(OBJECTS) - 1),
            "rgb": _rgb(e["rgb"], f"{n}.rgb"),
        })
    _unique_objects(colours, "colours")
    scene["colours"] = sorted(colours, key=lambda e: e["object"])

    clutter = []
    for i, e in enumerate(_object_list(raw.get("clutter", []), "clutter", 3)):
        n = f"clutter[{i}]"
        _fields(e, n, {"x", "y", "half_size"}, {"yaw", "rgb"})
        clutter.append({
            "x": _number(e["x"], f"{n}.x"),
            "y": _number(e["y"], f"{n}.y"),
            "yaw": _number(e.get("yaw", 0.0), f"{n}.yaw"),
            "half_size": _number(e["half_size"], f"{n}.half_size"),
            "rgb": _rgb(e.get("rgb", [0.5, 0.5, 0.5]), f"{n}.rgb"),
        })
    scene["clutter"] = clutter
    return scene


def parse(text):
    """Strict parse: rejects NaN, Infinity, 1e999 and duplicate keys."""
    if len(text) > MAX_FILE_BYTES:
        raise SceneError(f"scene file over {MAX_FILE_BYTES} bytes")
    try:
        raw = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_reject_duplicates)
    except (json.JSONDecodeError, RecursionError) as e:
        raise SceneError(f"not valid JSON: {e}") from e
    return validate(raw)


def load(path):
    data = Path(path).read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise SceneError(f"scene file over {MAX_FILE_BYTES} bytes")
    try:
        return parse(data.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise SceneError("scene file is not UTF-8") from e


def canonical(scene):
    return json.dumps(scene, sort_keys=True, separators=(",", ":"), allow_nan=False)


def scene_hash(scene):
    return hashlib.sha256(canonical(scene).encode()).hexdigest()
