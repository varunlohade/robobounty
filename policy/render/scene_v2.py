"""The photographic look. Run through render.py --look v2, not directly.

Same world as scene.py: x along the wall, y out of the wall is negative, z up. The robot pose and the dirt
grid come straight from the recorded trial. Everything else here is art and feeds nothing back to physics.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import city as city_gen  # noqa: E402
import data as run_data  # noqa: E402
import scene as v1  # noqa: E402
import shots as shot_list  # noqa: E402
from scene import N, add_box, dark_material, joint_profile, loft, mesh_obj, new_mat, out, pane_grid, place_camera  # noqa: E402

TEX = HERE.parents[1] / "design" / "render" / "_cache" / "tex"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="still", choices=["still", "clip"])
    ap.add_argument("--shot", default="close")
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--sky", required=True)
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--no-volume", action="store_true")
    ap.add_argument("--override", default=None, help="JSON merged over the shot, for framing tests")
    ap.add_argument("--layer", default="full", help="full, or norobotfibres for a fast test")
    return ap.parse_args(argv)


# ---------------------------------------------------------------- texture helpers

def image_node(n, name, kind, vec, colour=False, interp="Linear"):
    """A CC0 photographic map from design/render/_cache/tex."""
    path = TEX / name / f"{name}_2K-JPG_{kind}.jpg"
    if not path.exists():
        # Missing map: run on with soft noise rather than stop. assets.py fetches the real ones.
        print("texture missing, using noise:", path.name)
        noise = n.add("ShaderNodeTexNoise")
        n.link(vec, noise.inputs["Vector"])
        noise.inputs["Scale"].default_value = 9.0
        noise.inputs["Detail"].default_value = 8.0
        return noise.outputs["Color"]
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    t = n.add("ShaderNodeTexImage", interpolation=interp, extension="REPEAT")
    t.image = img
    n.link(vec, t.inputs["Vector"])
    return t.outputs["Color"]


def luma(n, col):
    m = n.add("ShaderNodeRGBToBW")
    n.link(col, m.inputs[0])
    return m.outputs[0]


def scale_col(n, col, s):
    m = n.add("ShaderNodeVectorMath", operation="SCALE")
    n.link(col, m.inputs[0])
    n.set(m.inputs["Scale"], s)
    return m.outputs[0]


# ---------------------------------------------------------------- glass

def glass_v2(run, dirt_image, haze, focus):
    mat = new_mat("glass_v2")
    n = N(mat)
    geo = n.add("ShaderNodeNewGeometry")
    px, py, pz = n.split(geo.outputs["Position"])

    s, off, ts = run.mullion_spacing, run.mullion_offset, run.transom_spacing
    fz = n.math("FRACT", n.mul(pz, 1 / ts))
    dx = n.mul(n.math("ABSOLUTE", n.sub(n.math("FRACT", n.add_(n.mul(n.sub(px, off), 1 / s), 0.5)), 0.5)), s)
    dz = n.mul(n.math("ABSOLUTE", n.sub(n.math("FRACT", n.add_(n.mul(pz, 1 / ts), 0.5)), 0.5)), ts)
    pane_x = n.math("FLOOR", n.mul(n.sub(px, off), 1 / s))
    pane_z = n.math("FLOOR", n.mul(pz, 1 / ts))
    pane = n.add("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    n.link(n.xyz(pane_x, pane_z, 3.0), pane.inputs["Vector"])
    pr = pane.outputs[0]

    # Photographic maps in metres on the wall. Each pane is its own sheet, so each gets its own offset.
    def wall_uv(tile, ox, oz, stretch=1.0):
        return n.xyz(n.add_(n.mul(px, 1 / tile), n.mul(pr, ox)), n.add_(n.mul(pz, stretch / tile), n.mul(pr, oz)), 0.0)

    imp_a = luma(n, image_node(n, "SurfaceImperfections015", "Color", wall_uv(1.25, 7.3, 3.1)))
    imp_c = luma(n, image_node(n, "SurfaceImperfections016", "Color", wall_uv(1.05, 4.1, 1.3)))
    imp_b = luma(n, image_node(n, "SurfaceImperfections003", "Color", wall_uv(1.45, 2.9, 5.7)))
    grit_i = luma(n, image_node(n, "SurfaceImperfections013", "Color", wall_uv(0.62, 5.3, 9.1)))
    prints = luma(n, image_node(n, "Fingerprints003", "Color", wall_uv(0.55, 8.3, 4.9)))
    leak_uv = n.xyz(n.add_(n.mul(px, 1 / 1.5), n.mul(pr, 3.7)), n.mul(n.sub(fz, 1.0), ts / 3.6), 0.0)
    leak = n.sub(1.0, n.mul(luma(n, image_node(n, "Leaking016A", "Roughness", leak_uv)), 7.0))
    scratch = luma(n, image_node(n, "Scratches003", "Color", wall_uv(0.9, 6.1, 2.2)))

    # Recorded dirt. Red holds the level. Green says whether the local edge runs up the wall (1) or across it (0).
    # The noise moves the sample by less than half a recorded cell, so a clean edge stays in its recorded cell.
    wob = n.sub(n.noise(n.xyz(n.mul(px, 1.0), n.mul(pz, 1.0), 2.0), 26.0, 3.0, 0.55), 0.5)
    wob2 = n.sub(n.noise(n.xyz(n.mul(px, 1.0), n.mul(pz, 1.0), 9.0), 26.0, 3.0, 0.55), 0.5)
    u = n.mul(n.sub(n.add_(px, n.mul(wob, 0.035)), run.tex_x0), 1 / run.tex_w)
    v = n.mul(n.sub(n.add_(pz, n.mul(wob2, 0.035)), run.tex_z0), 1 / run.tex_h)
    tex = n.add("ShaderNodeTexImage", interpolation="Cubic", extension="EXTEND")
    tex.image = dirt_image
    n.link(n.xyz(u, v, 0.0), tex.inputs["Vector"])
    rg = n.split(tex.outputs["Color"])
    in_area = n.mul(n.math("GREATER_THAN", u, 0.0), n.mul(n.math("LESS_THAN", u, 1.0),
                    n.mul(n.math("GREATER_THAN", v, 0.0), n.math("LESS_THAN", v, 1.0))))
    level = n.mix_f(in_area, 1.0, rg[0])
    edge_up = n.mix_f(in_area, 0.5, rg[1])

    # Wipe marks. Long thin noise along the wipe, in the direction the recorded edge runs.
    st_up_a = n.noise(n.xyz(n.mul(px, 230.0), n.mul(pz, 2.2), n.mul(pr, 11.0)), 1.0, 4.0, 0.62)
    st_up_b = n.noise(n.xyz(n.mul(px, 700.0), n.mul(pz, 6.0), n.mul(pr, 5.0)), 1.0, 2.0, 0.6)
    st_ac_a = n.noise(n.xyz(n.mul(px, 2.2), n.mul(pz, 230.0), n.mul(pr, 13.0)), 1.0, 4.0, 0.62)
    st_ac_b = n.noise(n.xyz(n.mul(px, 6.0), n.mul(pz, 700.0), n.mul(pr, 3.0)), 1.0, 2.0, 0.6)
    st_a = n.mix_f(edge_up, st_ac_a, st_up_a)
    st_b = n.mix_f(edge_up, st_ac_b, st_up_b)
    wipe_marks = n.add_(n.mul(0.7, st_a), n.mul(0.3, st_b))
    thresh = n.mul(n.sub(wipe_marks, 0.5), 0.30)
    film_mask = n.smooth(0.12, 0.36, n.add_(level, thresh))
    film_level = n.mul(film_mask, n.math("POWER", n.math("MAXIMUM", level, 0.0), 0.65))
    # The pad pushes a little dirt to the side of its path, so a thin ridge rims each clean lane.
    ridge = n.mul(n.mul(4.0, n.mul(film_mask, n.sub(1.0, film_mask))), n.smooth(0.38, 0.62, wipe_marks))

    # Dust is a soft particle veil: the veil, then cloudy patches, then the photographic mottles.
    uv3 = n.xyz(px, pz, n.mul(pr, 17.0))
    blot = n.noise(uv3, 1.9, 6.0, 0.6)
    grit = n.noise(uv3, 420.0, 3.0, 0.8)
    grit_mask = n.smooth(0.50, 0.72, grit)
    # Particle-like dust: many small soft dots at three sizes.
    def dots(scale, r, seed):
        vor = n.add("ShaderNodeTexVoronoi", feature="F1")
        n.link(n.xyz(px, pz, n.add_(n.mul(pr, 19.0), seed)), vor.inputs["Vector"])
        vor.inputs["Scale"].default_value = scale
        vor.inputs["Randomness"].default_value = 1.0
        rad = n.mul(n.add_(0.35, n.mul(n.split(vor.outputs["Color"])[0], 1.0)), r)
        return n.sub(1.0, n.smooth(n.mul(rad, 0.35), rad, vor.outputs["Distance"])), n.split(vor.outputs["Color"])[1], vor.outputs["Distance"]
    d1, _, _ = dots(620.0, 0.34, 1.0)
    d2, _, _ = dots(240.0, 0.20, 2.0)
    # Dried water spots: thin mineral rings, a few per square decimetre, with a faint inside.
    vor = n.add("ShaderNodeTexVoronoi", feature="F1")
    n.link(n.xyz(px, pz, n.add_(n.mul(pr, 23.0), 4.0)), vor.inputs["Vector"])
    vor.inputs["Scale"].default_value = 58.0
    vor.inputs["Randomness"].default_value = 0.95
    sc0, sc1, _ = n.split(vor.outputs["Color"])
    spot_r = n.add_(0.06, n.mul(0.22, n.mul(sc0, sc0)))
    dist = vor.outputs["Distance"]
    # Rings wobble: a real drop does not dry round.
    dist = n.add_(dist, n.mul(n.sub(n.noise(uv3, 180.0, 2.0, 0.5), 0.5), 0.11))
    ring = n.mul(n.smooth(n.mul(spot_r, 0.72), spot_r, dist), n.sub(1.0, n.smooth(spot_r, n.mul(spot_r, 1.13), dist)))
    fill = n.mul(0.28, n.sub(1.0, n.smooth(n.mul(spot_r, 0.5), spot_r, dist)))
    spots = n.mul(n.add_(ring, fill), n.math("GREATER_THAN", sc1, 0.56))
    spots = n.mul(spots, n.smooth(0.25, 0.42, imp_c))

    # Grime comes from photographs of real surfaces: two mottled maps, blended over the pane, then vertical run marks.
    mottled = n.mix_f(n.smooth(0.35, 0.65, blot), imp_a, imp_c)
    soft = n.add_(n.mul(0.6, mottled), n.mul(0.4, blot))
    veil = n.add_(0.16, n.mul(0.34, n.smooth(0.18, 0.55, soft)))
    veil = n.add_(veil, n.mul(0.20, n.smooth(0.10, 0.60, mottled)))
    veil = n.add_(veil, n.mul(0.26, n.smooth(0.08, 0.42, imp_b)))
    veil = n.add_(veil, n.mul(0.12, n.smooth(0.15, 0.6, grit_i)))
    veil = n.add_(veil, n.mul(0.18, n.smooth(0.05, 0.32, prints)))
    veil = n.add_(veil, n.mul(0.05, grit_mask))
    veil = n.add_(veil, n.mul(0.16, d1))
    veil = n.add_(veil, n.mul(0.14, d2))
    veil = n.add_(veil, n.mul(0.30, spots))
    # Rain runs off the transom above, down the top of each pane.
    below = n.mul(n.sub(1.0, fz), ts)
    run_off = n.mul(n.math("EXPONENT", n.mul(below, -0.7)), n.smooth(0.06, 0.45, leak))
    veil = n.add_(veil, n.mul(0.70, run_off))
    dirt_scale = run.film_gain * shot_list.FILM_OPACITY_V2
    film = n.clamp01(n.mul(n.add_(film_level, n.mul(0.20, ridge)), n.mul(veil, dirt_scale)))
    # Even a wiped lane is not clean: faint marks along the wipe, some spots and a thin smear.
    residue = n.mul(n.sub(1.0, film_mask), n.add_(n.mul(0.10, n.smooth(0.46, 0.66, wipe_marks)),
                    n.add_(n.mul(0.10, spots), n.add_(n.mul(0.05, d2), n.add_(n.mul(0.07, n.smooth(0.05, 0.3, prints)), 0.015)))))
    film = n.clamp01(n.add_(film, residue))

    # Float-glass roller wave, a fine ripple and scratches on the normal only.
    wave = n.noise(n.xyz(n.mul(px, 0.8), n.mul(pz, 2.6), n.mul(pr, 9.0)), 1.7, 2.0, 0.35)
    ripple = n.noise(n.xyz(px, pz, n.mul(pr, 4.0)), 21.0, 2.0, 0.4)
    height = n.add_(wave, n.mul(0.018, ripple))
    bump = n.add("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = shot_list.GLASS_WAVE
    n.link(height, bump.inputs["Height"])
    n.link(geo.outputs["Normal"], bump.inputs["Normal"])

    # Spandrel band, opaque, in front of each slab. Vision glass above and below it.
    span = n.sub(1.0, n.smooth(0.17, 0.175, n.math("MINIMUM", fz, n.sub(1.0, fz))))
    fres = n.add("ShaderNodeFresnel")
    fres.inputs["IOR"].default_value = 1.52
    n.link(bump.outputs[0], fres.inputs["Normal"])
    coat = n.add_(shot_list.GLASS_COAT_V2, n.mul(n.sub(pr, 0.5), 0.05))
    fac = n.add_(coat, n.mul(n.sub(1.0, coat), fres.outputs[0]))
    gloss = n.add("ShaderNodeBsdfGlossy", distribution="GGX")
    gloss.inputs["Color"].default_value = (0.90, 0.97, 0.95, 1)
    n.link(bump.outputs[0], gloss.inputs["Normal"])
    rough = n.add_(0.003, n.add_(n.mul(0.022, n.smooth(0.05, 0.4, imp_b)), n.mul(0.05, n.smooth(0.15, 0.6, scratch))))
    n.set(gloss.inputs["Roughness"], n.add_(rough, n.mul(0.20, film)))
    through = n.add("ShaderNodeBsdfTransparent")
    tint_v = n.add_(0.85, n.mul(pr, 0.3))
    n.link(scale_col(n, n.mix(0.0, (0.34, 0.42, 0.40, 1), (0.34, 0.42, 0.40, 1)), tint_v), through.inputs["Color"])
    vision = n.mixs(fac, through.outputs[0], gloss.outputs[0])
    span_d = n.add("ShaderNodeBsdfDiffuse")
    span_d.inputs["Color"].default_value = (0.006, 0.009, 0.009, 1)
    span_s = n.mixs(fac, span_d.outputs[0], gloss.outputs[0])
    glass = n.mixs(span, vision, span_s)

    # Opaque frit band round each pane. The 4 mm joint stays as recorded.
    frit = n.sub(1.0, n.smooth(run.frit_m, run.frit_m + 0.0015, n.math("MINIMUM", dx, dz)))
    frit_b = n.add("ShaderNodeBsdfPrincipled")
    frit_b.inputs["Base Color"].default_value = (0.012, 0.013, 0.014, 1)
    frit_b.inputs["Roughness"].default_value = 0.20
    n.link(bump.outputs[0], frit_b.inputs["Normal"])
    glass = n.mixs(frit, glass, frit_b.outputs[0])

    # The dirt film: a thin mineral dust, warm grey, slightly lifted in the clumps.
    tint = n.mix(n.smooth(0.3, 0.72, blot), (0.215, 0.20, 0.178, 1), (0.135, 0.128, 0.117, 1))
    tint = n.mix(n.mul(0.7, d1), tint, (0.42, 0.40, 0.36, 1))
    film_b = n.add("ShaderNodeBsdfPrincipled")
    n.link(tint, film_b.inputs["Base Color"])
    film_b.inputs["Roughness"].default_value = 0.85
    film_b.inputs["Specular IOR Level"].default_value = 0.25
    surf = n.mixs(film, glass, film_b.outputs[0])
    out(n, n.fog(surf, haze, focus))
    return mat


def alu_v2(haze, focus):
    mat = new_mat("alu_v2")
    n = N(mat)
    geo = n.add("ShaderNodeNewGeometry")
    px, py, pz = n.split(geo.outputs["Position"])
    # Brushed along the bar: a fast scale across, a slow one along. World-space, so both bar directions work.
    nrm = n.split(geo.outputs["True Normal"])
    uv = n.xyz(n.mul(n.add_(px, pz), 1 / 0.9), n.mul(n.add_(py, n.sub(px, pz)), 1 / 0.05), 0.0)
    col = image_node(n, "Metal051A", "Color", uv, colour=True)
    rgh = luma(n, image_node(n, "Metal051A", "Roughness", uv))
    rain = n.noise(n.xyz(n.mul(px, 11.0), n.mul(pz, 1.4), 0.0), 1.0, 6.0, 0.62)
    leak = n.noise(n.xyz(n.mul(px, 60.0), n.mul(pz, 3.0), 1.0), 1.0, 5.0, 0.6)
    grime = n.clamp01(n.add_(n.mul(0.55, n.smooth(0.42, 0.72, rain)), n.mul(0.45, n.smooth(0.55, 0.75, leak))))
    base = n.mix(grime, scale_col(n, col, 0.95), (0.20, 0.195, 0.185, 1))
    fine = n.noise(n.xyz(n.mul(px, 2.0), n.mul(py, 700.0), n.mul(pz, 2.0)), 1.0, 3.0, 0.5)
    bump = n.add("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.00015
    n.link(fine, bump.inputs["Height"])
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(base, b.inputs["Base Color"])
    b.inputs["Metallic"].default_value = 1.0
    n.set(b.inputs["Roughness"], n.add_(n.mul(rgh, 0.42), n.add_(0.08, n.mul(0.28, grime))))
    n.link(bump.outputs[0], b.inputs["Normal"])
    out(n, n.fog(b.outputs[0], haze, focus))
    return mat


def extrude(verts, faces, profile, a0, a1, axis):
    v1.extrude_joint(verts, faces, profile, a0, a1, axis)


def build_frame_v2(run, alu, seal):
    """The sim's caps at the sim's crown height. Mullions run through; transoms stop at them with a real butt joint.
    A wet-seal bead sits along every cap edge."""
    xs, zs = pane_grid(run)
    v, f, sv, sf = [], [], [], []
    d, r = run.mullion_depth, run.cap_r
    _, half = joint_profile(0.0, d, r)

    def bead(c, a0, a1, axis):
        for sgn in (-1, 1):
            e = c + sgn * half
            prof = [(e - 0.0035, 0.0), (e - 0.003, -0.0016), (e - 0.0012, -0.0024), (e + 0.0012, -0.0024), (e + 0.003, -0.0016), (e + 0.0035, 0.0)]
            extrude(sv, sf, prof, a0, a1, axis)

    for x in xs[1:-1]:
        pts, _ = joint_profile(x, d, r)
        extrude(v, f, pts, 0.0, run.roof_z, "z")
        bead(x, 0.0, run.roof_z, "z")
    inner = [run.tower_x0] + xs[1:-1] + [run.tower_x1]
    for z in zs[1:-1]:
        pts, _ = joint_profile(z, d, r)
        if abs(z - run.area["z0"]) > 40 and abs(z - run.area["z1"]) > 40:
            extrude(v, f, pts, run.tower_x0, run.tower_x1, "x")
            continue
        for a, b in zip(inner[:-1], inner[1:]):
            g0 = a + half + 0.0015 if a != run.tower_x0 else a
            g1 = b - half - 0.0015 if b != run.tower_x1 else b
            extrude(v, f, pts, g0, g1, "x")
            bead(z, g0 - 0.0015, g1 + 0.0015, "x")
    mesh_obj("frame", v, f, alu, smooth=True)
    mesh_obj("seal", sv, sf, seal, smooth=True)


# ---------------------------------------------------------------- behind the glass

def build_interior(run, haze, focus):
    """Offices behind the panes near the robot. Soft shapes behind tinted glass; nothing here needs to be sharp."""
    def diffuse(name, col):
        m = new_mat(name)
        n = N(m)
        b = n.add("ShaderNodeBsdfDiffuse")
        b.inputs["Color"].default_value = (*col, 1)
        out(n, b.outputs[0])
        return m

    def emit(name, col, s):
        m = new_mat(name)
        n = N(m)
        b = n.add("ShaderNodeEmission")
        b.inputs["Color"].default_value = (*col, 1)
        b.inputs["Strength"].default_value = s
        out(n, b.outputs[0])
        return m

    xs, zs = pane_grid(run)
    x0, x1 = max(run.tower_x0, -8.0), min(run.tower_x1, 10.0)
    ceil_v, ceil_f, floor_v, floor_f, wall_v, wall_f, lamp_v, lamp_f = [], [], [], [], [], [], [], []
    desk_v, desk_f, shade_v, shade_f, col_v, col_f = [], [], [], [], [], []
    rng = np.random.default_rng(23)
    depth = 9.0
    for z in zs:
        if not (run.area["z0"] - 13 < z < run.area["z1"] + 11):
            continue
        fl, cl = z + 0.62, z + 3.6 - 0.62
        add_box(floor_v, floor_f, x0, 0.12, z - 0.4, x1, depth, fl)
        add_box(ceil_v, ceil_f, x0, 0.12, cl, x1, depth, z + 3.6)
        add_box(wall_v, wall_f, x0, depth, fl, x1, depth + 0.3, cl)
        lit = rng.random() < 0.75
        for lx in np.arange(x0 + 0.6, x1 - 0.6, 1.8):
            for ly in (1.3, 3.1, 4.9, 6.7):
                if lit and rng.random() < 0.85:
                    add_box(lamp_v, lamp_f, lx - 0.3, ly - 0.3, cl - 0.012, lx + 0.3, ly + 0.3, cl - 0.002)
        for cx in np.arange(x0 + 1.2, x1, 7.5):
            add_box(col_v, col_f, cx - 0.3, 0.9, fl, cx + 0.3, 1.5, cl)
        for dx in np.arange(x0 + 0.5, x1 - 1.2, 2.6):
            for dy in (1.9, 3.8, 5.9):
                if rng.random() < 0.7:
                    add_box(desk_v, desk_f, dx, dy, fl + 0.70, dx + 1.5, dy + 0.75, fl + 0.74)
                    add_box(desk_v, desk_f, dx + 0.1, dy + 0.1, fl, dx + 0.15, dy + 0.65, fl + 0.70)
                    add_box(desk_v, desk_f, dx + 0.5, dy + 0.1, fl + 0.74, dx + 1.0, dy + 0.13, fl + 1.1)
        # Roller blinds: some panes up, some part down, a few closed.
        for a, b in zip(xs[:-1], xs[1:]):
            if b < x0 or a > x1:
                continue
            state = rng.random()
            drop = 0.0 if state < 0.45 else (rng.uniform(0.2, 0.7) if state < 0.85 else 1.0)
            if drop > 0:
                add_box(shade_v, shade_f, a + 0.04, 0.16, cl - drop * (cl - fl), b - 0.04, 0.165, cl)
    mesh_obj("in_floor", floor_v, floor_f, diffuse("carpet", (0.06, 0.06, 0.065)))
    mesh_obj("in_ceil", ceil_v, ceil_f, diffuse("ceiling", (0.55, 0.55, 0.53)))
    mesh_obj("in_wall", wall_v, wall_f, diffuse("backwall", (0.20, 0.20, 0.19)))
    mesh_obj("in_col", col_v, col_f, diffuse("column", (0.34, 0.34, 0.32)))
    if desk_v:
        mesh_obj("in_desk", desk_v, desk_f, diffuse("desk", (0.14, 0.12, 0.10)))
    if shade_v:
        mesh_obj("in_shade", shade_v, shade_f, diffuse("shade", (0.42, 0.40, 0.36)))
    if lamp_v:
        mesh_obj("in_lamp", lamp_v, lamp_f, emit("lamp", (1.0, 0.95, 0.86), shot_list.INTERIOR_LAMP))


# ---------------------------------------------------------------- robot

def resample(ring, count):
    """Even arc-length resample of a closed ring, so that long edges have vertices."""
    p = np.array(ring, float)
    seg = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, cum[-1], count, endpoint=False)
    q = np.empty((count, 3))
    closed = np.vstack([p, p[0]])
    for k in range(3):
        q[:, k] = np.interp(t, cum, closed[:, k])
    return [tuple(v) for v in q]


def shell_mats():
    """Moulded plastic: spark-eroded grain, orange-peel, faint subsurface, grime gathered in the cavities."""
    def uvmap(n, p, tile):
        px, py, pz = n.split(p)
        return n.xyz(n.mul(n.add_(px, pz), 1 / tile), n.mul(n.add_(py, n.mul(pz, 0.7)), 1 / tile), 0.0)

    def plastic(name, base, soil_col, rough, sss, coat):
        m = new_mat(name)
        n = N(m)
        p = n.add("ShaderNodeTexCoord").outputs["Object"]
        px, py, pz = n.split(p)
        spark = n.noise(p, 2600.0, 2.0, 0.6)
        peel = n.noise(p, 75.0, 2.0, 0.4)
        ao = n.add("ShaderNodeAmbientOcclusion")
        ao.samples = 4
        ao.inputs["Distance"].default_value = 0.016
        cav = n.sub(1.0, ao.outputs["AO"])
        imp = luma(n, image_node(n, "SurfaceImperfections013", "Color", uvmap(n, p, 0.42)))
        sme = luma(n, image_node(n, "Smear005", "Opacity", uvmap(n, p, 0.55)))
        fin = luma(n, image_node(n, "Fingerprints003", "Color", uvmap(n, p, 0.30)))
        sc = luma(n, image_node(n, "Scratches003", "Color", uvmap(n, p, 0.33)))
        dust = n.noise(p, 300.0, 5.0, 0.7)
        low = n.sub(1.0, n.smooth(0.03, 0.075, pz))
        soil = n.mul(0.75, n.smooth(0.15, 0.8, cav))
        soil = n.add_(soil, n.mul(0.09, n.smooth(0.05, 0.45, imp)))
        soil = n.add_(soil, n.mul(0.10, n.smooth(0.1, 0.55, sme)))
        soil = n.add_(soil, n.mul(0.30, low))
        soil = n.add_(soil, n.mul(0.22, n.smooth(0.47, 0.66, dust)))
        scuff = n.smooth(0.56, 0.68, n.noise(n.xyz(n.mul(px, 14.0), n.mul(py, 14.0), n.mul(pz, 120.0)), 1.0, 5.0, 0.62))
        soil = n.add_(soil, n.mul(0.20, n.mul(scuff, n.sub(1.0, n.smooth(0.05, 0.095, pz)))))
        soil = n.clamp01(soil)
        col = n.mix(soil, base, soil_col)
        b = n.add("ShaderNodeBsdfPrincipled")
        n.link(col, b.inputs["Base Color"])
        rg = n.add_(rough, n.add_(n.mul(0.18, n.smooth(0.1, 0.5, sc)), n.add_(n.mul(0.22, n.smooth(0.05, 0.3, fin)), n.mul(0.34, soil))))
        n.set(b.inputs["Roughness"], rg)
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Scale"].default_value = 0.004
        b.inputs["Subsurface Radius"].default_value = (1.0, 0.85, 0.7)
        n.set(b.inputs["Coat Weight"], n.mul(coat, n.sub(1.0, soil)))
        b.inputs["Coat Roughness"].default_value = 0.18
        bump = n.add("ShaderNodeBump")
        bump.inputs["Distance"].default_value = 0.00022
        n.link(n.add_(spark, n.mul(0.9, peel)), bump.inputs["Height"])
        n.link(bump.outputs[0], b.inputs["Normal"])
        out(n, b.outputs[0])
        return m

    white = plastic("shell", (0.66, 0.66, 0.635, 1), (0.30, 0.29, 0.26, 1), 0.36, 0.25, 0.18)
    panel = plastic("panel", (0.34, 0.345, 0.35, 1), (0.20, 0.195, 0.18, 1), 0.46, 0.05, 0.05)
    bumper = plastic("bumper", (0.055, 0.057, 0.06, 1), (0.13, 0.125, 0.115, 1), 0.50, 0.0, 0.0)

    rubber = new_mat("rubber_v2")
    n = N(rubber)
    p = n.add("ShaderNodeTexCoord").outputs["Object"]
    b = n.add("ShaderNodeBsdfPrincipled")
    nz = n.noise(p, 500.0, 4.0, 0.6)
    n.link(n.mix(n.smooth(0.46, 0.68, nz), (0.018, 0.018, 0.02, 1), (0.08, 0.075, 0.07, 1)), b.inputs["Base Color"])
    n.set(b.inputs["Roughness"], n.add_(0.42, n.mul(0.28, nz)))
    out(n, b.outputs[0])

    metal = new_mat("fastener_v2")
    n = N(metal)
    p = n.add("ShaderNodeTexCoord").outputs["Object"]
    nz = n.noise(p, 900.0, 3.0, 0.6)
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(n.mix(n.smooth(0.45, 0.65, nz), (0.62, 0.62, 0.61, 1), (0.28, 0.27, 0.25, 1)), b.inputs["Base Color"])
    b.inputs["Metallic"].default_value = 1.0
    n.set(b.inputs["Roughness"], n.add_(0.28, n.mul(0.3, nz)))
    out(n, b.outputs[0])

    track = new_mat("track_v2")
    n = N(track)
    px, py, pz = n.split(n.add("ShaderNodeTexCoord").outputs["Object"])
    tread = n.math("SINE", n.mul(px, 2 * math.pi / 0.012))
    bump = n.add("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.002
    n.link(tread, bump.inputs["Height"])
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.024, 0.025, 0.026, 1)
    b.inputs["Roughness"].default_value = 0.6
    n.link(bump.outputs[0], b.inputs["Normal"])
    out(n, b.outputs[0])

    fibre = new_mat("fibre_v2")
    n = N(fibre)
    p = n.add("ShaderNodeTexCoord").outputs["Object"]
    cloud = n.noise(p, 34.0, 5.0, 0.6)
    fine = n.noise(p, 800.0, 2.0, 0.6)
    tone = n.mix(n.mul(0.7, n.smooth(0.42, 0.70, cloud)), (0.66, 0.66, 0.64, 1), (0.30, 0.295, 0.27, 1))
    tone = n.mix(n.mul(0.45, fine), tone, (0.80, 0.80, 0.78, 1))
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(tone, b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.8
    b.inputs["Sheen Weight"].default_value = 0.4
    b.inputs["Specular IOR Level"].default_value = 0.2
    out(n, b.outputs[0])
    return dict(white=white, panel=panel, bumper=bumper, rubber=rubber, metal=metal, track=track, fibre=fibre)


def revolve(prof, seg=32, cx=0.0, cy=0.0, facet=None):
    v, f = [], []
    for r, z in prof:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            rr = r
            if facet:
                # Hexagon nut, by clamping the radius to six flats.
                sector = (a + math.pi / facet) % (2 * math.pi / facet) - math.pi / facet
                rr = r * math.cos(math.pi / facet) / math.cos(sector) if r > 0 else 0.0
            v.append((cx + rr * math.cos(a), cy + rr * math.sin(a), z))
    for k in range(len(prof) - 1):
        for i in range(seg):
            a, b = k * seg + i, k * seg + (i + 1) % seg
            f.append((a, b, b + seg, a + seg))
    return v, f


def append(vv, ff, v, f):
    b = len(vv)
    vv += v
    ff += [tuple(i + b for i in t) for t in f]


def hair_pad(run, rng_seed, count, mat, parent):
    """Microfibre fringe as real hair curves: tufts, curl and fly-aways round the underside edge.
    The MJCF's pad bar at PAD_X sits heaviest; the rest rims the body as the design shows."""
    rng = np.random.default_rng(rng_seed)
    S = run.body_side
    half = S / 2
    corner = 0.05
    n_pts = 5
    # Sample points along the outline: rounded square perimeter, biased to the -x bar side.
    ring = np.array(resample(v1.rounded_ring(S - 0.012, corner, 0.0), 800))[:, :2]
    tang = np.roll(ring, -1, axis=0) - ring
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    normal = np.stack([tang[:, 1], -tang[:, 0]], axis=1)
    if (normal[0] * ring[0]).sum() < 0:
        normal = -normal
    weight = np.where(ring[:, 0] < -half + 0.03, 3.4, 1.0)
    weight = weight / weight.sum()
    # Tufts: fibres of one tuft share a lean, as in a chenille mop.
    tuft_count = count // 40
    tuft_i = rng.choice(len(ring), tuft_count, p=weight)
    tuft_lean = rng.normal(0, 0.55, (tuft_count, 3))
    tuft_len = rng.uniform(0.0045, 0.0105, tuft_count) * (1.0 + 0.45 * (ring[tuft_i, 0] < -half + 0.03))
    tuft_z = rng.uniform(0.002, 0.017, tuft_count)
    idx = rng.integers(0, tuft_count, count)
    ii = tuft_i[idx]
    base = ring[ii] + tang[ii] * rng.normal(0, 0.0035, (count, 1)) - normal[ii] * rng.uniform(0.0, 0.012, (count, 1))
    z = tuft_z[idx] + rng.normal(0, 0.0022, count)
    z = np.clip(z, 0.0008, 0.0195)
    d = np.stack([normal[ii, 0], normal[ii, 1], np.zeros(count)], axis=1)
    d += tang_3(tang[ii]) * tuft_lean[idx, 0:1] + np.array([0, 0, 1.0]) * tuft_lean[idx, 1:2] * 0.5
    d += rng.normal(0, 0.22, (count, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    L = tuft_len[idx] * rng.uniform(0.6, 1.25, count)
    pts = np.empty((count, n_pts, 3))
    pts[:, 0] = np.stack([base[:, 0], base[:, 1], z], axis=1)
    curl = rng.normal(0, 0.6, (count, 3))
    for k in range(1, n_pts):
        step = d + curl * (k / n_pts) + rng.normal(0, 0.18, (count, 3))
        step /= np.linalg.norm(step, axis=1, keepdims=True)
        pts[:, k] = pts[:, k - 1] + step * (L / (n_pts - 1))[:, None]
    # Nothing goes through the glass.
    pts[:, :, 2] = np.maximum(pts[:, :, 2], 0.0004)
    cu = bpy.data.hair_curves.new("pad_fibres")
    cu.add_curves([n_pts] * count)
    cu.position_data.foreach_set("vector", pts.reshape(-1).astype(np.float32))
    radius = cu.attributes.get("radius") or cu.attributes.new("radius", "FLOAT", "POINT")
    r0 = rng.uniform(0.00024, 0.00042, count)
    taper = np.linspace(1.0, 0.45, n_pts)
    radius.data.foreach_set("value", (r0[:, None] * taper).reshape(-1).astype(np.float32))
    cu.materials.append(mat)
    ob = bpy.data.objects.new("pad_fibres", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    return ob


def tang_3(t):
    return np.stack([t[:, 0], t[:, 1], np.zeros(len(t))], axis=1)


def build_robot_v2(run, layer):
    """Same size and same pose as the sim: 0.36 m side, chassis from 0.02 to 0.10 m off the glass, local z out of the glass."""
    M = shell_mats()
    S, R = run.body_side, 0.052
    zlo, ztop = run.ride_clear, run.ride_clear + run.body_height
    root = bpy.data.objects.new("robot", None)
    bpy.context.scene.collection.objects.link(root)
    root.rotation_mode = "QUATERNION"
    parts = []

    def ring(inset, z, min_r=0.006, count=None):
        r = v1.rounded_ring(S - 2 * inset, max(R - inset, min_r), z)
        return resample(r, count) if count else r

    def add(name, v, f, mat, smooth=True):
        ob = mesh_obj(name, v, f, mat, smooth=smooth)
        parts.append(ob)
        return ob

    # Flexible vacuum skirt. Its lip is pressed to the glass and it ripples where it is compressed.
    cnt = 360
    rings = []
    for inset, z, amp in ((0.0145, 0.0006, 0.0016), (0.012, 0.0022, 0.0013), (0.0105, 0.006, 0.0006), (0.0095, 0.014, 0.0002), (0.0095, zlo + 0.002, 0.0)):
        base = np.array(ring(inset, z, 0.02, cnt))
        ang = np.arange(cnt) / cnt * 2 * math.pi
        wob = amp * (np.sin(ang * 37) * 0.6 + np.sin(ang * 91 + 1.3) * 0.4)
        rad = base[:, :2] / np.linalg.norm(base[:, :2], axis=1, keepdims=True)
        base[:, :2] += rad * wob[:, None]
        rings.append([tuple(p) for p in base])
    v, f = loft(rings, close_top=True)
    add("robot_skirt", v, f, M["rubber"])
    # Belly behind it.
    v, f = loft([ring(0.008, zlo + 0.001, 0.02), ring(0.009, zlo + 0.001, 0.02)], close_top=True)
    add("robot_belly", v, f, M["rubber"])

    # Tracks on the sim's roller lines.
    for y in (0.15, -0.15):
        v, f = v1.stadium_track(y, 0.05, 0.105, 0.018, 0.018)
        add("robot_track", v, f, M["track"])

    # Pad carrier at the sim's PAD_X, under the fibres.
    pv, pf = [], []
    add_box(pv, pf, -0.175, -0.118, 0.0015, -0.09, 0.118, 0.018)
    add("robot_pad_bar", pv, pf, M["rubber"], smooth=False)

    # Dark lower bumper. A soft V groove parts it from the white shell above.
    sect = [(0.008, zlo), (0.003, zlo + 0.0006), (0.0005, zlo + 0.002), (-0.0009, zlo + 0.004), (-0.0009, zlo + 0.0085),
            (-0.0002, zlo + 0.0105), (0.0012, zlo + 0.0118), (0.0030, zlo + 0.0122)]
    v, f = loft([ring(i, z, 0.03) for i, z in sect], close_top=False)
    add("robot_bumper", v, f, M["bumper"])
    v, f = loft([ring(0.0028, zlo + 0.012, 0.03), ring(0.0040, zlo + 0.0128, 0.03), ring(0.0028, zlo + 0.0138, 0.03)], close_top=False)
    add("robot_groove", v, f, M["rubber"])

    # White shell: draft on the wall, moulded fillet, broad rim, a crisp lip down to the panel.
    rim = 0.031
    sect = [(0.0030, zlo + 0.0136), (0.0010, zlo + 0.0143), (0.0002, zlo + 0.0158), (0.0, zlo + 0.018), (0.0006, ztop - 0.024), (0.0011, ztop - 0.021)]
    sect += [(0.0011 + a, b) for a, b in v1.fillet(ztop - 0.021, ztop, 0.0, 0.021, seg=10)[1:]]
    sect += [(rim - 0.0028, ztop - 0.0002), (rim - 0.0012, ztop - 0.0005), (rim - 0.0004, ztop - 0.0014), (rim, ztop - 0.003), (rim + 0.0002, ztop - 0.0075)]
    v, f = loft([ring(i, z, 0.030) for i, z in sect], close_top=False)
    add("robot_shell", v, f, M["white"])

    # Panel, inset, with a shadow-gap gasket.
    pz = ztop - 0.0065
    pin = rim + 0.0014
    v, f = loft([ring(rim + 0.0001, pz - 0.002, 0.028), ring(rim + 0.0007, pz + 0.0006, 0.028), ring(pin + 0.0005, pz - 0.0002, 0.028)], close_top=False)
    add("robot_panel_gasket", v, f, M["rubber"])
    rings = [ring(pin, pz - 0.0035, 0.028), ring(pin + 0.0006, pz - 0.0007, 0.028), ring(pin + 0.0018, pz, 0.028), ring(pin + 0.0035, pz + 0.00005, 0.028), ring(0.08, pz + 0.0006, 0.028)]
    v, f = loft(rings, close_top=True)
    add("robot_panel", v, f, M["panel"])

    # Vent slots: seven stadium openings with a small bezel on the hatch.
    bv, bf = [], []
    dv, df = [], []
    for k in range(7):
        cy = -0.033 + k * 0.011
        xa, xb = -0.112, -0.086
        # Bezel ring, then a dark floor below it.
        outline = []
        for cx, a0 in ((xb, -90), (xa, 90)):
            for i in range(9):
                a = math.radians(a0 + 180 * i / 8)
                outline.append((cx + math.cos(a), cy + math.sin(a), cx, cy))
        rr = [[(cx + (px - cx) * r, cy + (py - cy) * r, z) for px, py, cx, cy in outline] for r, z in
              ((0.0036, pz + 0.0007), (0.0030, pz + 0.0012), (0.0022, pz + 0.0012), (0.0020, pz - 0.0012))]
        tv, tf = loft(rr, close_top=False)
        append(bv, bf, tv, tf)
        fl = [(cx + (px - cx) * 0.0022, cy + (py - cy) * 0.0034, pz - 0.0011) for px, py, cx, cy in outline]
        b0 = len(dv)
        dv += fl
        df.append(tuple(range(b0, b0 + len(fl))))
    add("robot_vent_bezel", bv, bf, M["panel"])
    add("robot_vent_floor", dv, df, M["rubber"], smooth=False)

    # Screws: a countersink washer, a low head and a real hex socket with a dark floor.
    scv, scf, flv, flf = [], [], [], []
    pts = [(0.122, 0.122), (-0.122, 0.122), (0.122, -0.122), (-0.122, -0.122)]
    for cx, cy in pts:
        head = [(0.0062, pz + 0.0006), (0.0060, pz + 0.0012), (0.0056, pz + 0.0020), (0.0050, pz + 0.0024)]
        v, f = revolve(head, 24, cx, cy)
        append(scv, scf, v, f)
        # The flat of the head, up to the socket rim.
        seg = 24
        rim_h = 0.0027
        ang0 = 0.5 * (cx + cy)
        hx = [(rim_h * math.cos(ang0 + i * math.pi / 3), rim_h * math.sin(ang0 + i * math.pi / 3)) for i in range(6)]
        hexr = [(cx + hx[int(i / seg * 6)][0] + (hx[(int(i / seg * 6) + 1) % 6][0] - hx[int(i / seg * 6)][0]) * ((i / seg * 6) % 1),
                 cy + hx[int(i / seg * 6)][1] + (hx[(int(i / seg * 6) + 1) % 6][1] - hx[int(i / seg * 6)][1]) * ((i / seg * 6) % 1)) for i in range(seg)]
        circ = [(cx + 0.0050 * math.cos(2 * math.pi * i / seg), cy + 0.0050 * math.sin(2 * math.pi * i / seg), pz + 0.0024) for i in range(seg)]
        top = [(x, y, pz + 0.0024) for x, y in hexr]
        low = [(x, y, pz + 0.0004) for x, y in hexr]
        v, f = loft([circ, top, low], close_top=False)
        append(scv, scf, v, f)
        b0 = len(flv)
        flv += low
        flf.append(tuple(range(b0, b0 + seg)))
    add("robot_screws", scv, scf, M["metal"], smooth=False)
    add("robot_socket", flv, flf, M["rubber"], smooth=False)

    # Rubber port plug in the wall, on the +x side. A small moulded bulge with a seam.
    wall_z0, wall_z1 = zlo + 0.036, zlo + 0.050
    pl_v, pl_f = [], []
    add_box(pl_v, pl_f, S / 2 - 0.0010, -0.016, wall_z0, S / 2 + 0.0001, 0.016, wall_z0 + 0.008)
    add("robot_plug", pl_v, pl_f, M["bumper"], smooth=False)

    # Tether gland at the sim's tether point: lock nut, sealing cap, ribbed strain relief, swaged ferrule.
    v, f = revolve([(0.0185, pz + 0.0003), (0.0178, pz + 0.0012), (0.0160, pz + 0.0034), (0.0135, pz + 0.0048), (0.0095, pz + 0.0052)], 56)
    add("robot_nut", v, f, M["white"])
    prof = [(0.0100, pz + 0.0050), (0.0100, pz + 0.0065)]
    z_ = pz + 0.0065
    for k in range(5):
        rr = 0.0098 - k * 0.0007
        prof += [(rr, z_ + 0.0004), (rr, z_ + 0.0020), (rr - 0.0012, z_ + 0.0026), (rr - 0.0012, z_ + 0.0036)]
        z_ += 0.0036
    prof += [(0.0058, z_ + 0.001)]
    v, f = revolve(prof, 40)
    add("robot_relief", v, f, M["panel"])
    boot_z = pz + 0.0345
    v, f = revolve([(0.0058, z_ + 0.0005), (0.0062, z_ + 0.0012), (0.0062, boot_z - 0.0014), (0.0048, boot_z), (0.0032, boot_z)], 32)
    add("robot_ferrule", v, f, M["metal"])

    for ob in parts:
        ob.parent = root
        # As in v1: the white body's 10 cm mirror image reads as a second plate. What sits low stays in the glass.
        if ob.name.startswith(("robot_shell", "robot_panel", "robot_nut", "robot_relief", "robot_ferrule", "robot_vent", "robot_screws", "robot_socket", "robot_plug", "robot_bumper", "robot_groove", "robot_belly", "robot_pad_bar")):
            ob.visible_glossy = False
    if layer != "norobotfibres":
        hair_pad(run, 41, shot_list.FIBRES, M["fibre"], root)

    # Tether: a unit cylinder, scaled each frame.
    cable = new_mat("cable_v2")
    n = N(cable)
    coord = n.add("ShaderNodeTexCoord")
    ox, oy, _ = n.split(coord.outputs["Object"])
    geo = n.add("ShaderNodeNewGeometry")
    dist = n.add("ShaderNodeVectorMath", operation="DISTANCE")
    n.link(geo.outputs["Position"], dist.inputs[0])
    dist.inputs[1].default_value = run.anchor
    ang = n.math("ARCTAN2", oy, ox)
    k = 2 * math.pi / 0.0115
    s1 = n.math("SINE", n.add_(n.mul(ang, 8.0), n.mul(dist.outputs["Value"], k)))
    s2 = n.math("SINE", n.sub(n.mul(ang, 8.0), n.mul(dist.outputs["Value"], k)))
    braid = n.math("MAXIMUM", s1, s2)
    strand = n.math("SINE", n.mul(ang, 56.0))
    bump = n.add("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.0009
    n.link(n.add_(braid, n.mul(0.15, strand)), bump.inputs["Height"])
    nz = n.noise(n.xyz(n.mul(dist.outputs["Value"], 7.0), 0.0, 0.0), 1.0, 5.0, 0.6)
    tracer = n.math("GREATER_THAN", s1, s2)
    tone = n.mix(tracer, (0.26, 0.27, 0.27, 1), (0.40, 0.41, 0.41, 1))
    tone = n.mix(n.mul(0.5, n.smooth(0.45, 0.7, nz)), tone, (0.14, 0.135, 0.125, 1))
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(tone, b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.72
    b.inputs["Sheen Weight"].default_value = 0.3
    n.link(bump.outputs[0], b.inputs["Normal"])
    out(n, b.outputs[0])
    tv, tf = [], []
    seg = 24
    for z in (0.0, 1.0):
        for i in range(seg):
            a = 2 * math.pi * i / seg
            tv.append((math.cos(a), math.sin(a), z))
    for i in range(seg):
        j = (i + 1) % seg
        tf.append((i, j, j + seg, i + seg))
    teth = mesh_obj("tether", tv, tf, cable, smooth=True)
    teth.rotation_mode = "QUATERNION"
    teth.visible_glossy = False  # Its mirror image reads as a second tether.
    return root, teth, boot_z


# ---------------------------------------------------------------- set-up

def build_sun(s):
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = s["energy"]
    sun.angle = math.radians(s["angle"])
    sun.color = s["color"]
    ob = bpy.data.objects.new("sun", sun)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector(s["to_sun"]).normalized().to_track_quat("Z", "Y")


def setup_render_v2(args):
    v1.setup_render(args)
    sc = bpy.context.scene
    sc.cycles.adaptive_threshold = 0.01
    sc.cycles.max_bounces = 8
    sc.cycles.transparent_max_bounces = 8
    sc.cycles.glossy_bounces = 4
    sc.cycles.diffuse_bounces = 3
    sc.cycles.sample_clamp_direct = 0.0
    sc.cycles.sample_clamp_indirect = 10.0
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.blur_glossy = 0.4
    sc.render.image_settings.exr_codec = "DWAA"
    # Thin fibres gain nothing from full tubes.
    sc.cycles_curves.shape = "RIBBONS"
    sc.cycles_curves.subdivisions = 2


def smooth_follow(run, t, sigma, lag):
    """Where the operator aims: a Gaussian of the robot's recorded position around t - lag. Read only."""
    if sigma <= 0:
        return np.array(run.pose(t - lag)[0])
    taus = np.linspace(-2.5 * sigma, 2.5 * sigma, 41)
    w = np.exp(-0.5 * (taus / sigma) ** 2)
    pos = np.array([run.pose(max(t - lag + a, 0.0))[0] for a in taus])
    return (pos * w[:, None]).sum(axis=0) / w.sum()


def camera_v2(shot, u, run, t, t_start):
    e = u * u * (3 - 2 * u)
    lerp = lambda pair: np.array(pair[0], float) * (1 - e) + np.array(pair[1], float) * e
    base = smooth_follow(run, t, shot.get("sigma", 0.0), shot.get("lag", 0.0)) if shot.get("follow", True) else np.array(run.pose(t_start)[0])
    return {"pos": tuple(base + lerp(shot["pos"])), "target": tuple(base + lerp(shot["target"])),
            "lens": shot["lens"][0] * (1 - e) + shot["lens"][1] * e, "fstop": shot["fstop"],
            "focus": tuple(np.array(run.pose(t)[0]) + np.array(shot.get("focus_offset", (0, 0, 0)))), "roll": shot.get("roll", 0.0)}


def edge_direction(level):
    """Green channel of the dirt texture: 1 where the nearby recorded edge runs up the wall, 0 where it runs across."""
    gz, gx = np.gradient(level)
    ax, az = np.abs(gx), np.abs(gz)

    def box(a, r):
        for axis in (0, 1):
            c = np.cumsum(np.insert(a, 0, 0, axis=axis), axis=axis)
            hi = np.clip(np.arange(a.shape[axis]) + r + 1, 0, a.shape[axis])
            lo = np.clip(np.arange(a.shape[axis]) - r, 0, a.shape[axis])
            a = np.take(c, hi, axis=axis) - np.take(c, lo, axis=axis)
        return a

    ax, az = box(box(ax, 14), 14), box(box(az, 14), 14)
    return (ax + 1e-4) / (ax + az + 2e-4)


# ---------------------------------------------------------------- main

def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = run_data.Run(args.trial)
    shot = dict(shot_list.SHOTS[args.shot])
    if args.override:
        shot.update(json.loads(args.override))
    default_t = shot["t"] if args.mode == "clip" else shot.get("still_t", shot["t"])
    t0 = args.t if args.t is not None else default_t

    # The wall ends nearer the robot, so there is air past the corner. Scenery: the sim's wall is just a plane.
    run.tower_x0 = shot_list.TOWER_X0_V2

    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    setup_render_v2(args)

    haze = shot_list.HAZE_V2
    focus = (0.0, 0.0, run.area["z1"])
    shot_list.SKY_GAIN = shot_list.SKY_GAIN_V2
    shot_list.SKY_ROTATE_DEG = shot.get("sky_rot", shot_list.SKY_ROTATE_V2)
    v1.build_world(args.sky, haze)
    build_sun(shot_list.SUN_V2)

    img = bpy.data.images.new("dirt", run.tex_px_w, run.tex_px_h, float_buffer=True, alpha=False)
    img.colorspace_settings.name = "Non-Color"

    glass = glass_v2(run, img, haze, focus)
    alu = alu_v2(haze, focus)
    seal = dark_material("seal", (0.012, 0.012, 0.013), 0.42, haze, focus)
    side = dark_material("side_glass", (0.018, 0.022, 0.025), 0.08, haze, focus)
    conc = dark_material("concrete", (0.28, 0.27, 0.25), 0.8, haze, focus)
    v1.build_glass(run, glass)
    build_frame_v2(run, alu, seal)
    v1.build_tower_body(run, alu, side, conc)
    build_interior(run, haze, focus)
    t_c = time.time()
    city_gen.TREES = False
    city_gen.build(run, haze, focus, N, out, new_mat)
    print("city built in %.1f s" % (time.time() - t_c))

    robot, tether, boot_z = build_robot_v2(run, args.layer)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    n_frames = 1 if args.mode == "still" else int(round((args.seconds if args.seconds is not None else shot.get("seconds", 9.0)) * args.fps))
    end = args.end_frame if args.end_frame is not None else n_frames

    def apply_pose(t):
        pos, quat = run.pose(t)
        robot.location = pos
        robot.rotation_quaternion = quat
        q = Quaternion(quat)
        tp = Vector(pos) + q @ Vector((0, 0, boot_z))
        d = Vector(run.anchor) - tp
        tether.location = tp
        tether.rotation_quaternion = d.to_track_quat("Z", "Y")
        tether.scale = (run.tether_radius, run.tether_radius, d.length)

    def cam_for(fi):
        t = t0 + fi / args.fps if args.mode == "clip" else t0
        u = fi / max(n_frames - 1, 1) if args.mode == "clip" else 0.0
        return camera_v2(shot, u, run, t, t0)

    if args.mode == "clip":
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        for fi in range(max(args.start_frame - 1, 0), end + 1):
            apply_pose(t0 + fi / args.fps)
            for ob, paths in ((robot, ("location", "rotation_quaternion")),
                              (tether, ("location", "rotation_quaternion", "scale"))):
                for path in paths:
                    ob.keyframe_insert(data_path=path, frame=fi + 1)
            # The camera's move is keyed too, so the shutter sees it.
            cp = cam_for(fi)
            place_camera(cam, cp["pos"], cp["target"], cp["lens"], cp["focus"], cp["fstop"], cp["roll"])
            cam.keyframe_insert(data_path="location", frame=fi + 1)
            cam.keyframe_insert(data_path="rotation_quaternion", frame=fi + 1)

    log, timing = [], []
    from bpy_extras.object_utils import world_to_camera_view
    for fi in range(args.start_frame, end):
        t = t0 + fi / args.fps if args.mode == "clip" else t0
        cp = cam_for(fi)
        place_camera(cam, cp["pos"], cp["target"], cp["lens"], cp["focus"], cp["fstop"], cp["roll"])
        if args.mode == "clip":
            sc.frame_set(fi + 1)
        else:
            apply_pose(t)
        grid = run.dirt_image(t)
        ed = edge_direction(grid)
        rgba = np.stack([grid, ed, np.zeros_like(grid), np.ones_like(grid)], axis=2).astype(np.float32)
        img.pixels.foreach_set(rgba.ravel())
        img.update()
        img.update_tag()
        glass.node_tree.update_tag()

        path = out_dir / ("frame_%04d.exr" % fi if args.mode == "clip" else "still.exr")
        sc.render.filepath = str(path)
        t_s = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t_s
        timing.append(dt)
        bpy.context.view_layer.update()
        px = world_to_camera_view(sc, cam, robot.matrix_world.translation)
        log.append({"frame": fi, "t": t, "robot_loc": list(robot.matrix_world.translation),
                    "robot_quat": list(robot.matrix_world.to_quaternion()), "screen": [px.x, px.y, px.z],
                    "cam": list(cam.location), "seconds": dt, "lens": cam.data.lens, "dirt_cov": run.coverage(t)})
        print("frame %d t=%.3f %.1f s" % (fi, t, dt), flush=True)
        (out_dir / ("poses_%04d_%04d.json" % (args.start_frame, end))).write_text(json.dumps(log, indent=0))
    print("mean seconds per frame %.1f" % (sum(timing) / max(len(timing), 1)))


if __name__ == "__main__":
    main()
