"""World schema v5: one world file for the window robot. Every world is untrusted data.

validate() returns a new world made only of checked numbers, enums and pattern-checked names.
Reasons never quote text or values from the file. upgrade() maps a v3 or v4 world into v5.
"""
import hashlib
import json
import math
import os
import re
import stat

SCHEMA = "highrise.world.v5"
SCHEMA_V3 = "highrise.world.v3"
SCHEMA_V4 = "highrise.world.v4"
MAX_WORLD_FILE_BYTES = 1 << 20

MAX_GEOMS = 600
MAX_SOLIDS = 300
MAX_OBJECTS = 120
MAX_MATERIALS = 64
NEAR_GLASS_M = 0.13  # a solid further out than this cannot touch the robot body

# Fixed robot and building values, the same as policy/highrise/world.py.
BODY_SIDE = 0.36
BODY_MASS_KG = 4.0
BODY_HEIGHT = 0.08
RIDE_CLEARANCE = 0.02
ROLLER_RADIUS = 0.035
ROLLER_X = 0.12
ROLLER_Y = 0.15
PAD_X = -0.13
TETHER_ATTACH_Z = 0.09
MULLION_ROUND_R = 0.04
MULLION_MIN_H = 0.0005
ANCHOR_Y = -0.30
GLASS_BELOW_AREA_M = 16.0
START_CLEARANCE_M = 0.05
MU_DRY = 0.75
MU_WET = 0.30
MU_DUST = 0.40
DUST_FRICTION_SCALE_GM2 = 5.0
AIR_PRESSURE_PA = 101325.0
GLASS_BELOW_AIR_C = 3.0
CONDENSATION_RAMP_C = 3.0
LEGACY_ROOF_M = 160.0
LEGACY_FLOOR_M = 3.6
LEGACY_LEDGE_THICK_M = 0.12
LEGACY_TOWER_MARGIN_M = 12.0
VENT_FRAME_M = 0.003
CRADLE_DEPTH_M = 0.6
CRADLE_GAP_M = 0.01
ROBOT_GEOMS = 10
FIXED_VIEW_GEOMS = 4  # ground, tower, parapet, anchor post

NUM, INT = "num", "int"

# Each block: field -> (kind, min, max).
BLOCKS = {
    "area": {"width_m": (NUM, 0.8, 5.0), "height_m": (NUM, 1.0, 6.0), "drop_below_roof_m": (NUM, 5.0, 80.0),
             "margin_m": (NUM, 0.4, 3.0), "dirt_level": (NUM, 0.1, 2.0)},
    "panes": {"width_m": (NUM, 0.8, 3.0), "height_m": (NUM, 2.0, 5.0), "offset_x_m": (NUM, 0.0, 3.0), "offset_z_m": (NUM, 0.0, 5.0),
              "joint_depth_m": (NUM, 0.0, 0.04), "joint_gap_m": (NUM, 0.0, 0.03), "skip_every": (INT, 0, 5)},
    "weather": {"wetness": (NUM, 0.0, 1.0), "temperature_c": (NUM, -20.0, 50.0), "humidity_pct": (NUM, 0.0, 100.0), "dust_gm2": (NUM, 0.0, 60.0)},
    "wind": {"steady_ms": (NUM, 0.0, 25.0), "gust_ms": (NUM, 0.0, 60.0), "gust_start_s": (NUM, 0.0, 500.0), "gust_duration_s": (NUM, 0.5, 60.0),
             "gust_count": (INT, 0, 6), "gust_period_s": (NUM, 5.0, 200.0), "dir_deg": (NUM, -180.0, 180.0)},
    "robot": {"suction_pa": (NUM, 500.0, 5000.0), "seal_leak_mm2": (NUM, 20.0, 2000.0), "battery_start_frac": (NUM, 0.02, 1.0), "pad_force_n": (NUM, 5.0, 90.0)},
    "robot_start": {"x_m": (NUM, -6.0, 9.0), "above_top_m": (NUM, -14.0, 6.0)},
    "light": {"sun_level": (NUM, 0.2, 1.0), "azimuth_deg": (NUM, -180.0, 180.0), "haze": (NUM, 0.0, 1.0)},
    "surroundings": {"city_seed": (INT, 0, 1000000), "density": (NUM, 0.0, 1.0), "radius_m": (NUM, 100.0, 640.0)},
}
TOWER_FIELDS = {"height_m": (NUM, 40.0, 300.0), "width_m": (NUM, 10.0, 80.0), "floor_m": (NUM, 3.0, 5.0)}
CORNER_FIELDS = {"x_m": (NUM, -3.0, 9.0), "side": (INT, -1, 1)}
SETBACK_FIELDS = {"above_top_m": (NUM, 0.6, 5.0), "depth_m": (NUM, 0.5, 4.0)}
MATERIAL_FIELDS = {"roughness": (NUM, 0.0, 1.0), "metal": (NUM, 0.0, 1.0)}
POS_FIELDS = {"x_m": (NUM, -200.0, 200.0), "below_top_m": (NUM, -60.0, 300.0), "out_m": (NUM, 0.0, 300.0)}

SHAPES = {"box": 3, "cyl": 2, "sphere": 1, "capsule": 2}  # size entries: box w,out,h; cyl and capsule radius,length; sphere radius
SIZE_RANGE = (0.0005, 100.0)
PATCH_THICK_M = 0.0006
# kind -> (solid, extra numeric fields). "object" is free-form. The others are unrotated boxes at a fixed distance from the glass.
KINDS = {
    "object": (None, {}),
    "ledge": (True, {}),
    "sill": (True, {}),
    "fin": (True, {}),
    "sign": (True, {}),
    "balcony": (True, {}),
    "frame_step": (True, {}),
    "vent": (True, {"open_frac": (NUM, 0.1, 0.7)}),
    "cradle": (True, {"travel_m": (NUM, 0.0, 6.0), "period_s": (NUM, 10.0, 200.0)}),
    "wet_patch": (False, {"wetness": (NUM, 0.0, 1.0)}),
    "dirt_patch": (False, {"level": (NUM, 0.1, 3.0)}),
}
# kind -> ((w min, max), (out depth min, max), (h min, max), gap from the glass). From elements.py. The ledge depth floor is the v3 one.
KIND_BOXES = {
    "ledge": ((0.2, 12.0), (0.01, 0.30), (0.05, 0.30), 0.0),
    "sill": ((0.2, 8.0), (0.005, 0.06), (0.02, 0.10), 0.0),
    "fin": ((0.02, 0.20), (0.03, 0.60), (0.3, 6.0), 0.0),
    "sign": ((0.3, 4.0), (0.02, 0.15), (0.2, 3.0), 0.0),
    "balcony": ((1.0, 6.0), (0.6, 1.5), (0.10, 0.30), 0.0),
    "frame_step": ((0.1, 6.0), (0.002, 0.03), (0.1, 6.0), 0.0),
    "vent": ((0.2, 2.0), (VENT_FRAME_M, VENT_FRAME_M), (0.1, 1.0), 0.0),
    "cradle": ((1.0, 4.0), (CRADLE_DEPTH_M, CRADLE_DEPTH_M), (0.5, 1.5), CRADLE_GAP_M),
    "wet_patch": ((0.2, 6.0), (PATCH_THICK_M, PATCH_THICK_M), (0.2, 6.0), PATCH_THICK_M),
    "dirt_patch": ((0.2, 6.0), (PATCH_THICK_M, PATCH_THICK_M), (0.2, 6.0), PATCH_THICK_M),
}
SURFACE_KINDS = {"wet_patch", "dirt_patch"}  # they change friction and dirt, so they are physics with no solid
OBJECT_FIELDS = {"name", "kind", "shape", "size", "pos", "euler_deg", "material", "solid", "props"}
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")
VIEW_RESERVED_MATERIALS = {"city0", "city1"}  # the browser view does not draw geoms with these

# name: (rgba, metal, roughness). The view maps metal to MJCF specular and 1 - roughness to shininess.
DEFAULT_MATERIALS = {
    "ground": ((0.34, 0.33, 0.32, 1), 0.0, 0.5),
    "glass": ((0.20, 0.30, 0.40, 1), 0.8, 0.1),
    "alu": ((0.62, 0.63, 0.65, 1), 0.6, 0.4),
    "concrete": ((0.55, 0.52, 0.48, 1), 0.1, 0.5),
    "tower": ((0.26, 0.31, 0.37, 1), 0.4, 0.5),
    "city0": ((0.60, 0.57, 0.54, 1), 0.0, 0.5),
    "city1": ((0.46, 0.48, 0.52, 1), 0.0, 0.5),
    "cream": ((0.93, 0.89, 0.79, 1), 0.5, 0.4),
    "burgundy": ((0.42, 0.07, 0.13, 1), 0.4, 0.5),
    "rubber": ((0.04, 0.04, 0.04, 1), 0.2, 0.5),
    "tether": ((0.95, 0.45, 0.05, 1), 0.5, 0.5),
    "el_sign0": ((0.72, 0.16, 0.14, 1), 0.3, 0.5),
    "el_sign1": ((0.12, 0.30, 0.55, 1), 0.3, 0.5),
    "el_sign2": ((0.86, 0.72, 0.20, 1), 0.3, 0.5),
    "el_sign3": ((0.14, 0.42, 0.30, 1), 0.3, 0.5),
    "el_dark": ((0.10, 0.11, 0.12, 1), 0.3, 0.5),
    "el_steel": ((0.55, 0.57, 0.60, 1), 0.6, 0.4),
    "el_wet": ((0.08, 0.20, 0.45, 0.45), 0.9, 0.1),
    "el_cradle": ((0.78, 0.62, 0.12, 1), 0.4, 0.5),
}

# The legacy schema, copied from policy/highrise so this folder has no runtime link to it.
LEGACY_FIELDS = {
    "steady_wind_ms": (NUM, 0.0, 25.0), "gust_speed_ms": (NUM, 0.0, 60.0), "gust_start_s": (NUM, 0.0, 500.0), "gust_duration_s": (NUM, 0.5, 60.0),
    "gust_count": (INT, 0, 6), "gust_period_s": (NUM, 5.0, 200.0), "wind_dir_deg": (NUM, -180.0, 180.0), "wetness": (NUM, 0.0, 1.0),
    "mullion_depth_m": (NUM, 0.0, 0.04), "mullion_spacing_m": (NUM, 0.8, 3.0), "mullion_offset_m": (NUM, 0.0, 3.0), "joint_gap_m": (NUM, 0.0, 0.03),
    "edge_margin_m": (NUM, 0.4, 3.0), "area_width_m": (NUM, 0.8, 5.0), "area_height_m": (NUM, 1.0, 6.0), "drop_below_roof_m": (NUM, 5.0, 80.0),
    "suction_pa": (NUM, 500.0, 5000.0), "seal_leak_mm2": (NUM, 20.0, 2000.0), "battery_start_frac": (NUM, 0.02, 1.0), "pad_force_n": (NUM, 5.0, 90.0),
    "dirt_level": (NUM, 0.1, 2.0), "ledge_depth_m": (NUM, 0.01, 0.25), "ledge_below_top_m": (NUM, 0.5, 14.0), "ledge_x_m": (NUM, -6.0, 6.0),
    "ledge_width_m": (NUM, 0.2, 12.0), "temperature_c": (NUM, -20.0, 50.0), "humidity_pct": (NUM, 0.0, 100.0), "dust_gm2": (NUM, 0.0, 60.0),
    "sun_level": (NUM, 0.2, 1.0),
}
LEGACY_MOVES = {
    "steady_wind_ms": ("wind", "steady_ms"), "gust_speed_ms": ("wind", "gust_ms"), "gust_start_s": ("wind", "gust_start_s"),
    "gust_duration_s": ("wind", "gust_duration_s"), "gust_count": ("wind", "gust_count"), "gust_period_s": ("wind", "gust_period_s"),
    "wind_dir_deg": ("wind", "dir_deg"), "wetness": ("weather", "wetness"), "temperature_c": ("weather", "temperature_c"),
    "humidity_pct": ("weather", "humidity_pct"), "dust_gm2": ("weather", "dust_gm2"), "edge_margin_m": ("area", "margin_m"),
    "area_width_m": ("area", "width_m"), "area_height_m": ("area", "height_m"), "drop_below_roof_m": ("area", "drop_below_roof_m"),
    "dirt_level": ("area", "dirt_level"), "suction_pa": ("robot", "suction_pa"), "seal_leak_mm2": ("robot", "seal_leak_mm2"),
    "battery_start_frac": ("robot", "battery_start_frac"), "pad_force_n": ("robot", "pad_force_n"), "sun_level": ("light", "sun_level"),
    "joint_gap_m": ("panes", "joint_gap_m"), "mullion_spacing_m": ("panes", "width_m"), "mullion_offset_m": ("panes", "offset_x_m"),
    "mullion_depth_m": ("panes", "joint_depth_m"),
}
ANY_X, ANY_Z = (NUM, -6.0, 9.0), (NUM, -3.0, 14.0)
LEGACY_ELEMENTS = {
    "pane_grid": (1, {"pane_width_m": (NUM, 0.8, 3.0), "pane_height_m": (NUM, 2.0, 5.0), "offset_x_m": (NUM, 0.0, 3.0), "offset_z_m": (NUM, 0.0, 5.0),
                      "mullion_depth_m": (NUM, 0.0, 0.04), "skip_every": (INT, 0, 5)}),
    "ledge": (6, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.2, 12.0), "depth_m": (NUM, 0.02, 0.30), "thick_m": (NUM, 0.05, 0.30)}),
    "sill": (6, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.2, 8.0), "depth_m": (NUM, 0.005, 0.06), "thick_m": (NUM, 0.02, 0.10)}),
    "fin": (8, {"x_m": ANY_X, "below_top_m": ANY_Z, "height_m": (NUM, 0.3, 6.0), "depth_m": (NUM, 0.03, 0.60), "thick_m": (NUM, 0.02, 0.20)}),
    "sign": (4, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.3, 4.0), "height_m": (NUM, 0.2, 3.0), "depth_m": (NUM, 0.02, 0.15), "color": (INT, 0, 3)}),
    "balcony": (3, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 1.0, 6.0), "depth_m": (NUM, 0.6, 1.5), "slab_m": (NUM, 0.10, 0.30)}),
    "frame_step": (6, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.1, 6.0), "height_m": (NUM, 0.1, 6.0), "step_m": (NUM, 0.002, 0.03)}),
    "vent": (4, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.2, 2.0), "height_m": (NUM, 0.1, 1.0), "open_frac": (NUM, 0.1, 0.7)}),
    "corner": (1, {"x_m": (NUM, -3.0, 9.0), "side": (INT, -1, 1)}),
    "setback": (1, {"above_top_m": (NUM, 0.6, 5.0), "depth_m": (NUM, 0.5, 4.0)}),
    "wet_patch": (6, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.2, 6.0), "height_m": (NUM, 0.2, 6.0), "wetness": (NUM, 0.0, 1.0)}),
    "dirt_patch": (6, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 0.2, 6.0), "height_m": (NUM, 0.2, 6.0), "level": (NUM, 0.1, 3.0)}),
    "cradle": (1, {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (NUM, 1.0, 4.0), "height_m": (NUM, 0.5, 1.5), "travel_m": (NUM, 0.0, 6.0), "period_s": (NUM, 10.0, 200.0)}),
}
MAX_LEGACY_ELEMENTS = 24


class WorldError(ValueError):
    pass


def _reject_constant(_):
    raise WorldError("non-finite number")


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise WorldError("repeated key")
        out[k] = v
    return out


def _number(v, rule, where):
    kind, lo, hi = rule
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise WorldError(f"{where} must be a number")
    if kind == INT and not isinstance(v, int):
        raise WorldError(f"{where} must be an integer")
    if not lo <= v <= hi:  # exact for huge integers, and False for NaN
        raise WorldError(f"{where} is outside [{lo}, {hi}]")
    return int(v) if kind == INT else float(v)


def _fields(raw, rules, where):
    if not isinstance(raw, dict):
        raise WorldError(f"{where} must be an object")
    if set(raw) != set(rules):
        raise WorldError(f"{where} has {len(set(rules) - set(raw))} missing and {len(set(raw) - set(rules))} unknown fields")
    return {name: _number(raw[name], rule, f"{where}.{name}") for name, rule in rules.items()}


def _vector(raw, n, lo, hi, where):
    if not isinstance(raw, list) or len(raw) != n:
        raise WorldError(f"{where} must be a list of {n} numbers")
    return [_number(v, (NUM, lo, hi), where) for v in raw]


def _name(raw, where):
    if not isinstance(raw, str) or not NAME_RE.fullmatch(raw):
        raise WorldError(f"{where} must match {NAME_RE.pattern}")
    return raw


def _keys(raw, expected, where):
    if not isinstance(raw, dict):
        raise WorldError(f"{where} must be an object")
    if set(raw) != set(expected):
        raise WorldError(f"{where} has {len(set(expected) - set(raw))} missing and {len(set(raw) - set(expected))} unknown fields")


def _tower(raw):
    _keys(raw, set(TOWER_FIELDS) | {"shape", "corner", "setback"}, "tower")
    out = {name: _number(raw[name], rule, f"tower.{name}") for name, rule in TOWER_FIELDS.items()}
    if raw["shape"] != "flat":
        raise WorldError("tower.shape must be flat")
    out["shape"] = "flat"
    out["corner"] = None if raw["corner"] is None else _fields(raw["corner"], CORNER_FIELDS, "tower.corner")
    out["setback"] = None if raw["setback"] is None else _fields(raw["setback"], SETBACK_FIELDS, "tower.setback")
    if out["corner"] and out["corner"]["side"] == 0:
        raise WorldError("tower.corner.side must be -1 or 1")
    return out


def _materials(raw):
    if not isinstance(raw, dict):
        raise WorldError("materials must be an object")
    if len(raw) > MAX_MATERIALS:
        raise WorldError(f"more than {MAX_MATERIALS} materials")
    if set(DEFAULT_MATERIALS) - set(raw):
        raise WorldError("a built-in material is missing")
    out = {}
    for key, m in raw.items():
        name = _name(key, "material name")
        _keys(m, set(MATERIAL_FIELDS) | {"rgba"}, "material")
        out[name] = {"rgba": _vector(m["rgba"], 4, 0.0, 1.0, "material.rgba"),
                     **{f: _number(m[f], rule, f"material.{f}") for f, rule in MATERIAL_FIELDS.items()}}
    return out


def _object(raw, i, materials):
    where = f"objects[{i}]"
    _keys(raw, OBJECT_FIELDS, where)
    name = _name(raw["name"], f"{where}.name")
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise WorldError(f"{where}.kind is unknown")
    shape = raw["shape"]
    if not isinstance(shape, str) or shape not in SHAPES:
        raise WorldError(f"{where}.shape is unknown")
    if not isinstance(raw["solid"], bool):
        raise WorldError(f"{where}.solid must be true or false")
    material = _name(raw["material"], f"{where}.material")
    if material not in materials:
        raise WorldError(f"{where}.material does not exist")
    if material in VIEW_RESERVED_MATERIALS:
        raise WorldError(f"{where}.material is reserved")
    obj = {"name": name, "kind": kind, "shape": shape, "solid": raw["solid"], "material": material,
           "size": _vector(raw["size"], SHAPES[shape], *SIZE_RANGE, f"{where}.size"),
           "pos": _fields(raw["pos"], POS_FIELDS, f"{where}.pos"),
           "euler_deg": _vector(raw["euler_deg"], 3, -180.0, 180.0, f"{where}.euler_deg"),
           "props": _fields(raw["props"], KINDS[kind][1], f"{where}.props")}
    if kind != "object":
        if KINDS[kind][0] != obj["solid"]:
            raise WorldError(f"{where}.solid does not fit its kind")
        if shape != "box" or any(obj["euler_deg"]):
            raise WorldError(f"{where} must be an unrotated box")
        w, d, h, gap = KIND_BOXES[kind]
        for value, (lo, hi) in zip(obj["size"], (w, d, h)):
            if not lo <= value <= hi:
                raise WorldError(f"{where}.size is outside the range of its kind")
        if abs(obj["pos"]["out_m"] - (gap + obj["size"][1] / 2)) > 1e-9:
            raise WorldError(f"{where} must sit at the fixed distance of its kind")
    return obj


def _rotation(euler_deg):
    """MuJoCo's default intrinsic xyz sequence, in degrees. Rows are world axes."""
    a, b, c = (math.radians(v) for v in euler_deg)
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return ((cb * cc, -cb * sc, sb),
            (ca * sc + sa * sb * cc, ca * cc - sa * sb * sc, -sa * cb),
            (sa * sc - ca * sb * cc, sa * cc + ca * sb * sc, ca * cb))


def half_extents(obj):
    """World-axis half widths of the shape's bounding box, x, y, z."""
    R = _rotation(obj["euler_deg"])
    s = obj["size"]
    if obj["shape"] == "box":
        h = (s[0] / 2, s[1] / 2, s[2] / 2)
        return tuple(sum(abs(R[i][j]) * h[j] for j in range(3)) for i in range(3))
    if obj["shape"] == "sphere":
        return (s[0], s[0], s[0])
    r, half = s[0], s[1] / 2
    if obj["shape"] == "capsule":
        return tuple(abs(R[i][2]) * half + r for i in range(3))
    return tuple(abs(R[i][2]) * half + r * math.sqrt(max(0.0, 1 - R[i][2] ** 2)) for i in range(3))


def gap_m(obj):
    """Distance from the shape's nearest point to the plane of the glass. Measured to the plane and not the
    glass rectangle, because the robot body overhangs the glass edge and must still hit a solid there."""
    return max(0.0, obj["pos"]["out_m"] - half_extents(obj)[1])


def effect_of(obj):
    if obj["kind"] in SURFACE_KINDS:
        return "physics"
    return "physics" if obj["solid"] and gap_m(obj) <= NEAR_GLASS_M else "picture"


def area_rect(world):
    a = world["area"]
    top = world["tower"]["height_m"] - a["drop_below_roof_m"]
    return {"x0": 0.0, "x1": a["width_m"], "z0": top - a["height_m"], "z1": top}


def glass_rect(world):
    a = area_rect(world)
    m = world["area"]["margin_m"]
    rect = {"x0": a["x0"] - m, "x1": a["x1"] + m, "z0": a["z0"] - GLASS_BELOW_AREA_M, "z1": a["z1"] + m}
    corner, setback = world["tower"]["corner"], world["tower"]["setback"]
    if corner:
        x = a["x0"] + corner["x_m"]
        if corner["side"] > 0:
            rect["x1"] = min(rect["x1"], x)
        else:
            rect["x0"] = max(rect["x0"], x)
    if setback:
        rect["z1"] = a["z1"] + setback["above_top_m"]
    return rect


def mullion_xs(world):
    g = glass_rect(world)
    p = world["panes"]
    s, off, skip = p["width_m"], p["offset_x_m"], p["skip_every"]
    k = math.ceil((g["x0"] - off) / s)
    out = []
    while off + k * s < g["x1"]:
        if not skip or k % skip:
            out.append(off + k * s)
        k += 1
    return out


def transom_zs(world):
    g = glass_rect(world)
    p = world["panes"]
    s, off = p["height_m"], p["offset_z_m"]
    k = math.ceil((g["z0"] + 0.01 - off) / s)
    out = []
    while off + k * s < g["z1"]:
        out.append(off + k * s)
        k += 1
    return out


def object_center(world, obj):
    a = area_rect(world)
    return a["x0"] + obj["pos"]["x_m"], -obj["pos"]["out_m"], a["z1"] - obj["pos"]["below_top_m"]


def start_pose(world):
    a = area_rect(world)
    s = world["robot_start"]
    return a["x0"] + s["x_m"], a["z1"] + s["above_top_m"]


def city_blocks(world):
    """Far blocks as (ix, iy, height). City seed 0 at full density and radius gives the old fixed city."""
    s = world["surroundings"]
    seed = s["city_seed"]
    out = []
    for ix in range(-6, 7):
        for iy in range(1, 6):
            if abs(ix) * 95 > s["radius_m"] or iy * 110 + 30 > s["radius_m"]:
                continue
            if (ix * 31 + iy * 17 + seed * 13) % 100 >= s["density"] * 100:
                continue
            out.append((ix, iy, 12 + (ix * 37 + iy * 53 + seed * 17) % 45))
    return out


def vent_bar_count(obj):
    return max(2, int(obj["size"][2] / 0.06))


def geom_counts(world):
    """(all geoms in the view model, solid geoms). Picture solids count as solids, so moving one cannot pass a cap."""
    joints = len(mullion_xs(world)) + len(transom_zs(world))
    solids = 1 + joints + sum(o["solid"] for o in world["objects"])
    geoms = 1 + joints + ROBOT_GEOMS + FIXED_VIEW_GEOMS + len(city_blocks(world))
    if world["tower"]["setback"]:
        geoms += 2
    for o in world["objects"]:
        if o["kind"] == "vent":
            geoms += 1 + vent_bar_count(o)
        else:
            geoms += {"balcony": 4, "cradle": 2, "dirt_patch": 0}.get(o["kind"], 1)
    return geoms, solids


def _check_geometry(world):
    t, a = world["tower"], world["area"]
    rect = area_rect(world)
    g = glass_rect(world)
    if rect["z0"] - GLASS_BELOW_AREA_M < 0:
        raise WorldError("the glass runs below the ground")
    if t["setback"] and g["z1"] >= t["height_m"]:
        raise WorldError("the setback must stay below the roof")
    if a["width_m"] + 2 * a["margin_m"] > t["width_m"]:
        raise WorldError("the glass is wider than the tower")
    sx, sz = start_pose(world)
    h = BODY_SIDE / 2 + START_CLEARANCE_M
    if sx - h < g["x0"] or sx + h > g["x1"] or sz + h > g["z1"] or sz - h < g["z0"]:
        raise WorldError("start pose is not on glass")
    for o in world["objects"]:
        if not o["solid"] or effect_of(o) != "physics":
            continue
        x, _, z = object_center(world, o)
        ex, _, ez = half_extents(o)
        if x - ex < sx + h and x + ex > sx - h and z - ez < sz + h and z + ez > sz - h:
            raise WorldError("an object blocks the start pose")


def validate(raw):
    if not isinstance(raw, dict):
        raise WorldError("world must be an object")
    top = {"schema", "tower", "objects", "materials", "sky"} | set(BLOCKS)
    if set(raw) != top:
        raise WorldError(f"world has {len(top - set(raw))} missing and {len(set(raw) - top)} unknown fields")
    if raw["schema"] != SCHEMA:
        raise WorldError("bad schema")
    world = {"schema": SCHEMA, "tower": _tower(raw["tower"])}
    for block, rules in BLOCKS.items():
        world[block] = _fields(raw[block], rules, block)
    _keys(raw["sky"], {"top", "bottom"}, "sky")
    world["sky"] = {k: _vector(raw["sky"][k], 3, 0.0, 1.0, f"sky.{k}") for k in ("top", "bottom")}
    world["materials"] = _materials(raw["materials"])
    if not isinstance(raw["objects"], list):
        raise WorldError("objects must be a list")
    if len(raw["objects"]) > MAX_OBJECTS:
        raise WorldError(f"more than {MAX_OBJECTS} objects")
    world["objects"] = [_object(o, i, world["materials"]) for i, o in enumerate(raw["objects"])]
    names = [o["name"] for o in world["objects"]]
    if len(set(names)) != len(names):
        raise WorldError("object names must be unique")
    if sum(o["kind"] == "cradle" for o in world["objects"]) > 1:
        raise WorldError("more than one cradle")
    _check_geometry(world)
    geoms, solids = geom_counts(world)
    if geoms > MAX_GEOMS:
        raise WorldError(f"more than {MAX_GEOMS} geoms")
    if solids > MAX_SOLIDS:
        raise WorldError(f"more than {MAX_SOLIDS} solids")
    return world


def _legacy_box(name, kind, material, x, below, w, d, h, y0=0.0, props=None, solid=True):
    """A box from y = -y0 - d to y = -y0, in the old element frame."""
    return {"name": name, "kind": kind, "shape": "box", "size": [w, d, h], "pos": {"x_m": x, "below_top_m": below, "out_m": y0 + d / 2},
            "euler_deg": [0.0, 0.0, 0.0], "material": material, "solid": solid, "props": props or {}}


def _upgrade_element(e, i):
    t = e["type"]
    name = f"{t}{i}"
    x, below = e["x_m"], e["below_top_m"]
    if t in ("ledge", "sill"):
        return _legacy_box(name, t, "concrete", x, below, e["width_m"], e["depth_m"], e["thick_m"])
    if t == "fin":
        return _legacy_box(name, t, "alu", x, below, e["thick_m"], e["depth_m"], e["height_m"])
    if t == "sign":
        return _legacy_box(name, t, f"el_sign{e['color']}", x, below, e["width_m"], e["depth_m"], e["height_m"])
    if t == "balcony":
        return _legacy_box(name, t, "concrete", x, below, e["width_m"], e["depth_m"], e["slab_m"])
    if t == "frame_step":
        return _legacy_box(name, t, "alu", x, below, e["width_m"], e["step_m"], e["height_m"])
    if t == "vent":
        return _legacy_box(name, t, "el_dark", x, below, e["width_m"], VENT_FRAME_M, e["height_m"], props={"open_frac": e["open_frac"]})
    if t == "wet_patch":
        return _legacy_box(name, t, "el_wet", x, below, e["width_m"], PATCH_THICK_M, e["height_m"], y0=PATCH_THICK_M, props={"wetness": e["wetness"]}, solid=False)
    if t == "dirt_patch":
        return _legacy_box(name, t, "el_wet", x, below, e["width_m"], PATCH_THICK_M, e["height_m"], y0=PATCH_THICK_M, props={"level": e["level"]}, solid=False)
    return _legacy_box(name, t, "el_cradle", x, below, e["width_m"], CRADLE_DEPTH_M, e["height_m"], y0=CRADLE_GAP_M,
                       props={"travel_m": e["travel_m"], "period_s": e["period_s"]})


def _legacy_elements(raw):
    if not isinstance(raw, list):
        raise WorldError("elements must be a list")
    if len(raw) > MAX_LEGACY_ELEMENTS:
        raise WorldError("too many elements")
    out, counts = [], {}
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("type"), str) or item["type"] not in LEGACY_ELEMENTS:
            raise WorldError(f"elements[{i}] has an unknown type")
        kind = item["type"]
        cap, rules = LEGACY_ELEMENTS[kind]
        counts[kind] = counts.get(kind, 0) + 1
        if counts[kind] > cap:
            raise WorldError(f"too many {kind} elements")
        _keys(item, set(rules) | {"type"}, f"elements[{i}]")
        checked = {name: _number(item[name], rule, f"elements[{i}].{name}") for name, rule in rules.items()}
        checked["type"] = kind
        if kind == "corner" and checked["side"] == 0:
            raise WorldError(f"elements[{i}].side must be -1 or 1")
        out.append(checked)
    return out


def upgrade(raw):
    """A v3 or v4 world to a validated v5 world. It checks the old schema first, with the old ranges and caps."""
    if not isinstance(raw, dict):
        raise WorldError("world must be an object")
    schema = raw.get("schema")
    if not isinstance(schema, str) or schema not in (SCHEMA_V3, SCHEMA_V4):
        raise WorldError("upgrade takes a v3 or v4 world")
    expected = set(LEGACY_FIELDS) | {"schema"}
    if schema == SCHEMA_V4 and "elements" in raw:
        expected.add("elements")
    if set(raw) != expected:
        raise WorldError(f"world has {len(expected - set(raw))} missing and {len(set(raw) - expected)} unknown fields")
    old = {name: _number(raw[name], rule, name) for name, rule in LEGACY_FIELDS.items()}
    elements = _legacy_elements(raw.get("elements", []))

    world = {"schema": SCHEMA, "panes": {"height_m": LEGACY_FLOOR_M, "offset_z_m": 0.0, "skip_every": 0}}
    for field, (block, key) in LEGACY_MOVES.items():
        world.setdefault(block, {})[key] = old[field]
    corner = setback = None
    objects = [_legacy_box("ledge", "ledge", "concrete", old["ledge_x_m"] + old["area_width_m"] / 2, old["ledge_below_top_m"],
                           old["ledge_width_m"], old["ledge_depth_m"], LEGACY_LEDGE_THICK_M)]
    for i, e in enumerate(elements):
        if e["type"] == "pane_grid":
            world["panes"].update(width_m=e["pane_width_m"], height_m=e["pane_height_m"], offset_x_m=e["offset_x_m"],
                                  offset_z_m=e["offset_z_m"], joint_depth_m=e["mullion_depth_m"], skip_every=e["skip_every"])
        elif e["type"] == "corner":
            corner = {"x_m": e["x_m"], "side": e["side"]}
        elif e["type"] == "setback":
            setback = {"above_top_m": e["above_top_m"], "depth_m": e["depth_m"]}
        else:
            objects.append(_upgrade_element(e, i))
    world["objects"] = objects
    world["robot_start"] = {"x_m": BODY_SIDE / 2 - 0.03, "above_top_m": 0.13}
    world["tower"] = {"height_m": LEGACY_ROOF_M, "width_m": 0.0, "floor_m": LEGACY_FLOOR_M, "shape": "flat", "corner": corner, "setback": setback}
    glass = glass_rect(world)
    # The old tower stood 12 m past the glass on each side, measured after a corner cut the glass.
    world["tower"]["width_m"] = glass["x1"] - glass["x0"] + 2 * LEGACY_TOWER_MARGIN_M
    world["materials"] = {k: {"rgba": list(map(float, rgba)), "metal": metal, "roughness": rough} for k, (rgba, metal, rough) in DEFAULT_MATERIALS.items()}
    world["light"].update(azimuth_deg=round(math.degrees(math.atan2(-0.45, 0.6)), 4), haze=0.5)
    world["surroundings"] = {"city_seed": 0, "density": 1.0, "radius_m": 640.0}
    world["sky"] = {"top": [0.42, 0.58, 0.80], "bottom": [0.95, 0.82, 0.70]}
    return validate(world)


def parse(data):
    """Strict JSON from bytes, then a validated v5 world. Old schemas upgrade."""
    if len(data) > MAX_WORLD_FILE_BYTES:
        raise WorldError("world file too large")
    try:
        raw = json.loads(data.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys)
    except WorldError:
        raise
    except (ValueError, RecursionError, OverflowError):  # bad UTF-8, bad JSON, huge integer, deep nesting
        raise WorldError("world file is not strict JSON") from None
    if isinstance(raw, dict) and raw.get("schema") in (SCHEMA_V3, SCHEMA_V4):
        return upgrade(raw)
    return validate(raw)


def load(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise WorldError("world file is not a regular file")
    if info.st_size > MAX_WORLD_FILE_BYTES:
        raise WorldError("world file too large")
    with open(path, "rb") as f:
        return parse(f.read(MAX_WORLD_FILE_BYTES + 1))


def world_hash(world):
    return hashlib.sha256(json.dumps(world, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def air(world):
    w = world["weather"]
    t = w["temperature_c"]
    kelvin = t + 273.15
    e_s = 610.94 * math.exp(17.625 * t / (t + 243.04))
    e = w["humidity_pct"] / 100.0 * e_s
    rho = (AIR_PRESSURE_PA - e) / (287.05 * kelvin) + e / (461.5 * kelvin)
    if e <= 0:
        return rho, -273.15
    x = math.log(e / 610.94)
    return rho, 243.04 * x / (17.625 - x)


def effective_wetness(world):
    _, dew = air(world)
    w = world["weather"]
    glass = w["temperature_c"] - GLASS_BELOW_AIR_C
    return max(w["wetness"], min(1.0, max(0.0, (dew - glass) / CONDENSATION_RAMP_C)))


def friction(world):
    clean = MU_DRY + (MU_WET - MU_DRY) * effective_wetness(world)
    return clean + (MU_DUST - clean) * (1 - math.exp(-world["weather"]["dust_gm2"] / DUST_FRICTION_SCALE_GM2))
