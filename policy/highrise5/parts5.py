"""Library parts: each is several plain shapes with its own brackets or mounts, so it looks fitted to the building. build() returns ordinary v5 objects, so physics and picture use the same compiled shapes.

Heights are metres up from the part's origin. "out" is metres out from the glass plane, and a negative value is behind it, on the roof. world5.floating() checks every part like any other object.
"""
import math

import world5 as W

FACADE, ROOF = "facade", "roof"
# part: (where it goes, where else it may go, plain words for the chat)
PARTS = {
    "ac_unit": (FACADE, (ROOF,), "an AC unit on steel brackets"),
    "sign": (FACADE, (), "a sign on stand-off brackets"),
    "vent_hood": (FACADE, (), "a galvanised vent hood"),
    "window_frame_bracket": (FACADE, (), "a bracket fixed to a window frame"),
    "maintenance_cradle_parked": (ROOF, (), "a parked maintenance cradle hanging from roof davits"),
    "antenna": (ROOF, (), "a guyed antenna mast"),
    "crane": (ROOF, (), "a tower crane on a concrete pad"),
}


class Maker:
    def __init__(self, name, x, base_below, scale, material):
        self.name, self.x, self.base, self.s, self.material, self.out, self.n = name, x, base_below, scale, material, [], 0

    def _add(self, label, shape, size, x, up, out, euler, material, solid):
        self.n += 1
        self.out.append({"name": f"{self.name}_{label}{self.n}", "kind": "object", "shape": shape, "size": [v * self.s if i < 3 else v for i, v in enumerate(size)],
                         "pos": {"x_m": self.x + x * self.s, "below_top_m": self.base - up * self.s, "out_m": out * self.s}, "euler_deg": euler, "material": material, "solid": solid, "props": {}})

    def box(self, label, w, d, h, x, up, out, material=None, solid=True):
        """A box centred at x, up and out."""
        self._add(label, "box", [w, d, h], x, up, out, [0.0, 0.0, 0.0], material or self.material, solid)

    def rod(self, label, r, a, b, material=None, solid=True):
        """A round bar between two points (x, up, out). MuJoCo's cylinder axis is z, and R z = (sin b, -sin a cos b, cos a cos b)."""
        dx, dz, dy = b[0] - a[0], b[1] - a[1], -(b[2] - a[2])
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        beta = math.asin(dx / length)
        alpha = math.atan2(-dy, dz)
        self._add(label, "cyl", [r, length], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2, [math.degrees(alpha), math.degrees(beta), 0.0], material or self.material, solid)


def _ac_unit(m, place):
    if place == ROOF:
        for dx in (-0.45, 0.45):
            m.box("skid", 0.08, 0.9, 0.1, dx, 0.05, -1.5, "galvanised", False)
        body_up, out = 0.45, -1.5
        m.box("body", 1.1, 0.8, 0.7, 0, body_up, out, solid=False)
        m.box("grille", 0.9, 0.02, 0.5, 0, body_up, out + 0.41, "dark_sealant", False)
        m.rod("fan", 0.2, (0, body_up, out + 0.42), (0, body_up, out + 0.44), "galvanised", False)
        return
    for dx in (-0.36, 0.36):
        m.box("plate", 0.08, 0.012, 0.42, dx, -0.2, 0.006, "galvanised")
        m.box("arm", 0.05, 0.56, 0.05, dx, -0.33, 0.29, "galvanised")
        m.rod("brace", 0.015, (dx, -0.05, 0.012), (dx, -0.31, 0.5), "galvanised")
    m.box("body", 1.0, 0.5, 0.6, 0, 0, 0.32)
    m.box("grille", 0.84, 0.012, 0.46, 0, 0, 0.576, "dark_sealant", False)
    m.rod("fan", 0.19, (0, 0, 0.582), (0, 0, 0.6), "galvanised", False)
    m.rod("hub", 0.05, (0, 0, 0.6), (0, 0, 0.62), "dark_sealant", False)
    m.rod("pipe", 0.018, (0.42, 0.14, 0.0), (0.42, 0.14, 0.08), "dark_sealant", False)


def _sign(m, place):
    for dx in (-0.7, 0.7):
        for up in (-0.26, 0.26):
            m.box("plate", 0.1, 0.012, 0.1, dx, up, 0.006, "brushed_alu")
            m.box("standoff", 0.05, 0.14, 0.05, dx, up, 0.08, "brushed_alu")
    m.box("panel", 1.9, 0.05, 0.72, 0, 0, 0.175)
    m.box("trim", 1.94, 0.012, 0.76, 0, 0, 0.144, "brushed_alu")


def _vent_hood(m, place):
    m.box("flange", 0.78, 0.012, 0.58, 0, 0, 0.006, "dark_sealant")
    m.box("hood", 0.66, 0.16, 0.46, 0, 0.02, 0.09)
    m.box("cap", 0.72, 0.2, 0.03, 0, 0.26, 0.11)
    for i in range(3):
        m.box("louvre", 0.58, 0.014, 0.03, 0, -0.12 + i * 0.12, 0.178, "dark_sealant", False)


def _window_frame_bracket(m, place):
    m.box("plate", 0.1, 0.012, 0.36, 0, 0, 0.006)
    m.box("arm", 0.06, 0.15, 0.06, 0, 0.04, 0.085)
    m.box("tip", 0.1, 0.02, 0.1, 0, 0.04, 0.17)
    m.rod("gusset", 0.012, (0, -0.14, 0.012), (0, 0.02, 0.15))
    for up in (-0.14, 0.14):
        m.rod("bolt", 0.012, (0.03, up, 0.012), (0.03, up, 0.024), "dark_sealant", False)


def _maintenance_cradle(m, place):
    post_out, hang_out = -1.0, 0.95
    for dx in (-1.4, 1.4):
        m.box("plate", 0.5, 0.5, 0.05, dx, 0.025, post_out, "galvanised", False)
        m.box("post", 0.14, 0.14, 2.4, dx, 1.25, post_out, None, False)
        m.box("arm", 0.12, hang_out - post_out + 0.1, 0.12, dx, 2.5, (post_out + hang_out) / 2, None, False)
        m.rod("wire", 0.008, (dx, 2.44, hang_out), (dx, -2.2, hang_out), "dark_sealant", False)
    m.box("floor", 3.2, 0.7, 0.06, 0, -2.2, hang_out, "galvanised", False)
    m.box("hanger", 3.0, 0.05, 0.05, 0, -2.08, hang_out, "galvanised", False)
    for out in (hang_out - 0.33, hang_out + 0.33):
        m.box("toe", 3.2, 0.02, 0.2, 0, -2.07, out, None, False)
        m.box("rail", 3.2, 0.04, 0.04, 0, -1.2, out, "galvanised", False)
        for dx in (-1.58, -0.53, 0.53, 1.58):
            m.box("upright", 0.04, 0.04, 1.0, dx, -1.68, out, "galvanised", False)


def _antenna(m, place):
    out = -2.0
    m.box("pad", 1.4, 1.4, 0.12, 0, 0.06, out, "weathered_concrete", False)
    m.rod("mast", 0.05, (0, 0.12, out), (0, 9.0, out), "galvanised", False)
    for up, half in ((6.0, 0.9), (7.2, 0.65), (8.3, 0.4)):
        m.box("bar", 2 * half, 0.04, 0.04, 0, up, out, "galvanised", False)
    m.rod("dish", 0.42, (0, 4.2, out + 0.1), (0, 4.2, out + 0.2), "brushed_alu", False)
    for dx, dout in ((1.8, 1.0), (-1.8, 1.0), (0, -1.9)):
        m.rod("guy", 0.008, (0, 5.0, out), (dx, 0.01, out + dout), "dark_sealant", False)


def _crane(m, place):
    out, half, height = -5.0, 0.55, 30.0
    steel = "safety_paint"
    m.box("pad", 5.0, 5.0, 0.6, 0, 0.3, out, "weathered_concrete", False)
    for dx in (-half, half):
        for dout in (-half, half):
            m.box("chord", 0.16, 0.16, height, dx, 0.6 + height / 2, out + dout, steel, False)
    level, step, side = 0.6, 3.0, 1
    while level + step <= height + 0.6:
        m.box("ring", 2 * half, 0.1, 0.1, 0, level + step, out + half, steel, False)
        m.rod("lace", 0.04, (-side * half, level, out + half), (side * half, level + step, out + half), steel, False)
        level += step
        side = -side
    top = height + 0.6
    m.box("slew", 1.6, 1.6, 1.0, 0, top + 0.5, out, "galvanised", False)
    m.box("cab", 1.3, 1.5, 2.0, 1.4, top + 0.3, out + 0.3, "painted_steel", False)
    m.box("glass", 0.9, 0.02, 1.0, 1.4, top + 0.6, out + 1.06, "dark_sealant", False)
    jib, jib_up = 26.0, top + 1.05
    for dout in (-0.45, 0.45):
        m.box("jib", jib, 0.12, 0.12, 0.8 + jib / 2 - 0.8, jib_up, out + dout, steel, False)
    m.box("jibtop", jib - 2, 0.1, 0.1, jib / 2, jib_up + 1.3, out, steel, False)
    x, side = 0.8, 1
    while x + 2.4 <= jib - 1:
        m.rod("jiblace", 0.035, (x, jib_up, out + side * 0.45), (x + 1.2, jib_up + 1.3, out), steel, False)
        m.rod("jiblace", 0.035, (x + 1.2, jib_up + 1.3, out), (x + 2.4, jib_up, out + side * 0.45), steel, False)
        x += 2.4
        side = -side
    m.box("counter", 9.0, 1.1, 0.25, -4.5, jib_up, out, steel, False)
    for i in range(3):
        m.box("weight", 1.0, 1.0, 1.9, -8.2 + i * 1.1, jib_up - 1.05, out, "weathered_concrete", False)
    head = jib_up + 6.0
    for dout in (-0.3, 0.3):
        m.rod("head", 0.08, (0, jib_up, out + dout * 2), (0, head, out), steel, False)
    m.rod("tie", 0.03, (0, head, out), (jib * 0.62, jib_up + 1.3, out), "galvanised", False)
    m.rod("tie", 0.03, (0, head, out), (-8.5, jib_up + 0.12, out), "galvanised", False)
    m.box("trolley", 1.0, 0.8, 0.25, jib * 0.7, jib_up - 0.18, out, "painted_steel", False)
    m.rod("cable", 0.02, (jib * 0.7, jib_up - 0.3, out), (jib * 0.7, jib_up - 16.3, out), "dark_sealant", False)
    m.box("block", 0.5, 0.35, 0.7, jib * 0.7, jib_up - 16.65, out, "safety_paint", False)
    m.rod("hook", 0.05, (jib * 0.7, jib_up - 17.0, out), (jib * 0.7, jib_up - 17.5, out), "dark_sealant", False)


BUILDERS = {"ac_unit": (_ac_unit, "painted_steel"), "sign": (_sign, "painted_steel"), "vent_hood": (_vent_hood, "galvanised"), "window_frame_bracket": (_window_frame_bracket, "galvanised"),
            "maintenance_cradle_parked": (_maintenance_cradle, "painted_steel"), "antenna": (_antenna, "galvanised"), "crane": (_crane, "safety_paint")}


def place_of(part, asked):
    default, others, _ = PARTS[part]
    return asked if asked in (default, *others) else None if asked else default


def build(world, a):
    """The part's objects, or None when the part cannot go in the asked place or a facade part has no height."""
    part, scale = a["part"], a.get("scale", 1.0)
    place = place_of(part, a.get("place"))
    if place is None or (place == FACADE and "below_top_m" not in a):
        return None
    x = a["x_m"]
    if part == "window_frame_bracket":  # It fixes to a frame, so it goes to the nearest joint.
        x = min(W.mullion_xs(world) or [x], key=lambda m: abs(m - x))
    roof = W.area_rect(world)["z1"] - world["tower"]["height_m"]
    builder, material = BUILDERS[part]
    m = Maker(a["name"], x, a["below_top_m"] if place == FACADE else roof, scale, a.get("material", material))
    builder(m, place)
    return m.out
