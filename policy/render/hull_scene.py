"""Blender side of the hull film. Run through hull.py, not directly.

z up, metres, hull plane at z = 0 with water below, as in the record. Objects named solid_* come from the record: robot bodies at recorded poses and weld beads at recorded sizes.
Objects named visual_* are picture only: the physics never reads them and nothing writes back. Fouling comes from the recorded grid. Clean paint appears only where the record says.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hull_record as R  # noqa: E402
import inspection_scene as IS  # noqa: E402
from inspection_scene import Batch, box, cyl, lathe, tube, frame_of  # noqa: E402

# Beer-Lambert per metre. Art values that give blue-green water.
WATER_K = np.array((0.30, 0.085, 0.10))
INSCATTER = (0.006, 0.066, 0.068)
FOG_K = 0.13
WATER = {"scale": 1.0, "caustic": 1.0}
BILGE_R = 1.8
WATERLINE_Z = 6.0
BARNACLE_MAX = 42000


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="still", choices=["still", "clip", "probe"])
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--threshold", type=float, default=0.03)
    ap.add_argument("--device", default="metal", choices=["auto", "metal", "optix", "cuda"])
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--override", default=None)
    ap.add_argument("--no-blur", action="store_true")
    ap.add_argument("--probe-times", default="")
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1:])


class WaterG(IS.G):
    """Node writer whose finish applies water: colour loss per metre on the path of each ray, and in-scatter on camera rays. Analytic, so it adds no noise."""

    def path(self):
        return self.n("ShaderNodeLightPath")

    def transmit(self):
        lp = self.path()
        c = self.n("ShaderNodeCombineColor")
        for i in range(3):
            self.nt.links.new(self.math("EXPONENT", self.mul(lp.outputs["Ray Length"], float(-WATER_K[i] * WATER["scale"]))), c.inputs[i])
        return c.outputs[0]

    def _tint_bsdfs(self, T):
        for node in list(self.nt.nodes):
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                sock = node.inputs["Base Color"]
                src = sock.links[0].from_socket if sock.is_linked else None
                if src is None:
                    rgb = self.n("ShaderNodeRGB")
                    rgb.outputs[0].default_value = tuple(sock.default_value)
                    src = rgb.outputs[0]
                m = self.cmix(1.0, src, T, "MULTIPLY")
                self.nt.links.new(m, sock)

    def finish(self, shader):
        self._tint_bsdfs(self.transmit())
        lp = self.path()
        fog = self.math("SUBTRACT", 1.0, self.math("EXPONENT", self.mul(lp.outputs["Ray Length"], -FOG_K * WATER["scale"])))
        f = self.mul(fog, lp.outputs["Is Camera Ray"])
        e = self.n("ShaderNodeEmission")
        e.inputs[0].default_value = (*INSCATTER, 1)
        e.inputs[1].default_value = 1.0
        m = self.n("ShaderNodeMixShader")
        self.nt.links.new(f, m.inputs[0])
        self.nt.links.new(shader, m.inputs[1])
        self.nt.links.new(e.outputs[0], m.inputs[2])
        o = self.n("ShaderNodeOutputMaterial")
        self.nt.links.new(m.outputs[0], o.inputs[0])
        return self.mat

    def plain(self, shader):
        o = self.n("ShaderNodeOutputMaterial")
        self.nt.links.new(shader, o.inputs[0])
        return self.mat

    def attr(self, name, kind="GEOMETRY"):
        a = self.n("ShaderNodeAttribute")
        a.attribute_type = kind
        a.attribute_name = name
        return a

    def xyz(self, vec=None):
        s = self.n("ShaderNodeSeparateXYZ")
        self.nt.links.new(vec or self.obj, s.inputs[0])
        return s.outputs


IS.G = WaterG  # surface() builds its graphs through this name.


# ---------------------------------------------------------------- hull

def grid_vec(g, rec):
    """World x, y to the fouling image's u, v."""
    x, y, _ = g.xyz()
    c = g.n("ShaderNodeCombineXYZ")
    g.nt.links.new(g.math("DIVIDE", g.math("SUBTRACT", x, rec.grid_x[0]), rec.grid_x[1] - rec.grid_x[0]), c.inputs[0])
    g.nt.links.new(g.math("DIVIDE", g.math("SUBTRACT", y, rec.grid_y[0]), rec.grid_y[1] - rec.grid_y[0]), c.inputs[1])
    return c.outputs[0], x, y


def fouling_tex(g, image, vec):
    t = g.n("ShaderNodeTexImage")
    t.image = image
    t.extension = "EXTEND"
    t.interpolation = "Cubic"
    g.nt.links.new(vec, t.inputs[0])
    sep = g.n("ShaderNodeSeparateColor")
    g.nt.links.new(t.outputs[0], sep.inputs[0])
    return sep.outputs


def hull_material(name, rec, image, kind="paint"):
    """Anti-fouling paint under recorded fouling. Outside the grid, where the robot never goes, fouling is drawn at the world's mean level from noise."""
    g = WaterG(name)
    vec, x, y = grid_vec(g, rec)
    ch = fouling_tex(g, image, vec)
    inside = g.mul(g.mul(g.rng(x, rec.grid_x[0], rec.grid_x[0] + 0.5, 0, 1), g.rng(x, rec.grid_x[1] - 0.5, rec.grid_x[1], 1, 0)), g.mul(g.rng(y, rec.grid_y[0], rec.grid_y[0] + 0.5, 0, 1), g.rng(y, rec.grid_y[1] - 0.5, rec.grid_y[1], 1, 0)))
    far = g.rng(g.noise(1.1, 4.0, 0.55), 0.3, 0.7, 0.45, 1.0)
    # The bilge gets more light in life and more growth, so a fuller coat there.
    slime = g.lerp(inside, far, ch[0])

    fine = g.noise(95.0, 4.0, 0.6)
    mid = g.noise(19.0, 4.0, 0.55)
    big = g.noise(3.2, 4.0, 0.55)
    edge = g.math("ADD", g.mul(slime, 1.05), g.math("ADD", g.mul(g.math("SUBTRACT", big, 0.5), 0.9), g.math("ADD", g.mul(g.math("SUBTRACT", mid, 0.5), 0.55), g.mul(g.math("SUBTRACT", fine, 0.5), 0.34))))
    coat = g.mul(g.rng(edge, 0.30, 0.74, 0.0, 1.0), g.rng(slime, 0.10, 0.30, 0.0, 1.0))

    # Paint.
    macro = g.noise(0.9, 4.0, 0.55)
    patchy = g.noise(5.5, 5.0, 0.6)
    if kind == "stencil":
        paint = g.cmul(g.cmix(g.rng(patchy, 0.4, 0.62, 0, 0.5), (0.62, 0.61, 0.55), (0.34, 0.2, 0.17)), 1.0)
    else:
        paint = g.cmix(g.rng(macro, 0.36, 0.64, 0, 1), (0.115, 0.020, 0.016), (0.185, 0.036, 0.026))
        paint = g.cmix(g.mul(g.rng(patchy, 0.5, 0.72, 0, 1), 0.55), paint, (0.235, 0.075, 0.055))
        imp = g.luma(g.tex("SurfaceImperfections015", g.scaled(1 / 1.4), "Color", True))
        paint = g.cmul(paint, g.rng(imp, 0.1, 0.7, 0.72, 1.08, False))
        scr = g.luma(g.tex("Scratches003", g.scaled(1 / 0.9), "Color", True))
        paint = g.cmix(g.mul(g.rng(scr, 0.25, 0.6, 0, 1), 0.35), paint, (0.11, 0.09, 0.08))
    # Paint breaks down along welds: a dark rust-stained band, only drawn near the recorded bead lines.
    near = None
    for sx in R.SEAMS_X:
        d = g.math("ABSOLUTE", g.math("SUBTRACT", x, sx))
        near = d if near is None else g.math("MINIMUM", near, d)
    for sy in R.SEAMS_Y:
        near = g.math("MINIMUM", near, g.math("ABSOLUTE", g.math("SUBTRACT", y, sy)))
    stain = g.mul(g.rng(near, 0.012, 0.075, 0.9, 0.0), g.rng(g.noise(26.0, 4.0, 0.6), 0.34, 0.66, 0.25, 1.0))
    paint = g.cmix(stain, paint, (0.045, 0.022, 0.014))
    # Scrubbed paint is a little brighter, with the leached skin gone, only where the record cleaned it.
    scrub = g.mul(ch[2], inside)
    paint = g.cmix(g.mul(scrub, 0.65), paint, g.cmul(paint, 1.3))
    swirl = g.noise(40.0, 2.0, 0.5, g.scaled((0.35, 2.4, 1.0)))
    paint = g.cmul(paint, g.lerp(scrub, 1.0, g.rng(swirl, 0.3, 0.7, 0.86, 1.1, False)))

    # Slime and algae, combed along the ship by water flow.
    comb = g.noise(9.0, 5.0, 0.62, g.scaled((0.28, 1.6, 1.0)))
    comb2 = g.noise(34.0, 5.0, 0.62, g.scaled((0.35, 1.5, 1.0)))
    algae = g.cmix(g.rng(comb, 0.32, 0.68, 0, 1), (0.030, 0.027, 0.014), (0.075, 0.066, 0.034))
    algae = g.cmix(g.rng(macro, 0.45, 0.68, 0, 0.75), algae, (0.058, 0.040, 0.024))
    algae = g.cmix(g.mul(g.rng(comb2, 0.58, 0.74, 0, 1), 0.55), algae, (0.105, 0.098, 0.058))
    base = g.cmix(coat, paint, algae)

    # Height for the bump: paint orange peel, plate waviness, fur of the slime.
    height = g.math("ADD", g.mul(coat, g.math("ADD", 0.45, g.mul(comb2, 0.9))), g.mul(fine, 0.06))
    b = g.principled()
    g.link(b.inputs["Base Color"], base)
    g.link(b.inputs["Roughness"], g.lerp(coat, 0.62, 0.48))
    g.link(b.inputs["Specular IOR Level"], 0.45)
    bn = g.n("ShaderNodeBump")
    bn.inputs["Strength"].default_value = 0.8
    bn.inputs["Distance"].default_value = 0.006
    g.nt.links.new(height, bn.inputs["Height"])
    wav = g.n("ShaderNodeBump")
    wav.inputs["Strength"].default_value = 0.35
    wav.inputs["Distance"].default_value = 0.05
    g.nt.links.new(g.noise(0.75, 2.0, 0.4), wav.inputs["Height"])
    g.nt.links.new(wav.outputs[0], bn.inputs["Normal"])
    if kind == "weld":
        ripple = g.n("ShaderNodeTexWave")
        ripple.wave_type = "BANDS"
        ripple.bands_direction = "DIAGONAL"
        ripple.inputs["Scale"].default_value = 90.0
        ripple.inputs["Distortion"].default_value = 3.0
        ripple.inputs["Detail"].default_value = 2.0
        g.nt.links.new(g.obj, ripple.inputs["Vector"])
        r2 = g.n("ShaderNodeBump")
        r2.inputs["Strength"].default_value = 0.9
        r2.inputs["Distance"].default_value = 0.0025
        g.nt.links.new(ripple.outputs["Fac"], r2.inputs["Height"])
        g.nt.links.new(bn.outputs[0], r2.inputs["Normal"])
        g.nt.links.new(r2.outputs[0], b.inputs["Normal"])
    else:
        g.nt.links.new(bn.outputs[0], b.inputs["Normal"])

    # Caustics: art. Strong on the bilge, faint and broken inboard where only reflected light reaches.
    t = g.attr("water_t", "OBJECT").outputs["Fac"]
    warp = g.n("ShaderNodeTexNoise")
    warp.noise_dimensions = "4D"
    warp.inputs["Scale"].default_value = 1.6
    warp.inputs["Detail"].default_value = 2.0
    g.nt.links.new(g.obj, warp.inputs["Vector"])
    g.nt.links.new(g.mul(t, 0.18), warp.inputs["W"])
    add = g.n("ShaderNodeVectorMath")
    add.operation = "ADD"
    g.nt.links.new(g.obj, add.inputs[0])
    scale_warp = g.n("ShaderNodeVectorMath")
    scale_warp.operation = "SCALE"
    g.nt.links.new(warp.outputs["Color"], scale_warp.inputs[0])
    scale_warp.inputs["Scale"].default_value = 0.75
    g.nt.links.new(scale_warp.outputs[0], add.inputs[1])
    vor = g.n("ShaderNodeTexVoronoi")
    vor.voronoi_dimensions = "4D"
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 5.5
    g.nt.links.new(add.outputs[0], vor.inputs["Vector"])
    g.nt.links.new(g.mul(t, 0.42), vor.inputs["W"])
    vor2 = g.n("ShaderNodeTexVoronoi")
    vor2.voronoi_dimensions = "4D"
    vor2.feature = "DISTANCE_TO_EDGE"
    vor2.inputs["Scale"].default_value = 11.0
    g.nt.links.new(add.outputs[0], vor2.inputs["Vector"])
    g.nt.links.new(g.mul(t, 0.55), vor2.inputs["W"])
    line = g.math("MAXIMUM", g.rng(vor.outputs["Distance"], 0.0, 0.035, 0.75, 0.0), g.rng(vor2.outputs["Distance"], 0.0, 0.05, 0.55, 0.0))
    line = g.mul(line, g.rng(g.noise(5.0, 2.0, 0.5), 0.36, 0.6, 0.0, 1.0))
    patch = g.rng(g.noise(0.55, 2.0, 0.5), 0.42, 0.62, 0.15, 1.0)
    reach = g.mul(g.rng(y, 1.2, R.PLATE_Y[1] - 0.1, 0.05, 1.0), patch)
    glow = g.mul(g.mul(line, reach), 2.4 * WATER["caustic"])
    em = g.n("ShaderNodeEmission")
    g.nt.links.new(g.cmix(1.0, g.cmix(0.5, base, (0.16, 0.27, 0.22)), g.transmit(), "MULTIPLY"), em.inputs[0])
    g.nt.links.new(glow, em.inputs[1])
    s = g.n("ShaderNodeAddShader")
    g.nt.links.new(b.outputs[0], s.inputs[0])
    g.nt.links.new(em.outputs[0], s.inputs[1])
    return g.finish(s.outputs[0])


def hull_section():
    """(y, z) from far inboard, across the bilge, up the side to above the waterline. Flat to the physics plate's edge, then a scenery curve."""
    y0 = R.PLATE_Y[1]
    pts = [(-70.0, 0.0), (-20.0, 0.0), (-8.0, 0.0), (-3.0, 0.0), (R.PLATE_Y[0], 0.0), (0.0, 0.0), (y0, 0.0)]
    for a in np.linspace(0, math.pi / 2, 18)[1:]:
        pts.append((y0 + BILGE_R * math.sin(a), BILGE_R * (1 - math.cos(a))))
    pts.append((y0 + BILGE_R, WATERLINE_Z + 3.0))
    return np.array(pts)


def build_hull(rec, image, coll):
    sec = hull_section()
    xs = np.array((-70.0, -8.0, R.PLATE_X[0], R.PLATE_X[1], 20.0, 90.0))
    v, f = [], []
    n = len(sec)
    for i, x in enumerate(xs):
        for y, z in sec:
            v.append((x, y, z))
    for i in range(len(xs) - 1):
        for j in range(n - 1):
            a = i * n + j
            f.append((a, a + 1, a + n + 1, a + n))
    me = bpy.data.meshes.new("hull")
    me.from_pydata(v, [], f)
    me.polygons.foreach_set("use_smooth", [True] * len(f))
    me.materials.append(hull_material("hull_paint", rec, image))
    ob = bpy.data.objects.new("visual_hull_plate", me)
    coll.objects.link(ob)
    return ob


def build_seams(rec, image, coll):
    """Weld beads at the recorded height, with the recorded section. A slight waver in plan and height is art, under 1 mm."""
    h = rec.world["seam"]["height_m"]
    half = math.sqrt(max(0.0, R.SEAM_R ** 2 - (R.SEAM_R - h) ** 2))
    prof = np.linspace(-1, 1, 9)
    v, f = [], []
    rng = np.random.default_rng(7)
    manifest = []

    def strip(p0, p1, along, across):
        L = np.linalg.norm(np.array(p1) - np.array(p0))
        n = max(2, int(L / 0.012))
        start = len(v)
        wav = np.cumsum(rng.normal(0, 0.00012, n))
        wav -= np.linspace(wav[0], wav[-1], n)
        hv = np.cumsum(rng.normal(0, 0.00006, n))
        hv -= np.linspace(hv[0], hv[-1], n)
        for i in range(n):
            p = np.array(p0) + (np.array(p1) - np.array(p0)) * i / (n - 1)
            for u in prof:
                d = u * half
                z = -(max(0.0, math.sqrt(R.SEAM_R ** 2 - d * d) - (R.SEAM_R - h)) + (hv[i] if abs(u) < 0.8 else 0.0)) - 0.00005
                q = p + np.array(across) * (d + wav[i])
                v.append((q[0], q[1], z))
        m = len(prof)
        for i in range(n - 1):
            for j in range(m - 1):
                a = start + i * m + j
                f.append((a, a + 1, a + m + 1, a + m))

    x0, x1 = R.PLATE_X
    y0, y1 = R.PLATE_Y
    for x in R.SEAMS_X:
        strip((x, y0 - 3, 0), (x, y1, 0), (0, 1, 0), (1, 0, 0))
        manifest.append({"axis": "y", "at": x})
    for y in R.SEAMS_Y:
        strip((x0 - 4, y, 0), (x1 + 8, y, 0), (1, 0, 0), (0, 1, 0))
        manifest.append({"axis": "x", "at": y})
    me = bpy.data.meshes.new("seams")
    me.from_pydata(v, [], f)
    me.polygons.foreach_set("use_smooth", [True] * len(f))
    me.materials.append(hull_material("hull_weld", rec, image, "weld"))
    ob = bpy.data.objects.new("solid_weld_beads", me)
    coll.objects.link(ob)
    return ob, {"height_m": h, "half_width_m": half, "seams": manifest, "max_z_drop": float(-min(p[2] for p in v))}


def barnacle_material(rec, image):
    g = WaterG("barnacle")
    a = g.attr("cell")
    xyz = g.xyz(a.outputs["Vector"])
    in_grid = g.rng(xyz[1], -0.01, 0.0, 0.0, 1.0, False)
    vec = g.n("ShaderNodeCombineXYZ")
    g.nt.links.new(xyz[0], vec.inputs[0])
    g.nt.links.new(xyz[1], vec.inputs[1])
    ch = fouling_tex(g, image, vec.outputs[0])
    # Gone once the recorded level at its cell falls below its own threshold.
    gone = g.mul(in_grid, g.math("LESS_THAN", ch[1], xyz[2]))
    rough = g.noise(170.0, 3.0, 0.6)
    colour = g.cmix(g.rng(rough, 0.3, 0.7, 0, 1), (0.055, 0.055, 0.042), (0.17, 0.155, 0.115))
    colour = g.cmix(g.rng(g.noise(9.0, 3.0), 0.42, 0.62, 0, 0.8), colour, (0.035, 0.042, 0.018))
    b = g.principled()
    g.link(b.inputs["Base Color"], colour)
    g.link(b.inputs["Roughness"], 0.82)
    bn = g.n("ShaderNodeBump")
    bn.inputs["Strength"].default_value = 1.0
    bn.inputs["Distance"].default_value = 0.003
    g.nt.links.new(rough, bn.inputs["Height"])
    g.nt.links.new(bn.outputs[0], b.inputs["Normal"])
    t = g.n("ShaderNodeBsdfTransparent")
    m = g.n("ShaderNodeMixShader")
    g.nt.links.new(gone, m.inputs[0])
    g.nt.links.new(b.outputs[0], m.inputs[1])
    g.nt.links.new(t.outputs[0], m.inputs[2])
    g._tint_bsdfs(g.transmit())
    return g.plain(m.outputs[0])


def scar_material():
    g = WaterG("barnacle_scar")
    b = g.principled()
    g.link(b.inputs["Base Color"], g.cmix(g.rng(g.noise(240.0, 2.0), 0.35, 0.65, 0, 1), (0.105, 0.035, 0.027), (0.15, 0.062, 0.047)))
    g.link(b.inputs["Roughness"], 0.8)
    return g.finish(b.outputs[0])


def build_barnacles(rec, image, coll):
    """Each barnacle's place comes from the recorded start level of its cell. A cell's level sets how many it holds, and each barnacle's threshold lies under that level."""
    rng = np.random.default_rng(11)
    ny, nx = rec.shape
    cm = rec.cell_m
    level = rec.b0
    # In-grid: up to about 3 per cell at full level, where the level is high.
    weights = np.clip(level - 0.08, 0, 1) ** 1.2
    expected = weights * 1.15
    counts = rng.poisson(expected)
    iy, ix = np.nonzero(counts)
    reps = counts[iy, ix]
    iy, ix = np.repeat(iy, reps), np.repeat(ix, reps)
    x = rec.grid_x[0] + (ix + rng.random(len(ix))) * cm
    y = rec.grid_y[0] + (iy + rng.random(len(iy))) * cm
    lv = level[iy, ix]
    thr = rng.uniform(0.16, 1.0, len(ix)) * lv
    thr = np.maximum(thr, 0.16)
    u = (x - rec.grid_x[0]) / (rec.grid_x[1] - rec.grid_x[0])
    v_ = (y - rec.grid_y[0]) / (rec.grid_y[1] - rec.grid_y[0])
    # Outside the grid, for the eye only: drawn at a noise-led density.
    m = 16000
    fx = rng.uniform(-5.0, 14.0, m)
    fy = rng.uniform(-6.0, R.PLATE_Y[1] - 0.02, m)
    keep = ((fx < rec.grid_x[0]) | (fx > rec.grid_x[1]) | (fy < rec.grid_y[0]) | (fy > rec.grid_y[1])) & (np.sin(fx * 2.3 + np.sin(fy * 1.7) * 2) + np.sin(fy * 3.1 + fx) > -0.1)
    fx, fy = fx[keep], fy[keep]
    x, y = np.concatenate([x, fx]), np.concatenate([y, fy])
    u, v_ = np.concatenate([u, np.full(len(fx), 0.5)]), np.concatenate([v_, np.full(len(fx), -1.0)])
    thr = np.concatenate([thr, np.zeros(len(fx))])
    if len(x) > BARNACLE_MAX:
        pick = rng.choice(len(x), BARNACLE_MAX, replace=False)
        x, y, u, v_, thr = x[pick], y[pick], u[pick], v_[pick], thr[pick]
    n = len(x)
    size = np.exp(rng.normal(np.log(0.0050), 0.40, n))
    size = np.clip(size, 0.0028, 0.0135)
    tall = size * rng.uniform(0.75, 1.25, n)
    side = 12
    ring_r = np.array((1.0, 0.80, 0.42, 0.20))
    ring_z = np.array((0.0, 0.62, 1.0, 0.86))
    ang = np.linspace(0, 2 * np.pi, side, endpoint=False)
    nverts = side * len(ring_r) + 1
    jit = 1 + rng.normal(0, 0.07, (n, side)) + 0.10 * np.where(np.arange(side) % 2 == 0, 1.0, -1.0)[None, :]
    vv = np.zeros((n, nverts, 3))
    twist = rng.uniform(0, 6.28, n)
    for k in range(len(ring_r)):
        a = ang[None, :] + twist[:, None]
        r = size[:, None] * ring_r[k] * (jit if k < 3 else 1.0)
        vv[:, k * side, :] = 0
        vv[:, k * side:(k + 1) * side, 0] = x[:, None] + r * np.cos(a)
        vv[:, k * side:(k + 1) * side, 1] = y[:, None] + r * np.sin(a)
        vv[:, k * side:(k + 1) * side, 2] = -0.0002 - tall[:, None] * ring_z[k]
    vv[:, -1, 0], vv[:, -1, 1], vv[:, -1, 2] = x, y, -0.0002 - tall * 0.70
    faces = []
    for k in range(len(ring_r) - 1):
        for j in range(side):
            jn = (j + 1) % side
            faces.append((k * side + j, k * side + jn, (k + 1) * side + jn, (k + 1) * side + j))
    for j in range(side):
        faces.append(((len(ring_r) - 1) * side + j, (len(ring_r) - 1) * side + (j + 1) % side, nverts - 1))
    verts = vv.reshape(-1, 3)
    offs = (np.arange(n) * nverts)
    quads = np.array([f for f in faces if len(f) == 4])
    tris = np.array([f for f in faces if len(f) == 3])
    all_f = (quads[None] + offs[:, None, None]).reshape(-1, 4).tolist() + (tris[None] + offs[:, None, None]).reshape(-1, 3).tolist()
    me = bpy.data.meshes.new("barnacles")
    me.from_pydata(verts.tolist(), [], all_f)
    me.polygons.foreach_set("use_smooth", [True] * len(all_f))
    at = me.attributes.new("cell", "FLOAT_VECTOR", "POINT")
    cell = np.column_stack([np.repeat(u, nverts), np.repeat(v_, nverts), np.repeat(thr, nverts)])
    at.data.foreach_set("vector", cell.ravel())
    me.materials.append(barnacle_material(rec, image))
    ob = bpy.data.objects.new("visual_barnacles", me)
    coll.objects.link(ob)
    # Pale cement rings stay on the paint after a barnacle goes: only for those the robot can reach.
    grid = v_ >= 0
    sc_v, sc_f = [], []
    gx, gy, gs = x[grid], y[grid], size[grid]
    a6 = np.linspace(0, 2 * np.pi, 7)[:-1]
    r_in, r_out = gs[:, None] * 0.0, gs[:, None] * 0.7
    vo = np.stack([gx[:, None] + r_out * np.cos(a6), gy[:, None] + r_out * np.sin(a6), np.full((len(gx), 6), -0.00015)], axis=2)
    vi = np.stack([gx[:, None] + r_in * np.cos(a6), gy[:, None] + r_in * np.sin(a6), np.full((len(gx), 6), -0.00015)], axis=2)
    sv = np.concatenate([vo, vi], axis=1).reshape(-1, 3)
    base = np.array([(j, (j + 1) % 6, 6 + (j + 1) % 6, 6 + j) for j in range(6)])
    sf = (base[None] + (np.arange(len(gx)) * 12)[:, None, None]).reshape(-1, 4)
    me2 = bpy.data.meshes.new("scars")
    me2.from_pydata(sv.tolist(), [], sf.tolist())
    me2.materials.append(scar_material())
    ob2 = bpy.data.objects.new("visual_barnacle_scars", me2)
    coll.objects.link(ob2)
    return ob, ob2


def build_marks(rec, image, coll):
    """Stencilled frame marks. The text comes from the world's picture value and generic frame numbers. No ship's name."""
    mat = hull_material("hull_stencil", rec, image, "stencil")
    n0 = rec.world["picture"]["text"]
    marks = [(n0, 4.25, 2.62, 0.13), ("FR 116", 6.65, 2.62, 0.13), ("FR 108", 1.85, 2.62, 0.13), ("FR 104", -0.6, 2.62, 0.13)]
    out = []
    for text, x, y, size in marks:
        c = bpy.data.curves.new(text, "FONT")
        c.body = text
        c.size = size
        c.align_x, c.align_y = "CENTER", "CENTER"
        ob = bpy.data.objects.new("tmp_" + text, c)
        coll.objects.link(ob)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        coll.objects.unlink(ob)
        bpy.data.objects.remove(ob)
        # Readable from below: flip about the text's long axis. The film's camera looks toward +y.
        cos = np.zeros(len(me.vertices) * 3)
        me.vertices.foreach_get("co", cos)
        p = cos.reshape(-1, 3)
        q = np.column_stack([p[:, 0] + x, -p[:, 1] + y, np.full(len(p), -0.0003)])
        me.vertices.foreach_set("co", q.ravel())
        me.materials.clear()
        me.materials.append(mat)
        o2 = bpy.data.objects.new(f"visual_mark_{text.replace(' ', '_')}", me)
        coll.objects.link(o2)
        out.append(o2)
    return out


def hardware_materials():
    m = {}
    m["steel"] = IS.surface("hw_steel", "Metal049A", 0.5, tint=(0.62, 0.58, 0.54), metal=0.75, rough=0.46, grime=0.0, dust=0.0, wear=0.3)
    m["zinc"] = IS.surface("hw_zinc", "Metal032", 0.6, tint=(0.55, 0.56, 0.56), metal=0.85, rough=0.72, grime=0.0, dust=0.3, wear=0.5, rust=0.2)
    m["alu"] = IS.surface("hw_alu", "Metal049A", 0.7, tint=(0.34, 0.35, 0.37), metal=0.85, rough=0.46, grime=0.0, dust=0.18, wear=0.5)
    m["ano"] = IS.surface("hw_ano", "Metal049A", 0.7, tint=(0.070, 0.082, 0.098), metal=0.7, rough=0.42, grime=0.0, dust=0.12, wear=0.7)
    m["paint"] = IS.surface("hw_paint", None, 1.0, color=(0.052, 0.056, 0.062), rough=0.46, grime=0.0, dust=0.12, wear=0.8)
    m["foam"] = IS.surface("hw_foam", None, 1.0, color=(0.38, 0.235, 0.016), rough=0.62, grime=0.0, dust=0.45, wear=1.6, rust=0.0)
    m["rubber"] = IS.surface("hw_rubber", "Rubber004", 0.4, tint=(0.028, 0.028, 0.03), rough=0.72, grime=0.0, dust=0.15, wear=0.25)
    m["pu"] = IS.surface("hw_pu", None, 1.0, color=(0.05, 0.048, 0.042), rough=0.62, grime=0.0, dust=0.35, wear=0.5)
    m["nylon"] = IS.surface("hw_nylon", None, 1.0, color=(0.035, 0.036, 0.04), rough=0.5, grime=0.0, dust=0.3, wear=0.0)
    m["brass"] = IS.surface("hw_brass", None, 1.0, color=(0.55, 0.40, 0.17), metal=1.0, rough=0.38, grime=0.0, dust=0.1, wear=0.2)
    m["dark"] = IS.surface("hw_dark", None, 1.0, color=(0.008, 0.008, 0.009), rough=0.8, grime=0.0, dust=0.0, wear=0.0)
    m["mark"] = IS.surface("hw_mark", None, 1.0, color=(0.70, 0.48, 0.03), rough=0.5, grime=0.0, dust=0.1, wear=0.5)
    m["yellow"] = IS.surface("hw_yellow", None, 1.0, color=(0.46, 0.27, 0.012), rough=0.52, grime=0.0, dust=0.35, wear=1.6, rust=0.12, streak=0.4)
    m["motor"] = IS.surface("hw_motor", None, 1.0, color=(0.022, 0.024, 0.027), rough=0.48, grime=0.0, dust=0.15, wear=0.9)
    m["bottle"] = IS.surface("hw_bottle", "Metal049A", 0.7, tint=(0.20, 0.215, 0.23), metal=0.8, rough=0.44, grime=0.0, dust=0.15, wear=0.6)
    m["nylon_pale"] = IS.surface("hw_nylon2", None, 1.0, color=(0.30, 0.30, 0.27), rough=0.5, grime=0.0, dust=0.2, wear=0.0)
    m["cable"] = IS.surface("hw_cable", None, 1.0, color=(0.022, 0.022, 0.024), rough=0.46, grime=0.0, dust=0.15, wear=0.1)
    m["orange"] = IS.surface("hw_orange", None, 1.0, color=(0.62, 0.17, 0.02), rough=0.5, grime=0.0, dust=0.2, wear=0.35)
    g = WaterG("hw_lens")
    b = g.principled()
    g.link(b.inputs["Base Color"], (0.5, 0.52, 0.55))
    g.link(b.inputs["Roughness"], 0.08)
    g.link(b.inputs["Metallic"], 0.2)
    m["glass"] = g.finish(b.outputs[0])
    g = WaterG("hw_led")
    e = g.n("ShaderNodeEmission")
    e.inputs[0].default_value = (1.0, 0.93, 0.80, 1)
    e.inputs[1].default_value = 26.0
    m["led"] = g.plain(e.outputs[0])
    return m


class Parts:
    """One body's geometry, per material, merged into one mesh with slots."""

    def __init__(self, mats):
        self.mats = mats
        self.b = {}

    def __getitem__(self, key):
        return self.b.setdefault(key, Batch())

    def build(self, name, coll):
        ob = bpy.data.objects.new(name, self.mesh(name))
        ob.rotation_mode = "QUATERNION"
        coll.objects.link(ob)
        return ob

    def mesh(self, name):
        all_v, all_f, smooth, slot = [], [], [], []
        off = 0
        me = bpy.data.meshes.new(name)
        keys = [k for k in self.b if self.b[k].v]
        for s, key in enumerate(keys):
            bt = self.b[key]
            v = np.vstack(bt.v)
            all_v.append(v)
            all_f += [tuple(i + off for i in face) for face in bt.f]
            smooth += bt.s
            slot += [s] * len(bt.f)
            off += len(v)
            me.materials.append(self.mats[key])
        me.from_pydata(np.vstack(all_v).tolist(), [], all_f)
        me.polygons.foreach_set("use_smooth", smooth)
        me.polygons.foreach_set("material_index", slot)
        me.update()
        return me


def ring_bolts(p, center, axis, r, n, rb=0.0035, h=0.004, phase=0.0):
    m = frame_of(axis)
    a = np.array(axis, float) / np.linalg.norm(axis)
    for i in range(n):
        ang = phase + 2 * math.pi * i / n
        c = np.asarray(center, float) + m @ np.array((math.cos(ang), math.sin(ang), 0.0)) * r
        cyl(p["steel"], c, c + a * h, rb, 6, ch=0.0006)


def build_roller(m, coll):
    """One road roller, drawn inside the belt, on the recorded pose. The physics capsule is the roller plus the belt's thickness."""
    p = Parts(m)
    r = R.DRAWN_ROLLER_R
    lathe(p["steel"], (0, 0, 0), (0, 1, 0), [(0.0, -0.036), (r - 0.003, -0.036), (r, -0.033), (r, -0.006), (r - 0.003, -0.004), (r - 0.003, 0.004), (r, 0.006), (r, 0.033), (r - 0.003, 0.036), (0.0, 0.036)], 20)
    return p


def build_drum(m, coll):
    """The roller brush: core, end flanges, helical rows of nylon tufts out to the recorded tip radius. Origin on the axle, axis y."""
    p = Parts(m)
    tip, half = R.DRUM_TIP_R, R.DRUM_HALF_W
    lathe(p["ano"], (0, 0, 0), (0, 1, 0), [(0.0, -half), (0.046, -half), (0.046, half), (0.0, half)], 36)
    for s in (-1, 1):
        lathe(p["alu"], (0, s * (half + 0.001), 0), (0, s, 0), [(0.0, 0.0), (0.054, 0.0), (0.054, 0.006), (0.02, 0.008), (0.0, 0.008)], 36)
        ring_bolts(p, (0, s * (half + 0.007), 0), (0, s, 0), 0.04, 8, rb=0.0028, h=0.003)
    rng = np.random.default_rng(31)
    rows, per_row = 10, 34
    for row in range(rows):
        key = "nylon_pale" if row % 5 == 0 else "nylon"
        for i in range(per_row):
            y = -half + 0.006 + (2 * half - 0.012) * i / (per_row - 1)
            # A helix, so that the drum reads as turning and throws waste sideways.
            a = 2 * math.pi * row / rows + 2.6 * y / half + rng.normal(0, 0.02)
            d = np.array((math.sin(a), 0.0, math.cos(a)))
            base = d * 0.045 + np.array((0, y, 0))
            end = d * (tip - rng.uniform(0, 0.0012)) + np.array((rng.normal(0, 0.001), y + rng.normal(0, 0.001), rng.normal(0, 0.001)))
            cyl(p[key], base, end, 0.0031, 6)
    return p


def build_chassis(m, coll):
    """Frame, track frames, power pack, hoses, filter, shroud, lamps, camera, lift eye and tether boot. Origin at the recorded chassis origin. Nothing on it passes the 40 mm skid box top toward the hull, except the track frames inside their belts."""
    p = Parts(m)
    # Deck, side plates and cross members.
    box(p["yellow"], (-0.075, 0, 0.043), (0.20, 0.125, 0.005), ch=0.002)
    for s in (-1, 1):
        box(p["yellow"], (-0.075, s * 0.125, 0.0), (0.215, 0.006, 0.045), ch=0.002)
        for i in range(5):
            c = np.array((-0.24 + i * 0.085, s * 0.1315, 0.0))
            lathe(p["dark"], c, (0, s, 0), [(0.0, 0.0), (0.019, 0.0), (0.019, 0.0005), (0.0, 0.0005)], 20)
            ring_bolts(p, c + np.array((0.03, 0, 0.027)), (0, s, 0), 0.0, 1, rb=0.0032, h=0.0035)
    for x in (-0.28, -0.075, 0.13):
        box(p["yellow"], (x, 0, -0.03), (0.016, 0.122, 0.014), ch=0.003)
    # Track frames: inside the belt, and outer plates with the axle bolts.
    for s in (-1, 1):
        for off in (-0.036, 0.036):
            box(p["yellow"], (-0.075, s * (R.TRACK_Y + off), 0.03), (0.178, 0.004, 0.021), ch=0.001)
        for i, x in enumerate(R.ROLLER_XS):
            c = (x, s * (R.TRACK_Y + 0.04), R.AXLE_Z - 0.008)
            cyl(p["steel"], c, (x, s * (R.TRACK_Y + 0.0465), R.AXLE_Z - 0.008), 0.0065, 6, ch=0.0008)
        for x in (-0.17, -0.075, 0.02):
            c = np.array((x, s * (R.TRACK_Y + 0.0405), 0.022))
            lathe(p["dark"], c, (0, s, 0), [(0.0, 0.0), (0.012, 0.0), (0.012, 0.0004), (0.0, 0.0004)], 16)
        for x in (-0.19, 0.04):
            box(p["yellow"], (x, s * 0.152, 0.025), (0.022, 0.024, 0.012), ch=0.002)
        # Drive motor and final drive at the rear, track tensioner at the front.
        lathe(p["motor"], (R.TRACK_X[0], s * 0.131, 0.03), (0, s, 0), [(0.0, 0.0), (0.04, 0.0), (0.04, 0.018), (0.043, 0.02), (0.043, 0.034), (0.0, 0.034)], 32)
        ring_bolts(p, (R.TRACK_X[0], s * 0.165, 0.03), (0, s, 0), 0.035, 8, rb=0.0025, h=0.003)
        box(p["alu"], (R.TRACK_X[1] + 0.022, s * (R.TRACK_Y + 0.043), 0.03), (0.03, 0.005, 0.012), ch=0.002)
        cyl(p["steel"], (R.TRACK_X[1] - 0.012, s * (R.TRACK_Y + 0.043), 0.03), (R.TRACK_X[1] + 0.058, s * (R.TRACK_Y + 0.043), 0.03), 0.0045, 8)
    # Electronics bottle: end caps, flange bolts, saddle clamps.
    hc = np.array((-0.29, 0, -0.098))
    lathe(p["bottle"], hc, (1, 0, 0), [(0.0, -0.002), (0.042, -0.002), (0.054, 0.0), (0.054, 0.014), (0.05, 0.017), (0.05, 0.276), (0.054, 0.279), (0.054, 0.293), (0.042, 0.295), (0.0, 0.295)], 44)
    ring_bolts(p, hc, (-1, 0, 0), 0.046, 10, rb=0.0026, h=0.003)
    ring_bolts(p, hc + np.array((0.295, 0, 0)), (1, 0, 0), 0.046, 10, rb=0.0026, h=0.003)
    for x in (-0.23, -0.05):
        lathe(p["steel"], (x, 0, -0.098), (1, 0, 0), [(0.0515, -0.011), (0.0515, 0.011)], 44, caps=False)
        box(p["yellow"], (x, 0, -0.051), (0.014, 0.062, 0.006), ch=0.0015)
        for s in (-1, 1):
            cyl(p["steel"], (x, s * 0.052, -0.044), (x, s * 0.052, -0.066), 0.0035, 6, ch=0.0005)
    box(p["alu"], (-0.14, 0.0, -0.1495), (0.036, 0.016, 0.0007), ch=0.0002)
    # Hydraulic pack, oil-filled, finned, on one side; the compensator on the other.
    box(p["motor"], (-0.135, -0.085, -0.075), (0.105, 0.032, 0.03), ch=0.004)
    for i in range(9):
        box(p["motor"], (-0.225 + i * 0.0225, -0.085, -0.106), (0.0035, 0.03, 0.0035), ch=0.0008)
    for x in (-0.235, -0.035):
        ring_bolts(p, (x, -0.057, -0.102), (0, 0, -1), 0.0, 1, rb=0.003, h=0.003)
    lathe(p["alu"], (-0.245, 0.085, -0.075), (1, 0, 0), [(0.0, 0.0), (0.033, 0.0), (0.036, 0.004), (0.036, 0.012), (0.032, 0.015), (0.032, 0.195), (0.036, 0.198), (0.036, 0.206), (0.033, 0.21), (0.0, 0.21)], 32)
    ring_bolts(p, (-0.035, 0.085, -0.075), (1, 0, 0), 0.027, 6, rb=0.0022, h=0.0025)
    for x in (-0.2, -0.08):
        lathe(p["steel"], (x, 0.085, -0.075), (1, 0, 0), [(0.0335, -0.007), (0.0335, 0.007)], 32, caps=False)
    # Foam at the rear corners, strapped. It offsets the steel in water.
    for s in (-1, 1):
        box(p["foam"], (-0.262, s * 0.078, -0.082), (0.022, 0.04, 0.03), ch=0.006)
    # Shroud over the drum: rear and belly closed, front open so that the bristles meet the fouling first.
    dc = np.array((R.DRUM_X, 0, R.DRUM_Z))
    hood_r, wall = 0.086, 0.004
    half = R.DRUM_HALF_W + 0.018
    angles = np.radians(np.linspace(140, 318, 30))
    v = []
    for y in (-half, half):
        for rr in (hood_r, hood_r + wall):
            for a in angles:
                v.append((dc[0] + rr * math.sin(a), y, dc[2] + rr * math.cos(a)))
    n = len(angles)
    faces = []
    for j in range(n - 1):
        faces.append((j, j + 1, 2 * n + j + 1, 2 * n + j))
        faces.append((n + j, 3 * n + j, 3 * n + j + 1, n + j + 1))
    p["yellow"].add(v, faces, smooth=True)
    p["yellow"].add(v, [(0, 2 * n, 3 * n, n), (n - 1, n + n - 1, 3 * n + n - 1, 2 * n + n - 1)])
    for y in (-0.16, 0.0, 0.16):
        rib = [(dc[0] + (hood_r + wall) * math.sin(a), y, dc[2] + (hood_r + wall) * math.cos(a)) for a in angles[2:-2:4]]
        for q0, q1 in zip(rib[:-1], rib[1:]):
            beam = np.array(q1) - np.array(q0)
            L = np.linalg.norm(beam)
            ax = beam / L
            nrm = (np.array(q0) + np.array(q1)) / 2 - dc
            nrm = nrm - ax * (nrm @ ax)
            nrm /= np.linalg.norm(nrm)
            rot = np.column_stack([ax, np.cross(nrm, ax), nrm])
            box(p["yellow"], (np.array(q0) + np.array(q1)) / 2 + nrm * 0.004, (L / 2 + 0.002, 0.004, 0.005), rot=rot, ch=0.001)
    for s in (-1, 1):
        lathe(p["yellow"], dc + np.array((0, s * half, 0)), (0, s, 0), [(0.0, 0.0), (hood_r + 0.008, 0.0), (hood_r + 0.008, 0.006), (0.04, 0.006), (0.036, 0.016), (0.0, 0.016)], 44)
        ring_bolts(p, dc + np.array((0, s * (half + 0.006), 0)), (0, s, 0), 0.065, 8, rb=0.0028, h=0.003)
        ring_bolts(p, dc + np.array((0, s * (half + 0.016), 0)), (0, s, 0), 0.026, 6, rb=0.0024, h=0.003)
        box(p["yellow"], (0.165, s * (half - 0.004), 0.02), (0.075, 0.006, 0.018), ch=0.002)
    # Rubber skirt on the shroud's rear edge, near the plate.
    a = math.radians(318)
    box(p["rubber"], (dc[0] + 0.083 * math.sin(a), 0, dc[2] + 0.083 * math.cos(a) + 0.002), (0.004, half - 0.004, 0.009), ch=0.001)
    # Drum motor on the right end.
    lathe(p["motor"], dc + np.array((0, -half - 0.016, 0)), (0, -1, 0), [(0.0, 0.0), (0.034, 0.0), (0.034, 0.04), (0.03, 0.044), (0.0, 0.044)], 28)
    ring_bolts(p, dc + np.array((0, -half - 0.06, 0)), (0, -1, 0), 0.02, 6, rb=0.0024, h=0.003)
    # Waste filter canister with a corrugated hose from the shroud.
    lathe(p["bottle"], (0.09, -0.115, -0.078), (0, 1, 0), [(0.0, 0.0), (0.042, 0.0), (0.046, 0.004), (0.046, 0.226), (0.042, 0.23), (0.0, 0.23)], 36)
    for y in (-0.08, 0.08):
        lathe(p["steel"], (0.09, y, -0.078), (0, 1, 0), [(0.0475, -0.008), (0.0475, 0.008)], 36, caps=False)
    start, end = dc + np.array((-0.012, 0.0, -hood_r - wall)), np.array((0.105, 0.0, -0.118))
    axis = end - start
    prof = []
    L = np.linalg.norm(axis)
    for i in range(int(L / 0.009)):
        z = i * 0.009
        prof += [(0.021, z), (0.0245, z + 0.0045)]
    lathe(p["rubber"], start, axis, prof, 18)
    lathe(p["steel"], start, axis, [(0.0275, -0.002), (0.0275, 0.012)], 18, caps=False)
    # Hydraulic hoses with crimped fittings, and a cable loom.
    def hose(a, b, drop, key="rubber", r=0.0062):
        a, b = np.array(a, float), np.array(b, float)
        d = (b - a) / np.linalg.norm(b - a)
        pts = [a, a + d * 0.05 + np.array((0, 0, -drop)), b - d * 0.05 + np.array((0, 0, -drop)), b]
        tube(p[key], pts, r, bend=0.028, seg=10)
        for q, u in ((a, pts[1] - a), (b, pts[2] - b)):
            u = u / np.linalg.norm(u)
            cyl(p["steel"], q, q + u * 0.022, r + 0.0022, 8, ch=0.0008)
            cyl(p["brass"], q - u * 0.006, q, r + 0.0032, 6, ch=0.0006)
    hose((-0.05, -0.108, -0.095), (0.215, -half - 0.03, 0.0), 0.022)
    hose((-0.03, -0.098, -0.103), (0.25, -half - 0.03, -0.02), 0.03)
    hose((-0.235, -0.11, -0.085), (R.TRACK_X[0], -0.145, -0.012), 0.012)
    hose((-0.21, -0.098, -0.103), (R.TRACK_X[0] + 0.03, 0.145, -0.012), 0.05)
    hose((-0.035, 0.085, -0.09), (0.04, 0.0, -0.13), 0.005, key="cable", r=0.0045)
    hose((-0.005, 0.02, -0.11), (0.13, 0.10, -0.098), 0.012, key="cable", r=0.0042)
    hose((-0.005, -0.02, -0.11), (0.13, -0.10, -0.098), 0.012, key="cable", r=0.0042)
    # Lamps in guards on the frame's front, aimed ahead and off the plate. Real spot lights sit at the same place.
    n = np.array((1, 0, -0.22)) / np.linalg.norm((1, 0, -0.22))
    for s in (-1, 1):
        c = np.array(R.LAMP_LOCAL) * np.array((1, s, 1))
        lathe(p["motor"], c, n, [(0.0, -0.055), (0.026, -0.055), (0.028, -0.05), (0.028, 0.0), (0.032, 0.002), (0.032, 0.012), (0.027, 0.014)], 24)
        lathe(p["led"], c + n * 0.0146, n, [(0.0, 0.0), (0.024, 0.0), (0.024, 0.0004), (0.0, 0.0004)], 24)
        for ang in (0.0, 2.09, 4.19):
            m_ = frame_of(n)
            q = m_ @ np.array((math.cos(ang), math.sin(ang), 0.0)) * 0.03
            cyl(p["steel"], c + q, c + q + n * 0.035, 0.0018, 6)
        lathe(p["steel"], c + n * 0.035, n, [(0.028, 0.0), (0.032, 0.0), (0.032, 0.003), (0.028, 0.003)], 24, caps=False)
        box(p["yellow"], c + np.array((-0.03, 0, 0.028)), (0.014, 0.012, 0.024), ch=0.002)
    # Pan-tilt inspection camera on a short post between the lamps.
    cc = np.array((0.128, 0, -0.098))
    cyl(p["motor"], (0.128, 0, -0.03), cc, 0.014, 14, ch=0.002)
    lathe(p["motor"], cc, (0.8, 0, -0.6), [(0.0, -0.022), (0.026, -0.022), (0.026, 0.0), (0.0, 0.0)], 24)
    lathe(p["glass"], cc, (0.8, 0, -0.6), [(0.0245, 0.0), (0.022, 0.008), (0.016, 0.014), (0.008, 0.0175), (0.0, 0.0185)], 24, caps=False)
    # Lift bail for the launch crane.
    bail = [np.array(q, float) for q in ((-0.285, -0.09, -0.05), (-0.285, -0.09, -0.165), (-0.285, 0.09, -0.165), (-0.285, 0.09, -0.05))]
    tube(p["steel"], bail, 0.0065, bend=0.024, seg=12)
    for s in (-1, 1):
        box(p["yellow"], (-0.285, s * 0.09, -0.045), (0.016, 0.016, 0.006), ch=0.002)
    # Tether termination on the recorded point: a ribbed bend restrictor.
    tl = np.array(R.TETHER_LOCAL)
    prof = [(0.03, 0.0), (0.03, 0.012)]
    for i in range(7):
        z = 0.012 + i * 0.012
        r_ = 0.029 - i * 0.0022
        prof += [(r_, z), (r_ - 0.0045, z + 0.006)]
    prof += [(0.009, 0.1), (0.0085, 0.1)]
    lathe(p["rubber"], tl, (-1, 0, 0), prof, 24)
    lathe(p["brass"], tl, (1, 0, 0), [(0.034, 0.0), (0.034, 0.012), (0.0, 0.012)], 20)
    return p.build("solid_robot_chassis", coll)


class Tracks:
    """Belt and shoes over the recorded rollers. Shoes travel with the recorded track travel, and the hull-side run lifts with the recorded roller springs. Nothing here is keyed by hand."""

    def __init__(self, m, coll, chassis):
        self.shoe_me = self._shoe_mesh(m)
        self.sprocket_me = self._sprocket_mesh(m)
        self.objs = {0: [], 1: []}
        self.belts = {}
        self.wheels = {0: [], 1: []}
        for side in (0, 1):
            for i in range(R.SHOES):
                ob = bpy.data.objects.new(f"solid_track_{side}_{i:02d}", self.shoe_me)
                ob.rotation_mode = "XYZ"
                ob.parent = chassis
                coll.objects.link(ob)
                self.objs[side].append(ob)
            me = bpy.data.meshes.new(f"belt_{side}")
            ob = bpy.data.objects.new(f"solid_belt_{side}", me)
            ob.parent = chassis
            me.materials.append(m["rubber"])
            coll.objects.link(ob)
            self.belts[side] = ob
            for x in R.TRACK_X:
                sp = bpy.data.objects.new(f"solid_sprocket_{side}_{x:+.2f}", self.sprocket_me)
                sp.parent = chassis
                sp.rotation_mode = "XYZ"
                sp.location = (x, (1 if side == 0 else -1) * R.TRACK_Y, R.IDLER_Z)
                coll.objects.link(sp)
                self.wheels[side].append(sp)

    def _shoe_mesh(self, m):
        """One track shoe, outer face at local z = 0, going inward to -z: rubber pad, magnet block, steel back plate and bolts."""
        p = Parts(m)
        L, W = R.SHOE_LEN / 2, R.SHOE_W / 2
        box(p["pu"], (0, 0, -0.0045), (L, W, 0.0045), ch=0.0018)
        box(p["steel"], (0, 0, -0.0005), (L * 0.56, W * 0.46, 0.0012), ch=0.0005)
        box(p["steel"], (0, 0, -0.0115), (L + 0.002, W + 0.002, 0.0025), ch=0.0008)
        for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            c = np.array((sx * L * 0.62, sy * W * 0.70, -0.0005))
            cyl(p["steel"], c - np.array((0, 0, 0.0005)), c + np.array((0, 0, 0.0003)), 0.0026, 6)
        return p.mesh("shoe")

    def _sprocket_mesh(self, m):
        p = Parts(m)
        r = R.SPROCKET_R
        lathe(p["motor"], (0, 0, 0), (0, 1, 0), [(0.0, -0.041), (r, -0.041), (r, -0.034), (0.024, -0.03), (0.024, 0.03), (r, 0.034), (r, 0.041), (0.0, 0.041)], 32)
        for s in (-1, 1):
            for i in range(5):
                a = 2 * math.pi * i / 5
                c = np.array((math.cos(a) * r * 0.62, s * 0.0412, math.sin(a) * r * 0.62))
                lathe(p["dark"], c, (0, s, 0), [(0.0, 0.0), (0.0062, 0.0), (0.0062, 0.0004), (0.0, 0.0004)], 12)
            ring_bolts(p, (0, s * 0.041, 0), (0, s, 0), 0.012, 5, rb=0.0022, h=0.003)
            for i in range(12):
                a = 2 * math.pi * (i + 0.5) / 12
                c = np.array((math.cos(a) * r, s * 0.0375, math.sin(a) * r))
                rot = np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
                box(p["motor"], c, (0.005, 0.0035, 0.0042), rot=rot, ch=0.0012)
        return p.mesh("sprocket")

    def update(self, rec, t):
        travel, spring = rec.track_state(t)
        for side in (0, 1):
            sign = 1 if side == 0 else -1
            x, z, th = R.shoe_poses(travel[side], spring[side])
            for ob, xi, zi, ti in zip(self.objs[side], x, z, th):
                ob.location = (xi, sign * R.TRACK_Y, zi)
                ob.rotation_euler = (0.0, ti, 0.0)
            px, pz = R.belt_path(spring[side])
            seg = np.array(((-1, -0.0145), (1, -0.0145), (1, -0.0085), (-1, -0.0085)))
            hw = R.SHOE_W / 2 - 0.006
            nx, nz = R.path_normals(px, pz)
            n = len(px)
            verts = np.zeros((n * 4, 3))
            for j, (sw, off) in enumerate(seg):
                verts[j::4, 0] = px + nx * off
                verts[j::4, 1] = sign * R.TRACK_Y + sw * hw
                verts[j::4, 2] = pz + nz * off
            me = self.belts[side].data
            if not len(me.vertices):
                f = [(i * 4 + j, ((i + 1) % n) * 4 + j, ((i + 1) % n) * 4 + (j + 1) % 4, i * 4 + (j + 1) % 4) for i in range(n) for j in range(4)]
                me.from_pydata(verts.tolist(), [], f)
                me.polygons.foreach_set("use_smooth", [True] * len(f))
            else:
                me.vertices.foreach_set("co", verts.ravel())
            me.update()
            for sp in self.wheels[side]:
                sp.rotation_euler = (0.0, -travel[side] / R.SPROCKET_R, 0.0)
        return travel


def set_pose(rec, objs, t):
    pos, q = rec.pose(t)
    for i, body in enumerate(rec.labels):
        ob = objs[body]
        ob.location = pos[i].tolist()
        ob.rotation_quaternion = (q[i, 3], q[i, 0], q[i, 1], q[i, 2])


def build_robot(rec, m, coll):
    objs = {"chassis": build_chassis(m, coll)}
    roller = build_roller(m, coll).mesh("roller")
    for body in rec.labels:
        if body.startswith("roller_"):
            ob = bpy.data.objects.new("solid_robot_" + body, roller)
            ob.rotation_mode = "QUATERNION"
            coll.objects.link(ob)
            objs[body] = ob
    objs["drum"] = build_drum(m, coll).build("solid_robot_drum", coll)
    return objs


def build_hardware(m, coll):
    """Things found on a ship's bottom, mounted on the plate: zinc anodes and a sea-chest grating. Away from every lane, checked by hull_check.py."""
    p = Parts(m)
    boxes = []
    for x, y in ((-0.6, -1.15), (2.1, -1.15), (4.9, -1.15), (7.6, -1.15), (0.6, 3.12), (5.6, 3.12)):
        box(p["zinc"], (x, y, -0.03), (0.34, 0.052, 0.018), ch=0.006)
        for s in (-1, 1):
            box(p["steel"], (x + s * 0.40, y, -0.02), (0.07, 0.012, 0.005), ch=0.001)
            box(p["steel"], (x + s * 0.46, y, -0.012), (0.012, 0.012, 0.012), ch=0.001)
        boxes.append({"kind": "anode", "min": [x - 0.48, y - 0.055, -0.05], "max": [x + 0.48, y + 0.055, 0.0]})
    gx, gy = 3.1, 2.98
    box(p["dark"], (gx, gy, -0.002), (0.62, 0.28, 0.0015), ch=0.0002)
    for i in range(23):
        x = gx - 0.57 + i * 1.14 / 22
        box(p["paint"], (x, gy, -0.012), (0.007, 0.25, 0.01), ch=0.0015)
    for s in (-1, 1):
        box(p["paint"], (gx, gy + s * 0.26, -0.012), (0.60, 0.012, 0.012), ch=0.002)
        box(p["paint"], (gx + s * 0.60, gy, -0.012), (0.012, 0.26, 0.012), ch=0.002)
    boxes.append({"kind": "sea_chest", "min": [gx - 0.62, gy - 0.28, -0.026], "max": [gx + 0.62, gy + 0.28, 0.0]})
    ob = p.build("visual_hardware", coll)
    return ob, boxes


def water_world(sc):
    """Open water beyond the hull: deep below, brighter toward the surface, with a shimmer far off. Art."""
    w = bpy.data.worlds.new("water")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    g = IS.G.__new__(IS.G)
    g.nt, g.mat = nt, None
    co = nt.nodes.new("ShaderNodeTexCoord").outputs["Generated"]
    g.obj = co
    sep = g.xyz(co)
    z = sep[2]
    t = nt.nodes.new("ShaderNodeValue")
    t.name = "water_t"
    lp = nt.nodes.new("ShaderNodeLightPath")
    deep = g.cmix(g.rng(z, -0.16, 0.13, 0, 1), (0.0012, 0.012, 0.015), (0.008, 0.085, 0.082))
    upper = g.cmix(g.rng(z, 0.06, 0.20, 0, 1), deep, (0.024, 0.19, 0.175))
    wave = nt.nodes.new("ShaderNodeTexNoise")
    wave.noise_dimensions = "4D"
    wave.inputs["Scale"].default_value = 30.0
    wave.inputs["Detail"].default_value = 4.0
    m = nt.nodes.new("ShaderNodeMapping")
    nt.links.new(co, m.inputs["Vector"])
    m.inputs["Scale"].default_value = (0.35, 0.35, 6.0)
    nt.links.new(m.outputs[0], wave.inputs["Vector"])
    nt.links.new(g.mul(t.outputs[0], 0.5), wave.inputs["W"])
    shim = g.mul(g.rng(wave.outputs["Fac"], 0.48, 0.66, 0.0, 1.0), g.rng(z, 0.05, 0.17, 0.0, 1.0))
    cam = g.cmix(g.mul(shim, 0.7), upper, (0.10, 0.46, 0.40))
    ambient = g.cmix(g.rng(z, -0.6, 0.5, 0, 1), (0.026, 0.17, 0.165), (0.08, 0.38, 0.36))
    colour = g.cmix(lp.outputs["Is Camera Ray"], ambient, cam)
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(colour, bg.inputs[0])
    bg.inputs[1].default_value = 1.0
    o = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs[0], o.inputs[0])
    sc.world = w
    return t.outputs[0]


def build_shafts(coll, centre_x):
    """God rays: long soft cards past the bilge, out in open water, added on top of what is behind them. Art: the sun itself is not simulated."""
    rng = np.random.default_rng(5)
    v, f, cu = [], [], []
    for i in range(44):
        top = np.array((centre_x + rng.uniform(-30, 30), rng.uniform(7.5, 44.0), WATERLINE_Z))
        down = np.array((rng.normal(0.10, 0.03), -0.23 + rng.normal(0, 0.02), -1.0))
        L = rng.uniform(14, 34)
        w0, w1 = rng.uniform(0.3, 1.4), rng.uniform(0.7, 2.6)
        side = np.array((1.0, 0.0, 0.0))
        end = top + down * L
        n = len(v)
        seed = rng.random()
        v += [top - side * w0, top + side * w0, end + side * w1, end - side * w1]
        f.append((n, n + 1, n + 2, n + 3))
        cu += [(0, 0, seed), (1, 0, seed), (1, 1, seed), (0, 1, seed)]
    me = bpy.data.meshes.new("shafts")
    me.from_pydata([list(p) for p in v], [], f)
    at = me.attributes.new("cu", "FLOAT_VECTOR", "POINT")
    at.data.foreach_set("vector", np.array(cu).ravel())
    g = WaterG("shaft")
    a = g.attr("cu")
    u, vv, seed = g.xyz(a.outputs["Vector"])
    cross = g.math("SUBTRACT", 1.0, g.math("ABSOLUTE", g.math("SUBTRACT", g.mul(u, 2.0), 1.0)))
    cross = g.mul(cross, cross)
    fade = g.mul(g.rng(vv, 0.0, 0.12, 0.3, 1.0), g.rng(vv, 0.3, 1.0, 1.0, 0.0))
    t = g.attr("water_t", "OBJECT").outputs["Fac"]
    flick = g.n("ShaderNodeTexNoise")
    flick.noise_dimensions = "4D"
    flick.inputs["Scale"].default_value = 0.35
    flick.inputs["Detail"].default_value = 1.0
    g.nt.links.new(g.obj, flick.inputs["Vector"])
    g.nt.links.new(g.mul(t, 0.28), flick.inputs["W"])
    strength = g.mul(g.mul(cross, fade), g.rng(flick.outputs["Fac"], 0.28, 0.72, 0.0, 1.0))
    e = g.n("ShaderNodeEmission")
    e.inputs[0].default_value = (0.20, 0.72, 0.62, 1)
    g.nt.links.new(g.mul(strength, 0.085), e.inputs[1])
    tr = g.n("ShaderNodeBsdfTransparent")
    s = g.n("ShaderNodeAddShader")
    g.nt.links.new(e.outputs[0], s.inputs[0])
    g.nt.links.new(tr.outputs[0], s.inputs[1])
    me.materials.append(g.plain(s.outputs[0]))
    ob = bpy.data.objects.new("visual_shafts", me)
    ob.visible_shadow = False
    ob.visible_diffuse = False
    ob.visible_glossy = False
    coll.objects.link(ob)
    return ob


def snow_material():
    g = WaterG("marine_snow")
    b = g.principled()
    g.link(b.inputs["Base Color"], (0.26, 0.29, 0.26))
    g.link(b.inputs["Roughness"], 0.9)
    t = g.n("ShaderNodeBsdfTranslucent")
    g.nt.links.new(g.transmit(), t.inputs[0])
    m = g.n("ShaderNodeMixShader")
    m.inputs[0].default_value = 0.45
    g.nt.links.new(b.outputs[0], m.inputs[1])
    g.nt.links.new(t.outputs[0], m.inputs[2])
    e = g.n("ShaderNodeEmission")
    e.inputs[0].default_value = (0.10, 0.30, 0.33, 1)
    e.inputs[1].default_value = 0.22
    a = g.n("ShaderNodeAddShader")
    g.nt.links.new(m.outputs[0], a.inputs[0])
    g.nt.links.new(e.outputs[0], a.inputs[1])
    g._tint_bsdfs(g.transmit())
    return g.plain(a.outputs[0])


def tetra_mesh(name, p, size, seed):
    """Small irregular flakes at points."""
    rng = np.random.default_rng(seed)
    n = len(p)
    base = np.array(((1, 1, 1), (-1, -1, 1), (-1, 1, -1), (1, -1, -1)), float) * 0.58
    jitter = rng.normal(1.0, 0.25, (n, 4, 3))
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    v = p[:, None, :] + (base[None] * jitter @ q.T) * size[:, None, None]
    faces = np.array(((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)))
    f = (faces[None] + (np.arange(n) * 4)[:, None, None]).reshape(-1, 3)
    me = bpy.data.meshes.new(name)
    me.from_pydata(v.reshape(-1, 3).tolist(), [], f.tolist())
    return me


def build_snow(coll, centre):
    rng = np.random.default_rng(3)
    mat = snow_material()
    layers = []
    for k, (n, lo, hi, speed, near) in enumerate(((12000, 0.0006, 0.0016, 1.0, False), (2500, 0.0016, 0.0032, 0.85, False), (16000, 0.0004, 0.0015, 0.9, True))):
        if near:  # Dense around the camera's path, where the lamp lights them.
            p = np.column_stack([rng.uniform(centre[0] - 4, centre[0] + 6, n), rng.uniform(centre[1] - 6.5, centre[1] + 1.5, n), rng.uniform(-3.2, -0.05, n)])
        else:
            p = np.column_stack([rng.uniform(centre[0] - 9, centre[0] + 9, n), rng.uniform(centre[1] - 14, centre[1] + 6, n), rng.uniform(-6.5, -0.06, n)])
        me = tetra_mesh(f"snow{k}", p, rng.uniform(lo, hi, n) ** 1.0, 40 + k)
        me.materials.append(mat)
        ob = bpy.data.objects.new(f"visual_snow_{k}", me)
        coll.objects.link(ob)
        layers.append((ob, speed))
    return layers


class Plume:
    """Waste from the brushes: flakes and soft puffs, rebuilt each frame from hull_record.plume. Picture only."""

    def __init__(self, coll):
        g = WaterG("plume_flake")
        b = g.principled()
        g.link(b.inputs["Base Color"], g.cmix(g.rng(g.attr("tone").outputs["Fac"], 0.0, 1.0, 0, 1), (0.05, 0.055, 0.025), (0.12, 0.09, 0.05)))
        g.link(b.inputs["Roughness"], 0.85)
        self.flake_mat = g.finish(b.outputs[0])
        g = WaterG("plume_puff")
        a = g.attr("sp").outputs["Vector"]
        u, v, op = g.xyz(a)
        du, dv = g.math("SUBTRACT", u, 0.5), g.math("SUBTRACT", v, 0.5)
        d = g.math("SQRT", g.math("ADD", g.mul(du, du), g.mul(dv, dv)))
        soft = g.rng(d, 0.08, 0.5, 1.0, 0.0)
        n = g.noise(16.0, 4.0, 0.6)
        alpha = g.mul(g.mul(soft, op), g.rng(n, 0.34, 0.66, 0.35, 1.0))
        dif = g.n("ShaderNodeBsdfDiffuse")
        dif.inputs[0].default_value = (0.105, 0.098, 0.066, 1)
        e = g.n("ShaderNodeEmission")
        e.inputs[0].default_value = (0.030, 0.052, 0.042, 1)
        e.inputs[1].default_value = 0.5
        add = g.n("ShaderNodeAddShader")
        g.nt.links.new(dif.outputs[0], add.inputs[0])
        g.nt.links.new(e.outputs[0], add.inputs[1])
        tr = g.n("ShaderNodeBsdfTransparent")
        m = g.n("ShaderNodeMixShader")
        g.nt.links.new(alpha, m.inputs[0])
        g.nt.links.new(tr.outputs[0], m.inputs[1])
        g.nt.links.new(add.outputs[0], m.inputs[2])
        self.puff_mat = g.plain(m.outputs[0])
        self.flakes = bpy.data.objects.new("visual_plume_flakes", bpy.data.meshes.new("pf"))
        self.puffs = bpy.data.objects.new("visual_plume_puffs", bpy.data.meshes.new("pp"))
        self.puffs.visible_shadow = False
        self.puffs.visible_diffuse = False
        self.puffs.visible_glossy = False
        coll.objects.link(self.flakes)
        coll.objects.link(self.puffs)

    def update(self, rec, t, eye):
        p, age, size, _ = R.plume(rec, t)
        keep = age < 7.0
        p, age, size = p[keep], age[keep], size[keep]
        me = self.flakes.data
        me.clear_geometry()
        if len(p):
            flakes = np.arange(len(p)) % 3 == 0
            q = p[flakes]
            s = size[flakes] * 0.0015 * (1 + age[flakes] * 0.02)
            new = tetra_mesh("tmp", q, s, 9)
            cos = np.zeros(len(new.vertices) * 3)
            new.vertices.foreach_get("co", cos)
            idx = np.zeros(len(new.polygons) * 3, np.int32)
            new.polygons.foreach_get("vertices", idx)
            me.from_pydata(cos.reshape(-1, 3).tolist(), [], idx.reshape(-1, 3).tolist())
            bpy.data.meshes.remove(new)
            tone = (np.arange(len(q)) * 0.6180339) % 1.0
            at = me.attributes.new("tone", "FLOAT", "POINT")
            at.data.foreach_set("value", np.repeat(tone, 4))
            me.materials.clear()
            me.materials.append(self.flake_mat)
        me2 = self.puffs.data
        me2.clear_geometry()
        pick = np.arange(len(p)) % 16 == 1
        if pick.any():
            c = p[pick]
            a = age[pick]
            r = 0.05 + 0.05 * a ** 0.8
            op = 0.20 * np.minimum(a / 0.35, 1.0) * np.exp(-a / 2.2)
            to_eye = eye - c
            to_eye /= np.linalg.norm(to_eye, axis=1, keepdims=True)
            side = np.cross(to_eye, (0, 0, 1.0))
            side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-6)
            up = np.cross(side, to_eye)
            corners = np.stack([c - side * r[:, None] - up * r[:, None], c + side * r[:, None] - up * r[:, None], c + side * r[:, None] + up * r[:, None], c - side * r[:, None] + up * r[:, None]], axis=1)
            # Puffs stay on the water side of the plate.
            corners[..., 2] = np.minimum(corners[..., 2], -0.002)
            n = len(c)
            f = np.arange(n * 4).reshape(-1, 4)
            me2.from_pydata(corners.reshape(-1, 3).tolist(), [], f.tolist())
            at = me2.attributes.new("sp", "FLOAT_VECTOR", "POINT")
            uv = np.tile(np.array(((0, 0), (1, 0), (1, 1), (0, 1)), float), (n, 1))
            at.data.foreach_set("vector", np.column_stack([uv, np.repeat(op, 4)]).ravel())
            me2.materials.clear()
            me2.materials.append(self.puff_mat)


def tether_points(rec, t):
    """A visual path: from the recorded boot point, a soft sag toward the tender's side. It never touches the physics. The current bows it."""
    pos, q = rec.pose(t)
    m = IS.qmat(q[0])
    boot_dir = m @ np.array((-1.0, 0, 0))
    boot = pos[0] + m @ (np.array(R.TETHER_LOCAL) + np.array((-0.10, 0, 0)))
    end = np.array(R.TETHER_ANCHOR, float)
    cur = rec.world["current"]
    a = math.radians(cur["dir_deg"])
    bow = np.array((math.cos(a), math.sin(a), 0.0)) * cur["speed_ms"]
    p1 = boot + boot_dir * 0.55 + np.array((0, -0.12, -0.75))
    p2 = boot + (end - boot) * 0.22 + bow * 1.2 + np.array((0, 0, -3.2))
    u = np.linspace(0, 1, 90)[:, None]
    pts = (1 - u) ** 3 * boot + 3 * u * (1 - u) ** 2 * p1 + 3 * u ** 2 * (1 - u) * p2 + u ** 3 * end
    sway = np.sin(u * 14.0 + t * 0.9) * 0.012 * u * (1 - u) * 4
    pts = pts + np.column_stack([sway, sway * 0.5, sway * 0.7])
    return pts


class Tether:
    def __init__(self, coll, mats):
        self.me = bpy.data.meshes.new("tether")
        self.mat = mats["orange"]
        self.ob = bpy.data.objects.new("visual_tether", self.me)
        coll.objects.link(self.ob)

    def update(self, rec, t):
        pts = tether_points(rec, t)
        seg = 10
        ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
        tan = np.gradient(pts, axis=0)
        tan /= np.linalg.norm(tan, axis=1, keepdims=True)
        a = np.cross(tan, (0.0, 0.0, 1.0))
        a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-6)
        b = np.cross(tan, a)
        r = 0.008
        v = pts[:, None, :] + (a[:, None, :] * np.cos(ang)[None, :, None] + b[:, None, :] * np.sin(ang)[None, :, None]) * r
        n = len(pts)
        f = [(i * seg + j, i * seg + (j + 1) % seg, (i + 1) * seg + (j + 1) % seg, (i + 1) * seg + j) for i in range(n - 1) for j in range(seg)]
        self.me.clear_geometry()
        self.me.from_pydata(v.reshape(-1, 3).tolist(), [], f)
        self.me.polygons.foreach_set("use_smooth", [True] * len(f))
        self.me.materials.clear()
        self.me.materials.append(self.mat)


def place_camera(cam, eye, target, up, focus, lens, fstop):
    cam.location = eye.tolist()
    f = Vector((target - eye).tolist()).normalized()
    u = Vector(up.tolist())
    r = f.cross(u).normalized()
    u2 = r.cross(f)
    from mathutils import Matrix
    m = Matrix((r, u2, -f)).transposed()
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = m.to_quaternion()
    d = cam.data
    d.lens = lens
    d.sensor_width = 36.0
    d.clip_start = 0.03
    d.clip_end = 300.0
    d.dof.use_dof = fstop < 15.9
    d.dof.aperture_fstop = fstop
    d.dof.aperture_blades = 7
    fwd = m.to_quaternion() @ Vector((0, 0, -1))
    d.dof.focus_distance = max(0.2, (Vector(focus.tolist()) - Vector(eye.tolist())).dot(fwd))


def main():
    a = parse_args()
    shot = dict(R.SHOTS[a.shot])
    if a.override:
        shot.update(json.loads(a.override))
    rec = R.Record(shot["run"])
    scan = shot["kind"] == "orbit"
    WATER["scale"] = float(shot.get("water", 0.22 if scan else 1.0))
    WATER["caustic"] = 0.15 if scan else 1.0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    IS.setup_render(a)
    sc.cycles.transparent_max_bounces = 48
    sc.cycles.caustics_refractive = False
    sc.render.film_transparent = False
    world_t = water_world(sc)
    coll = sc.collection
    t_build = time.time()

    ny, nx = rec.shape
    image = bpy.data.images.new("fouling", nx, ny, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"

    def set_image(t):
        s, b = rec.fouling(t)
        cleaned = np.clip((rec.s0 - s) + (rec.b0 - b), 0, 1)
        px = np.dstack([s, b, cleaned, np.ones_like(s)]).astype(np.float32)
        image.pixels.foreach_set(px.ravel())
        image.update()
        return s, b

    t_ref = shot["t"]
    pos0 = rec.pose(t_ref)[0][0]
    mats = hardware_materials()
    hull = build_hull(rec, image, coll)
    seams, seam_info = build_seams(rec, image, coll)
    barnacle, scars = build_barnacles(rec, image, coll)
    marks = build_marks(rec, image, coll)
    hardware, hw_boxes = build_hardware(mats, coll)
    # SimFoundry's capture rule: an object that leaves the frame can come out missing. The anodes would, so the scan leaves them out.
    hardware.hide_render = scan
    robot = build_robot(rec, mats, coll)
    tracks = Tracks(mats, coll, robot["chassis"])
    objs_t = [hull, seams] + marks
    tether = Tether(coll, mats)
    snow = []
    plume = None
    shafts = None
    if not scan:
        snow = build_snow(coll, (2.3 + 0.0, 1.6))
        plume = Plume(coll)
        shafts = build_shafts(coll, 2.3)
        objs_t.append(shafts)
    (out / "manifest.json").write_text(json.dumps({"seams": seam_info, "visual_boxes": hw_boxes, "visual_objects": sorted(o.name for o in bpy.data.objects if o.name.startswith("visual_")), "solid_objects": len([o for o in bpy.data.objects if o.name.startswith("solid_")])}))
    print("hull built in %.1f s, %d triangles" % (time.time() - t_build, sum(len(o.data.polygons) for o in bpy.data.objects if o.type == "MESH")), flush=True)

    # Lights. A hand lamp on the film camera, lamps on the robot, and open water for the rest.
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    coll.objects.link(cam)
    sc.camera = cam
    lamp = bpy.data.lights.new("cam_lamp", "SPOT")
    lamp.color = (1.0, 0.95, 0.86)
    lamp.energy = float(shot.get("lamp_w", 300.0))
    lamp.spot_size = math.radians(112)
    lamp.spot_blend = 0.9
    lamp.shadow_soft_size = 0.09
    lamp_ob = bpy.data.objects.new("visual_cam_lamp", lamp)
    coll.objects.link(lamp_ob)
    robot_lamps = []
    for s in (-1, 1):
        rl = bpy.data.lights.new(f"robot_lamp_{s}", "SPOT")
        rl.color = (1.0, 0.93, 0.80)
        rl.energy = 14.0
        rl.spot_size = math.radians(75)
        rl.spot_blend = 0.8
        rl.shadow_soft_size = 0.018
        ob = bpy.data.objects.new(f"visual_robot_lamp_{s}", rl)
        coll.objects.link(ob)
        ob.parent = robot["chassis"]
        ob.location = (0.14, s * 0.05, -0.018)
        ob.rotation_mode = "XYZ"
        ob.rotation_euler = (0.0, math.radians(90 + 14), 0.0)
        robot_lamps.append(ob)

    if a.mode == "clip":
        if scan:
            n = int(round(shot["seconds"] * a.fps))
            times = [shot["t"]] * n
        else:
            n = int(round((shot["t1"] - shot["t0"]) * a.fps))
            times = [shot["t0"] + i / a.fps for i in range(n)]
    elif a.mode == "still":
        times = [a.t if a.t is not None else shot["t"]]
    else:
        times = [float(x) for x in a.probe_times.split(",")]
    n = len(times)
    lo, hi = float(rec.t[0]), float(rec.t[-1])
    if max(times) > hi + 1e-6 or min(times) < lo - 1e-6:
        raise SystemExit("a frame lies outside the record")
    clamp = lambda t: min(max(t, lo), hi)
    us = [(i + 0.5) / n if a.mode == "clip" else float(shot.get("u", 0.5)) for i in range(n)]

    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    bpy.context.view_layer.update()
    if not a.no_blur and not scan:
        frames = list(enumerate(times)) if a.mode == "clip" else []
        for fi, t in frames:
            set_pose(rec, robot, t)
            for ob in robot.values():
                ob.keyframe_insert("location", frame=fi + 1)
                ob.keyframe_insert("rotation_quaternion", frame=fi + 1)
        if a.mode == "still":
            t = times[0]
            for f, tt in ((0, t - 1 / a.fps), (1, t), (2, t + 1 / a.fps)):
                set_pose(rec, robot, clamp(tt))
                for ob in robot.values():
                    ob.keyframe_insert("location", frame=f)
                    ob.keyframe_insert("rotation_quaternion", frame=f)
    else:
        sc.render.use_motion_blur = False
    if scan:
        sc.render.use_motion_blur = False
    if a.mode == "probe":
        cos = np.zeros(len(robot["chassis"].data.vertices) * 3)
        robot["chassis"].data.vertices.foreach_get("co", cos)
        np.save(out / "chassis_verts.npy", cos.reshape(-1, 3))
        for name, ob in robot.items():
            ob.hide_render = name != "chassis"
        for ob in bpy.data.objects:
            if ob.type in ("MESH",) and not ob.name.startswith("solid_robot_chassis"):
                ob.hide_render = True
        gf = WaterG("flat")
        e = gf.n("ShaderNodeEmission")
        mf = gf.plain(e.outputs[0])
        ch = robot["chassis"].data
        for i in range(len(ch.materials)):
            ch.materials[i] = mf
        sc.render.film_transparent = True
        sc.render.use_motion_blur = False
        sc.cycles.samples = 4
        sc.cycles.use_denoising = False
        sc.cycles.filter_width = 0.01
        sc.render.image_settings.file_format = "PNG"
        sc.render.image_settings.color_mode = "RGBA"
        sc.render.image_settings.color_depth = "8"
        sc.render.resolution_x, sc.render.resolution_y = 960, 540

    from bpy_extras.object_utils import world_to_camera_view
    log, timing = [], []
    end = a.end_frame if a.end_frame is not None else n
    for fi in range(a.start_frame, min(end, n)):
        t = times[fi]
        eye, tgt, up, foc, lens, fstop = R.camera(shot, rec, t, us[fi])
        if a.mode == "clip" and not a.no_blur and not scan:
            sc.frame_set(fi + 1)
        elif a.mode == "still" and not a.no_blur and not scan:
            sc.frame_set(1)
        else:
            set_pose(rec, robot, t)
        place_camera(cam, eye, tgt, up, foc, lens, fstop)
        side = np.array(((tgt - eye)[1], -(tgt - eye)[0], 0.0))
        side = side / max(np.linalg.norm(side), 1e-6)
        lamp_ob.location = (eye + side * 0.55 + np.array(up) * -0.25).tolist()
        lamp_ob.rotation_mode = "QUATERNION"
        lamp_ob.rotation_quaternion = cam.rotation_quaternion
        wt = float(shot["t"]) if scan else t
        for ob in objs_t:
            ob["water_t"] = wt
        world_t.node.outputs[0].default_value = wt
        s, b = set_image(t)
        travel = tracks.update(rec, t)
        if a.mode != "probe":
            tether.update(rec, t)
        if plume is not None and a.mode != "probe":
            plume.update(rec, t, eye)
        cur = rec.world["current"]
        ca = math.radians(cur["dir_deg"])
        drift = np.array((math.cos(ca), math.sin(ca), 0.0)) * cur["speed_ms"]
        for ob, speed in snow:
            ob.location = (drift * speed * (t - shot.get("t0", t))).tolist()
        bpy.context.view_layer.update()
        name = {"clip": "frame_%04d.exr" % fi, "still": "still.exr", "probe": "probe_%02d.png" % fi}[a.mode]
        sc.render.filepath = str(out / name)
        ts = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - ts
        timing.append(dt)
        dg = bpy.context.evaluated_depsgraph_get()
        bodies = {b_: {"loc": list(ob.evaluated_get(dg).matrix_world.translation), "quat": list(ob.evaluated_get(dg).matrix_world.to_quaternion())} for b_, ob in robot.items()}
        base_px = world_to_camera_view(sc, cam, robot["chassis"].evaluated_get(dg).matrix_world.translation)
        log.append({"frame": fi, "t": t, "bodies": bodies, "cam": [list(r) for r in cam.evaluated_get(dg).matrix_world], "lens": cam.data.lens, "sensor": cam.data.sensor_width, "res": [sc.render.resolution_x, sc.render.resolution_y], "screen": list(base_px), "seconds": dt, "slime_sum": float(s.sum()), "barnacle_sum": float(b.sum()), "tether_start": tether_points(rec, t)[0].tolist(), "track_travel": [float(travel[0]), float(travel[1])], "shoe0": [list(tracks.objs[0][0].location), tracks.objs[0][0].rotation_euler[1]]})
        print("frame %d t=%.3f %.1f s" % (fi, t, dt), flush=True)
        (out / ("poses_%s_%04d.json" % (a.mode, a.start_frame))).write_text(json.dumps(log))
    print("mean seconds per frame %.1f" % (sum(timing) / max(len(timing), 1)), flush=True)


if __name__ == "__main__":
    main()
