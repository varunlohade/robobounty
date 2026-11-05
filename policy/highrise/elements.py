"""Optional scene elements for world schema v4. A world lists elements; our code compiles them to MJCF primitives.

A spec holds an allowlisted type name and clamped numbers only. No text from a spec reaches the MJCF.
Positions: x_m from the left edge of the assigned area, below_top_m down from its top edge. Physics effects are in PARAMETERS.md.
"""
import math

ANY_X = (-6.0, 9.0)
ANY_Z = (-3.0, 14.0)
MAX_ELEMENTS = 24

SPECS = {
    "pane_grid": {"cap": 1, "fields": {"pane_width_m": (0.8, 3.0), "pane_height_m": (2.0, 5.0), "offset_x_m": (0.0, 3.0),
                                       "offset_z_m": (0.0, 5.0), "mullion_depth_m": (0.0, 0.04), "skip_every": (0, 5)}},
    "ledge": {"cap": 6, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.2, 12.0), "depth_m": (0.02, 0.30), "thick_m": (0.05, 0.30)}},
    "sill": {"cap": 6, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.2, 8.0), "depth_m": (0.005, 0.06), "thick_m": (0.02, 0.10)}},
    "fin": {"cap": 8, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "height_m": (0.3, 6.0), "depth_m": (0.03, 0.60), "thick_m": (0.02, 0.20)}},
    "sign": {"cap": 4, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.3, 4.0), "height_m": (0.2, 3.0), "depth_m": (0.02, 0.15), "color": (0, 3)}},
    "balcony": {"cap": 3, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (1.0, 6.0), "depth_m": (0.6, 1.5), "slab_m": (0.10, 0.30)}},
    "frame_step": {"cap": 6, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.1, 6.0), "height_m": (0.1, 6.0), "step_m": (0.002, 0.03)}},
    "vent": {"cap": 4, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.2, 2.0), "height_m": (0.1, 1.0), "open_frac": (0.1, 0.7)}},
    "corner": {"cap": 1, "fields": {"x_m": (-3.0, 9.0), "side": (-1, 1)}},
    "setback": {"cap": 1, "fields": {"above_top_m": (0.6, 5.0), "depth_m": (0.5, 4.0)}},
    "wet_patch": {"cap": 6, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.2, 6.0), "height_m": (0.2, 6.0), "wetness": (0.0, 1.0)}},
    "dirt_patch": {"cap": 6, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (0.2, 6.0), "height_m": (0.2, 6.0), "level": (0.1, 3.0)}},
    "cradle": {"cap": 1, "fields": {"x_m": ANY_X, "below_top_m": ANY_Z, "width_m": (1.0, 4.0), "height_m": (0.5, 1.5), "travel_m": (0.0, 6.0), "period_s": (10.0, 200.0)}},
}
INTEGER_FIELDS = {"skip_every", "color", "side"}

VENT_FRAME_M = 0.003
CRADLE_DEPTH_M = 0.6
CRADLE_GAP_M = 0.01  # front of the cradle bumper off the glass
SIGN_COLORS = ("0.72 0.16 0.14 1", "0.12 0.30 0.55 1", "0.86 0.72 0.20 1", "0.14 0.42 0.30 1")


def validate(raw, error):
    """Returns the checked list. `error` is the exception class to raise. Counts are checked before any element is read."""
    if not isinstance(raw, list):
        raise error("elements must be a list")
    if len(raw) > MAX_ELEMENTS:
        raise error("too many elements")
    out, counts = [], {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str) or item["type"] not in SPECS:
            raise error("unknown element type")
        kind = item["type"]
        spec = SPECS[kind]
        counts[kind] = counts.get(kind, 0) + 1
        if counts[kind] > spec["cap"]:
            raise error(f"too many {kind}")
        if set(item) != set(spec["fields"]) | {"type"}:
            raise error(f"bad fields on {kind}")
        element = {"type": kind}
        for name, (lo, hi) in spec["fields"].items():
            v = item[name]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise error(f"{kind}.{name} must be a number")
            if name in INTEGER_FIELDS and not isinstance(v, int):
                raise error(f"{kind}.{name} must be an integer")
            if not math.isfinite(v) or not lo <= v <= hi:
                raise error(f"{kind}.{name} outside [{lo}, {hi}]")
            element[name] = int(v) if name in INTEGER_FIELDS else float(v)
        if kind == "corner" and element["side"] == 0:
            raise error("corner.side must be -1 or 1")
        out.append(element)
    return out


def of_type(world, kind):
    return [e for e in world.get("elements", ()) if e["type"] == kind]


def rects(world, area):
    """Raised solid elements as (x0, x1, z0, z1, height off the glass)."""
    top, left = area["z1"], area["x0"]
    out = []
    for e in world.get("elements", ()):
        t = e["type"]
        if t in ("ledge", "sill"):
            w, h, d = e["width_m"], e["thick_m"], e["depth_m"]
        elif t == "fin":
            w, h, d = e["thick_m"], e["height_m"], e["depth_m"]
        elif t == "sign":
            w, h, d = e["width_m"], e["height_m"], e["depth_m"]
        elif t == "balcony":
            w, h, d = e["width_m"], e["slab_m"], e["depth_m"]
        elif t == "frame_step":
            w, h, d = e["width_m"], e["height_m"], e["step_m"]
        elif t == "vent":
            w, h, d = e["width_m"], e["height_m"], VENT_FRAME_M
        else:
            continue
        x, z = left + e["x_m"], top - e["below_top_m"]
        out.append((x - w / 2, x + w / 2, z - h / 2, z + h / 2, d))
    return out


def regions(world, area, kind, value):
    """Flat patches of one kind as (x0, x1, z0, z1, value)."""
    top, left = area["z1"], area["x0"]
    out = []
    for e in of_type(world, kind):
        x, z = left + e["x_m"], top - e["below_top_m"]
        out.append((x - e["width_m"] / 2, x + e["width_m"] / 2, z - e["height_m"] / 2, z + e["height_m"] / 2, e[value]))
    return out


def cradle_z(element, top, t):
    return top - element["below_top_m"] + element["travel_m"] / 2 * math.sin(2 * math.pi * t / element["period_s"])


def _box(x0, x1, z0, z1, y0, y1, attrs):
    return (f'<geom type="box" size="{(x1 - x0) / 2:.5f} {(y1 - y0) / 2:.5f} {(z1 - z0) / 2:.5f}" '
            f'pos="{(x0 + x1) / 2:.5f} {(y0 + y1) / 2:.5f} {(z0 + z1) / 2:.5f}" {attrs}/>')


SOLID = 'conaffinity="1" friction="0.3 0.005 0.0001" material="{}"'
VISUAL = 'class="vis" material="{}"'


def extend_xml(xml, world, area, glass, roof_z):
    """Adds the elements to a built world. Only called for a world that has them."""
    top, left = area["z1"], area["x0"]
    assets = "".join(f'<material name="el_sign{i}" rgba="{c}" specular="0.3"/>' for i, c in enumerate(SIGN_COLORS))
    assets += ('<material name="el_dark" rgba="0.10 0.11 0.12 1" specular="0.3"/>'
               '<material name="el_steel" rgba="0.55 0.57 0.60 1" specular="0.6" shininess="0.6"/>'
               '<material name="el_wet" rgba="0.08 0.20 0.45 0.45" specular="0.9" shininess="0.9"/>'
               '<material name="el_cradle" rgba="0.78 0.62 0.12 1" specular="0.4"/>')
    static, moving = [], []
    for e in world["elements"]:
        t = e["type"]
        x = left + e.get("x_m", 0.0)
        z = top - e.get("below_top_m", 0.0)
        if t in ("ledge", "sill"):
            w, h, d = e["width_m"], e["thick_m"], e["depth_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -d, 0.0, SOLID.format("concrete")))
        elif t == "fin":
            w, h, d = e["thick_m"], e["height_m"], e["depth_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -d, 0.0, SOLID.format("alu")))
        elif t == "sign":
            w, h, d = e["width_m"], e["height_m"], e["depth_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -d, 0.0, SOLID.format(f"el_sign{e['color']}")))
        elif t == "balcony":
            w, h, d = e["width_m"], e["slab_m"], e["depth_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -d, 0.0, SOLID.format("concrete")))
            rail = z + h / 2 + 1.0
            static.append(_box(x - w / 2, x + w / 2, rail - 0.03, rail + 0.03, -d, -d + 0.05, VISUAL.format("el_steel")))
            for side in (-1, 1):
                static.append(_box(x + side * w / 2 - 0.03, x + side * w / 2 + 0.03, z, rail, -d, -d + 0.05, VISUAL.format("el_steel")))
        elif t == "frame_step":
            w, h, d = e["width_m"], e["height_m"], e["step_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -d, 0.0, SOLID.format("alu")))
        elif t == "vent":
            w, h = e["width_m"], e["height_m"]
            static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -VENT_FRAME_M, 0.0, SOLID.format("el_dark")))
            bars = max(2, int(h / 0.06))
            for i in range(bars):
                bz = z - h / 2 + (i + 0.5) * h / bars
                static.append(_box(x - w / 2 + 0.01, x + w / 2 - 0.01, bz - 0.008, bz + 0.008, -VENT_FRAME_M - 0.002, -VENT_FRAME_M,
                                   VISUAL.format("el_steel")))
        elif t in ("wet_patch", "dirt_patch"):
            if t == "wet_patch":
                w, h = e["width_m"], e["height_m"]
                static.append(_box(x - w / 2, x + w / 2, z - h / 2, z + h / 2, -0.0012, -0.0006, VISUAL.format("el_wet")))
        elif t == "cradle":
            w, h = e["width_m"], e["height_m"]
            y0, y1 = -CRADLE_GAP_M - CRADLE_DEPTH_M, -CRADLE_GAP_M
            moving.append(
                f'<body name="cradle" mocap="true" pos="{x:.5f} {(y0 + y1) / 2:.5f} {z:.5f}">'
                f'<geom type="box" size="{w / 2:.5f} {CRADLE_DEPTH_M / 2:.5f} {h / 2:.5f}" {SOLID.format("el_cradle")}/>'
                f'<geom class="vis" type="box" size="{w / 2 + 0.02:.5f} 0.02 0.03" pos="0 -0.28 {h / 2 + 0.5:.5f}" material="el_steel"/></body>')
    hw_tower = 12.0
    x0, x1 = glass["x0"] - hw_tower, glass["x1"] + hw_tower
    for e in of_type(world, "corner"):
        cx = left + e["x_m"]
        if e["side"] > 0:
            x1 = cx
        else:
            x0 = cx
    tower_top = roof_z
    upper = []
    for e in of_type(world, "setback"):
        tower_top = top + e["above_top_m"]
        d = e["depth_m"]
        upper.append(f'<geom class="vis" type="box" size="{(x1 - x0) / 2:.4f} {14 - d / 2:.4f} {(roof_z - tower_top) / 2:.4f}" '
                     f'pos="{(x0 + x1) / 2:.4f} {14.2 + d / 2:.4f} {(roof_z + tower_top) / 2:.4f}" material="tower"/>')
        upper.append(f'<geom class="vis" type="box" size="{(x1 - x0) / 2:.4f} {d / 2:.4f} 0.12" '
                     f'pos="{(x0 + x1) / 2:.4f} {d / 2:.4f} {tower_top:.4f}" material="concrete"/>')
    start = xml.index('<geom name="tower"')
    end = xml.index("/>", start) + 2
    tower = (f'<geom name="tower" class="vis" type="box" size="{(x1 - x0) / 2:.4f} 14 {tower_top / 2:.4f}" '
             f'pos="{(x0 + x1) / 2:.4f} 14.2 {tower_top / 2:.4f}" material="tower"/>' + "".join(upper))
    xml = xml[:start] + tower + xml[end:]
    xml = xml.replace("</asset>", assets + "\n  </asset>", 1)
    xml = xml.replace('<body name="scenery">', "\n    ".join(static) + '\n    <body name="scenery">', 1)
    xml = xml.replace('<body name="robot"', "\n    ".join(moving) + '\n    <body name="robot"', 1)
    if of_type(world, "wet_patch") or of_type(world, "dirt_patch"):
        # Roller friction then wins over the glass, so the sim can set it per roller from the patch under it.
        xml = xml.replace('contype="1" density="400"', 'contype="1" priority="2" density="400"', 1)
    return xml
