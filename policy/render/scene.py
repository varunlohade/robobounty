"""Blender scene for one recorded high-rise run. Run through render.py, not directly.

World units are metres and the axes match MuJoCo: x along the wall, y out of the wall is negative,
z up. The robot pose and the dirt grid come straight from the recorded trial. All scenery and
lighting are artistic and feed nothing back to the physics.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import data as run_data  # noqa: E402
import city as city_gen  # noqa: E402
import shots as shot_list  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="still", choices=["still", "clip"])
    ap.add_argument("--shot", default="side")
    ap.add_argument("--t", type=float, default=None, help="run time in seconds; default from the shot")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--sky", required=True)
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--no-volume", action="store_true")
    return ap.parse_args(argv)


# ---------------------------------------------------------------- node helpers

class N:
    """Small wrapper so shader graphs read as maths."""

    def __init__(self, mat_or_world):
        self.tree = mat_or_world.node_tree
        self.tree.nodes.clear()

    def add(self, kind, **props):
        n = self.tree.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.tree.links.new(a, b)

    def set(self, sock, v):
        if hasattr(v, "bl_idname") or hasattr(v, "is_linked"):
            self.link(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        m = self.add("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(m.inputs[0], a)
        if b is not None:
            self.set(m.inputs[1], b)
        if c is not None:
            self.set(m.inputs[2], c)
        return m.outputs[0]

    def add_(self, a, b):
        return self.math("ADD", a, b)

    def sub(self, a, b):
        return self.math("SUBTRACT", a, b)

    def mul(self, a, b):
        return self.math("MULTIPLY", a, b)

    def clamp01(self, a):
        return self.math("MULTIPLY", a, 1.0, clamp=True)

    def smooth(self, lo, hi, v):
        m = self.add("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
        self.set(m.inputs["Value"], v)
        self.set(m.inputs["From Min"], lo)
        self.set(m.inputs["From Max"], hi)
        self.set(m.inputs["To Min"], 0.0)
        self.set(m.inputs["To Max"], 1.0)
        return m.outputs[0]

    def mix(self, fac, a, b):
        m = self.add("ShaderNodeMix", data_type="RGBA", clamp_factor=True)
        self.set(m.inputs[0], fac)
        self.set(m.inputs[6], a)
        self.set(m.inputs[7], b)
        return m.outputs[2]

    def mix_f(self, fac, a, b):
        m = self.add("ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
        self.set(m.inputs[0], fac)
        self.set(m.inputs[2], a)
        self.set(m.inputs[3], b)
        return m.outputs[0]

    def mixs(self, fac, a, b):
        m = self.add("ShaderNodeMixShader")
        self.set(m.inputs[0], fac)
        self.link(a, m.inputs[1])
        self.link(b, m.inputs[2])
        return m.outputs[0]

    def noise(self, vec, scale, detail=4.0, rough=0.5, lac=2.0):
        m = self.add("ShaderNodeTexNoise")
        self.link(vec, m.inputs["Vector"])
        m.inputs["Scale"].default_value = scale
        m.inputs["Detail"].default_value = detail
        m.inputs["Roughness"].default_value = rough
        m.inputs["Lacunarity"].default_value = lac
        return m.outputs[0]

    def xyz(self, x, y, z):
        m = self.add("ShaderNodeCombineXYZ")
        self.set(m.inputs[0], x)
        self.set(m.inputs[1], y)
        self.set(m.inputs[2], z)
        return m.outputs[0]

    def split(self, v):
        m = self.add("ShaderNodeSeparateXYZ")
        self.link(v, m.inputs[0])
        return m.outputs

    def fog(self, surface, haze, focus, kdist=1 / 2300.0):
        """Aerial perspective that also holds in reflections: distance is measured from a fixed
        point near the robot, not along the ray, so a reflected city hazes the same as a direct one."""
        geo = self.add("ShaderNodeNewGeometry")
        d = self.add("ShaderNodeVectorMath", operation="DISTANCE")
        self.link(geo.outputs["Position"], d.inputs[0])
        d.inputs[1].default_value = focus
        z = self.split(geo.outputs["Position"])[2]
        # Air is thicker near the ground.
        dens = self.add_(1.0, self.mul(2.2, self.math("EXPONENT", self.mul(z, -1 / 55.0))))
        f = self.sub(1.0, self.math("EXPONENT", self.mul(self.mul(d.outputs["Value"], kdist), self.mul(dens, -1.0))))
        em = self.add("ShaderNodeEmission")
        em.inputs["Color"].default_value = (*haze, 1)
        return self.mixs(f, surface, em.outputs[0])


def out(n, shader):
    o = n.add("ShaderNodeOutputMaterial")
    n.link(shader, o.inputs["Surface"])


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m


def mesh_obj(name, verts, faces, mat, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    if smooth:
        me.shade_smooth()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# ---------------------------------------------------------------- world

def build_world(sky_path, haze):
    w = bpy.data.worlds.new("sky")
    w.use_nodes = True
    n = N(w)
    coord = n.add("ShaderNodeTexCoord")
    mapping = n.add("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(shot_list.SKY_ROTATE_DEG))
    n.link(coord.outputs["Generated"], mapping.inputs["Vector"])
    env = n.add("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(sky_path))
    n.link(mapping.outputs[0], env.inputs["Vector"])
    # Below the horizon the sky map is empty. Blend into the haze colour so the far city melts away.
    # Above it, the same haze lifts the bottom of the sky.
    z = n.split(coord.outputs["Generated"])[2]
    lift = n.smooth(-0.015, 0.07, z)
    col = n.mix(lift, (*haze, 1), env.outputs[0])
    bg = n.add("ShaderNodeBackground")
    n.link(col, bg.inputs["Color"])
    bg.inputs["Strength"].default_value = shot_list.SKY_GAIN
    o = n.add("ShaderNodeOutputWorld")
    n.link(bg.outputs[0], o.inputs["Surface"])
    bpy.context.scene.world = w


# ---------------------------------------------------------------- the facade

def glass_material(run, dirt_image, haze, focus):
    """Coated curtain wall glass under a film of grime. The film thickness comes from dirt_image,
    the recorded grid. Procedural detail only breaks up the film inside what the grid allows."""
    mat = new_mat("glass")
    n = N(mat)
    geo = n.add("ShaderNodeNewGeometry")
    px, py, pz = n.split(geo.outputs["Position"])

    # Pane grid distances from the sim's own mullion and transom lines.
    s, off, ts = run.mullion_spacing, run.mullion_offset, run.transom_spacing
    fx = n.math("FRACT", n.mul(n.sub(px, off), 1 / s))
    fz = n.math("FRACT", n.mul(pz, 1 / ts))
    dx = n.mul(n.math("ABSOLUTE", n.sub(n.math("FRACT", n.add_(n.mul(n.sub(px, off), 1 / s), 0.5)), 0.5)), s)
    dz = n.mul(n.math("ABSOLUTE", n.sub(n.math("FRACT", n.add_(n.mul(pz, 1 / ts), 0.5)), 0.5)), ts)
    pane_x = n.math("FLOOR", n.mul(n.sub(px, off), 1 / s))
    pane_z = n.math("FLOOR", n.mul(pz, 1 / ts))
    pane = n.add("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    n.link(n.xyz(pane_x, pane_z, 3.0), pane.inputs["Vector"])
    pane_rand = pane.outputs[0]

    # Recorded dirt. u, v run across the padded grid image.
    u = n.mul(n.sub(px, run.tex_x0), 1 / run.tex_w)
    v = n.mul(n.sub(pz, run.tex_z0), 1 / run.tex_h)
    tex = n.add("ShaderNodeTexImage", interpolation="Cubic", extension="EXTEND")
    tex.image = dirt_image
    n.link(n.xyz(u, v, 0.0), tex.inputs["Vector"])
    in_area = n.mul(n.math("GREATER_THAN", u, 0.0), n.mul(n.math("LESS_THAN", u, 1.0),
                    n.mul(n.math("GREATER_THAN", v, 0.0), n.math("LESS_THAN", v, 1.0))))
    # Outside the padded grid there is no record: the wall carries the same film at level 1.
    level = n.mix_f(in_area, 1.0, tex.outputs["Color"])
    # A wiped edge is sharp. Tighten the grid's 5 cm cell gradient, without moving it.
    film_mask = n.smooth(0.10, 0.34, level)
    film_level = n.mul(film_mask, n.math("POWER", n.math("MAXIMUM", level, 0.0), 0.7))

    p_xz = n.xyz(px, pz, n.mul(pane_rand, 17.0))
    # Grime detail, all in metres on the wall.
    blot = n.noise(p_xz, 1.6, 7.0, 0.62)
    fine = n.noise(p_xz, 34.0, 6.0, 0.7)
    streak_v = n.xyz(n.mul(px, 46.0), n.mul(pz, 2.0), n.mul(pane_rand, 11.0))
    streak = n.noise(streak_v, 1.0, 5.0, 0.62)
    streak2 = n.noise(n.xyz(n.mul(px, 150.0), n.mul(pz, 5.0), n.mul(pane_rand, 7.0)), 1.0, 3.0, 0.6)
    # Run-off stains under each transom. Height below the transom above.
    below = n.sub(1.0, fz)
    stain = n.mul(n.math("EXPONENT", n.mul(n.mul(below, ts), -1.6)), n.smooth(0.42, 0.62, streak))
    vor = n.add("ShaderNodeTexVoronoi", feature="F1")
    n.link(p_xz, vor.inputs["Vector"])
    vor.inputs["Scale"].default_value = 90.0
    vor.inputs["Randomness"].default_value = 1.0
    specks = n.sub(1.0, n.smooth(0.04, 0.17, vor.outputs["Distance"]))
    vor2 = n.add("ShaderNodeTexVoronoi", feature="F1")
    n.link(p_xz, vor2.inputs["Vector"])
    vor2.inputs["Scale"].default_value = 28.0
    specks2 = n.mul(n.sub(1.0, n.smooth(0.02, 0.09, vor2.outputs["Distance"])), n.smooth(0.5, 0.7, fine))

    # Dust is spots on a mirror, not a brushed sheet: an even thin veil, cloudy patches, fine mottle,
    # rare drips. The sharp reflection survives between the spots.
    mottle = n.noise(p_xz, 140.0, 4.0, 0.7)
    grime = n.add_(0.27, n.mul(0.26, n.smooth(0.36, 0.68, blot)))
    grime = n.add_(grime, n.mul(0.17, n.smooth(0.42, 0.62, fine)))
    grime = n.add_(grime, n.mul(0.08, n.smooth(0.46, 0.60, mottle)))
    grime = n.add_(grime, n.mul(0.05, n.smooth(0.62, 0.74, streak)))
    grime = n.add_(grime, n.mul(0.20, stain))
    grime = n.add_(grime, n.mul(0.20, specks))
    grime = n.add_(grime, n.mul(0.40, specks2))
    dirt_scale = run.film_gain * shot_list.FILM_OPACITY
    film = n.clamp01(n.mul(n.mul(film_level, grime), dirt_scale))

    # Glass normal: float-glass roller wave and tiny film relief.
    wave = n.noise(n.xyz(px, n.mul(pz, 0.35), n.mul(pane_rand, 9.0)), 2.2, 2.0, 0.4)
    bump = n.add("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = 0.004
    n.link(wave, bump.inputs["Height"])
    n.link(geo.outputs["Normal"], bump.inputs["Normal"])

    # Vision glass versus spandrel, by height within the floor. Spandrels sit behind the slab line.
    span = n.sub(1.0, n.smooth(0.16, 0.19, n.math("MINIMUM", fz, n.sub(1.0, fz))))
    pane_tone = n.add_(0.75, n.mul(pane_rand, 0.5))
    inner = n.mix(span, (0.012, 0.024, 0.024, 1), (0.004, 0.008, 0.008, 1))
    inner_diff = n.add("ShaderNodeBsdfDiffuse")
    m_tone = n.add("ShaderNodeVectorMath", operation="SCALE")
    n.link(inner, m_tone.inputs[0])
    n.link(pane_tone, m_tone.inputs["Scale"])
    n.link(m_tone.outputs[0], inner_diff.inputs["Color"])

    fres = n.add("ShaderNodeFresnel")
    fres.inputs["IOR"].default_value = 1.52
    n.link(bump.outputs[0], fres.inputs["Normal"])
    coat = shot_list.GLASS_COAT
    fac = n.add_(coat, n.mul(1.0 - coat, fres.outputs[0]))
    gloss = n.add("ShaderNodeBsdfAnisotropic", distribution="GGX")
    gloss.inputs["Color"].default_value = (0.86, 0.96, 0.94, 1)
    n.link(bump.outputs[0], gloss.inputs["Normal"])
    n.set(gloss.inputs["Roughness"], n.add_(0.008, n.mul(0.14, film)))
    glass = n.mixs(fac, inner_diff.outputs[0], gloss.outputs[0])

    # Frit: an opaque band around every pane, flush with the glass, so the frame reads heavier
    # without changing the 5 mm joint the robot actually crosses.
    frit = n.sub(1.0, n.smooth(run.frit_m, run.frit_m + 0.002, n.math("MINIMUM", dx, dz)))
    frit_bsdf = n.add("ShaderNodeBsdfPrincipled")
    frit_bsdf.inputs["Base Color"].default_value = (0.014, 0.015, 0.016, 1)
    frit_bsdf.inputs["Roughness"].default_value = 0.22
    glass = n.mixs(frit, glass, frit_bsdf.outputs[0])

    # The film itself: a thin warm-grey mineral layer.
    tint = n.mix(n.smooth(0.3, 0.7, blot), (0.24, 0.235, 0.22, 1), (0.17, 0.17, 0.165, 1))
    film_b = n.add("ShaderNodeBsdfPrincipled")
    n.link(tint, film_b.inputs["Base Color"])
    film_b.inputs["Roughness"].default_value = 0.72
    film_b.inputs["Specular IOR Level"].default_value = 0.3
    surf = n.mixs(film, glass, film_b.outputs[0])
    out(n, n.fog(surf, haze, focus))
    return mat


def pane_grid(run):
    xs = [run.mullion_offset + k * run.mullion_spacing for k in range(-40, 40)]
    xs = [x for x in xs if run.tower_x0 < x < run.tower_x1]
    xs = [run.tower_x0] + xs + [run.tower_x1]
    zs = [k * run.transom_spacing for k in range(0, 60)]
    zs = [z for z in zs if z < run.roof_z]
    zs = zs + [run.roof_z]
    return xs, zs


def build_glass(run, mat):
    """Panes with a hair of bow and tilt, so reflections kink at every joint as they do on a real tower.
    The surface stays within 1.5 mm behind the sim's y=0 plane."""
    xs, zs = pane_grid(run)
    rng = np.random.default_rng(7)
    verts, faces = [], []
    near_x = (run.area["x0"] - 9, run.area["x1"] + 9)
    near_z = (run.area["z0"] - 12, run.roof_z + 1)
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            x0, x1, z0, z1 = xs[i], xs[i + 1], zs[j], zs[j + 1]
            near = x1 > near_x[0] and x0 < near_x[1] and z1 > near_z[0] and z0 < near_z[1]
            nx, nz = (14, 26) if near else (1, 1)
            tilt_x, tilt_z = rng.normal(0, 0.00028, 2)
            bow = rng.uniform(0.0005, 0.0014)
            base = len(verts)
            for b in range(nz + 1):
                for a in range(nx + 1):
                    u, w = a / nx, b / nz
                    x, z = x0 + (x1 - x0) * u, z0 + (z1 - z0) * w
                    y = 0.0
                    if near:
                        y = bow * math.sin(u * math.pi) * math.sin(w * math.pi)
                    y += 0.0015 + tilt_x * (x - (x0 + x1) / 2) + tilt_z * (z - (z0 + z1) / 2)
                    verts.append((x, y, z))
            for b in range(nz):
                for a in range(nx):
                    p = base + b * (nx + 1) + a
                    faces.append((p, p + 1, p + nx + 2, p + nx + 1))
    return mesh_obj("glass", verts, faces, mat, smooth=True)


def alu_material(haze, focus):
    mat = new_mat("alu")
    n = N(mat)
    geo = n.add("ShaderNodeNewGeometry")
    px, py, pz = n.split(geo.outputs["Position"])
    grain = n.noise(n.xyz(n.mul(px, 400.0), n.mul(py, 400.0), n.mul(pz, 400.0)), 1.0, 2.0, 0.5)
    rain = n.noise(n.xyz(n.mul(px, 7.0), n.mul(pz, 3.0), 0.0), 1.0, 5.0, 0.6)
    b = n.add("ShaderNodeBsdfPrincipled")
    tone = n.mix(n.smooth(0.35, 0.7, rain), (0.50, 0.51, 0.52, 1), (0.38, 0.39, 0.40, 1))
    n.link(tone, b.inputs["Base Color"])
    b.inputs["Metallic"].default_value = 1.0
    n.set(b.inputs["Roughness"], n.add_(0.30, n.mul(0.18, grain)))
    out(n, n.fog(b.outputs[0], haze, focus))
    return mat


def dark_material(name, col, rough, haze, focus):
    mat = new_mat(name)
    n = N(mat)
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    out(n, n.fog(b.outputs[0], haze, focus))
    return mat


def extrude_joint(verts, faces, profile, a0, a1, axis):
    """Sweep an (offset, y) profile along an axis ('z' for mullions, 'x' for transoms)."""
    base = len(verts)
    for o, y in profile:
        if axis == "z":
            verts.append((o, y, a0))
            verts.append((o, y, a1))
        else:
            verts.append((a0, y, o))
            verts.append((a1, y, o))
    for i in range(len(profile) - 1):
        p = base + 2 * i
        if axis == "z":
            faces.append((p, p + 1, p + 3, p + 2))
        else:
            faces.append((p, p + 2, p + 3, p + 1))


def joint_profile(center, depth, cap_r, seg=10):
    """The sim's rounded cap: a cylinder of radius cap_r buried so its crown stands proud by depth."""
    half = math.sqrt(max(2 * cap_r * depth - depth * depth, 1e-8))
    a = math.asin(half / cap_r)
    pts = []
    for i in range(seg + 1):
        t = -a + 2 * a * i / seg
        pts.append((center + cap_r * math.sin(t), (cap_r - depth) - cap_r * math.cos(t)))
    return pts, half


def build_frame(run, alu, seal):
    xs, zs = pane_grid(run)
    v, f, sv, sf = [], [], [], []
    d, r, gap = run.mullion_depth, run.cap_r, run.joint_gap
    for x in xs[1:-1]:
        pts, half = joint_profile(x, d, r)
        extrude_joint(v, f, pts, 0.0, run.roof_z, "z")
        seal_pts = [(x - half - gap, 0.0), (x - half - gap, 0.006), (x + half + gap, 0.006), (x + half + gap, 0.0)]
        extrude_joint(sv, sf, seal_pts, 0.0, run.roof_z, "z")
    for z in zs[1:-1]:
        pts, half = joint_profile(z, d, r)
        extrude_joint(v, f, pts, run.tower_x0, run.tower_x1, "x")
        seal_pts = [(z - half - gap, 0.0), (z - half - gap, 0.006), (z + half + gap, 0.006), (z + half + gap, 0.0)]
        extrude_joint(sv, sf, seal_pts, run.tower_x0, run.tower_x1, "x")
    mesh_obj("frame", v, f, alu, smooth=True)
    mesh_obj("seal", sv, sf, seal, smooth=False)


def build_tower_body(run, alu, side_glass, conc):
    x0, x1, r = run.tower_x0, run.tower_x1, run.roof_z
    y1 = run.tower_depth
    # End faces and back, behind the modelled front.
    verts = [(x0, 0.002, 0), (x1, 0.002, 0), (x1, y1, 0), (x0, y1, 0), (x0, 0.002, r), (x1, 0.002, r), (x1, y1, r), (x0, y1, r)]
    faces = [(0, 3, 7, 4), (1, 5, 6, 2), (3, 2, 6, 7)]
    mesh_obj("tower_sides", verts, faces, side_glass)
    # Corner columns: the wall has to end in something.
    cv, cf = [], []
    for cx in (x0, x1):
        add_box(cv, cf, cx - 0.09, -0.03, 0, cx + 0.09, 0.2, r)
    mesh_obj("corners", cv, cf, alu)
    # Parapet and anchor post, sized as in the sim's MJCF.
    pv, pf = [], []
    add_box(pv, pf, x0, -0.6, r, x1, y1, r + 1.0)
    add_box(pv, pf, run.anchor[0] - 0.08, run.anchor[1] - 0.05, r - 0.08, run.anchor[0] + 0.08, run.anchor[1] + 0.55, r + 0.08)
    mesh_obj("parapet", pv, pf, conc)


def add_box(v, f, x0, y0, z0, x1, y1, z1):
    b = len(v)
    v += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f += [(b, b + 3, b + 2, b + 1), (b + 4, b + 5, b + 6, b + 7), (b, b + 1, b + 5, b + 4),
          (b + 1, b + 2, b + 6, b + 5), (b + 2, b + 3, b + 7, b + 6), (b + 3, b, b + 4, b + 7)]


# ---------------------------------------------------------------- the robot

def rounded_ring(side, radius, z, n_corner=14):
    """Closed outline of a rounded square in the body frame, at height z above the glass."""
    half = side / 2
    r = min(radius, half)
    out_pts = []
    for cx, cy, a0 in ((half - r, half - r, 0), (-half + r, half - r, 90), (-half + r, -half + r, 180), (half - r, -half + r, 270)):
        for i in range(n_corner + 1):
            a = math.radians(a0 + 90 * i / n_corner)
            out_pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return out_pts


def loft(rings, close_top=True, close_bottom=True):
    verts, faces = [], []
    n = len(rings[0])
    for ring in rings:
        verts += ring
    for k in range(len(rings) - 1):
        for i in range(n):
            a, b = k * n + i, k * n + (i + 1) % n
            faces.append((a, b, b + n, a + n))
    if close_top:
        verts.append((0, 0, rings[-1][0][2]))
        c = len(verts) - 1
        for i in range(n):
            faces.append((len(rings[:-1]) * n + i, len(rings[:-1]) * n + (i + 1) % n, c))
    return verts, faces


def fillet(z0, z1, inset0, inset1, seg=6):
    """Quarter round from (inset0, z0) to (inset1, z1)."""
    out_pts = []
    for i in range(seg + 1):
        t = i / seg * math.pi / 2
        out_pts.append((inset0 + (inset1 - inset0) * (1 - math.cos(t)), z0 + (z1 - z0) * math.sin(t)))
    return out_pts


def robot_materials():
    shell = new_mat("shell")
    n = N(shell)
    coord = n.add("ShaderNodeTexCoord")
    p = coord.outputs["Object"]
    px, py, pz = n.split(p)
    micro = n.noise(p, 900.0, 3.0, 0.5)
    # Wear: fine scuffs along the travel axis, a dull grey film low on the walls and in the corners.
    scuff = n.smooth(0.60, 0.70, n.noise(n.xyz(n.mul(px, 22.0), n.mul(py, 240.0), n.mul(pz, 240.0)), 1.0, 4.0, 0.6))
    blotch = n.noise(p, 26.0, 6.0, 0.6)
    low = n.sub(1.0, n.smooth(0.03, 0.085, pz))
    soil = n.clamp01(n.add_(n.mul(0.45, low), n.mul(0.40, n.smooth(0.46, 0.68, blotch))))
    col = n.mix(soil, (0.50, 0.505, 0.50, 1), (0.31, 0.31, 0.295, 1))
    col = n.mix(n.mul(scuff, 0.22), col, (0.62, 0.62, 0.61, 1))
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(col, b.inputs["Base Color"])
    n.set(b.inputs["Roughness"], n.add_(n.add_(0.26, n.mul(0.08, micro)), n.add_(n.mul(0.18, soil), n.mul(0.2, scuff))))
    b.inputs["Specular IOR Level"].default_value = 0.5
    n.set(b.inputs["Coat Weight"], n.sub(0.55, n.mul(0.4, soil)))
    b.inputs["Coat Roughness"].default_value = 0.12
    out(n, b.outputs[0])

    panel = new_mat("panel")
    n = N(panel)
    coord = n.add("ShaderNodeTexCoord")
    p = coord.outputs["Object"]
    dust = n.noise(p, 60.0, 5.0, 0.55)
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(n.mix(n.mul(0.22, n.smooth(0.42, 0.7, dust)), (0.135, 0.14, 0.145, 1), (0.22, 0.22, 0.215, 1)), b.inputs["Base Color"])
    n.set(b.inputs["Roughness"], n.add_(0.30, n.mul(0.14, n.smooth(0.42, 0.7, dust))))
    b.inputs["Coat Weight"].default_value = 0.25
    b.inputs["Coat Roughness"].default_value = 0.2
    out(n, b.outputs[0])

    rubber = new_mat("rubber")
    n = N(rubber)
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.022, 0.023, 0.025, 1)
    b.inputs["Roughness"].default_value = 0.62
    out(n, b.outputs[0])

    track = new_mat("track")
    n = N(track)
    coord = n.add("ShaderNodeTexCoord")
    px, py, pz = n.split(coord.outputs["Object"])
    # Cross tread every 12 mm along the belt.
    tread = n.math("SINE", n.mul(px, 2 * math.pi / 0.012))
    bump = n.add("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.0015
    n.link(tread, bump.inputs["Height"])
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.03, 0.031, 0.032, 1)
    b.inputs["Roughness"].default_value = 0.55
    n.link(bump.outputs[0], b.inputs["Normal"])
    out(n, b.outputs[0])

    fibre = new_mat("fibre")
    n = N(fibre)
    coord = n.add("ShaderNodeTexCoord")
    nz = n.noise(coord.outputs["Object"], 500.0, 3.0, 0.7)
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(n.mix(n.smooth(0.4, 0.62, nz), (0.15, 0.15, 0.145, 1), (0.42, 0.42, 0.40, 1)), b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.92
    out(n, b.outputs[0])

    metal = new_mat("fastener")
    n = N(metal)
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.18, 0.18, 0.185, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.42
    out(n, b.outputs[0])

    cable = new_mat("cable")
    n = N(cable)
    b = n.add("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.55, 0.56, 0.56, 1)
    b.inputs["Roughness"].default_value = 0.5
    out(n, b.outputs[0])
    return shell, panel, rubber, track, fibre, metal, cable


def stadium_track(y_center, width, half_len, radius, z_center, seg=16):
    """A belt from the MJCF's roller line: rounded ends along x, swept across y."""
    ring = []
    for cx, a0 in ((half_len, -90.0), (-half_len, 90.0)):
        for i in range(seg + 1):
            a = math.radians(a0 + 180.0 * i / seg)
            ring.append((cx + radius * math.cos(a), z_center + radius * math.sin(a)))
    v, f = [], []
    n = len(ring)
    for y in (y_center - width / 2, y_center + width / 2):
        for x, z in ring:
            v.append((x, y, z))
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, j + n, i + n))
    f.append(tuple(range(n - 1, -1, -1)))
    f.append(tuple(range(n, 2 * n)))
    return v, f


def build_robot(run):
    """Square body at the sim's size: 0.36 m side, chassis from 0.02 to 0.10 m off the glass.
    Local z points out of the glass, as in the MJCF, so the MuJoCo pose applies unchanged.
    Tracks sit on the MJCF's roller lines. The pad bar sits at the sim's PAD_X."""
    shell, panel, rubber, track, fibre, metal, cable = robot_materials()
    S, R = run.body_side, 0.052
    zlo = run.ride_clear
    ztop = run.ride_clear + run.body_height
    rng = random.Random(11)
    parts = []

    def ring(inset, z, min_r=0.006):
        return rounded_ring(S - 2 * inset, max(R - inset, min_r), z)

    # Dark belly. The 2 cm ride gap stays open, so tracks and the pad edge show under the body.
    v, f = loft([ring(0.006, zlo + 0.001), ring(0.007, zlo + 0.001)], close_top=True)
    parts.append(mesh_obj("robot_belly", v, f, rubber, smooth=True))
    # Soft seal, set in from the tracks.
    v, f = loft([ring(0.065, 0.0012, 0.03), ring(0.062, 0.004, 0.03), ring(0.062, zlo + 0.002, 0.03)], close_top=False)
    parts.append(mesh_obj("robot_seal", v, f, rubber, smooth=True))

    # Tracks on the sim's roller lines, y = +/-0.15, touching the glass.
    for y in (0.15, -0.15):
        v, f = stadium_track(y, 0.05, 0.145, 0.035, 0.035)
        parts.append(mesh_obj("robot_track", v, f, track, smooth=True))

    # Pad bar at the sim's PAD_X, with a worn microfibre edge.
    pad_x = -0.13
    pv, pf = [], []
    add_box(pv, pf, pad_x - 0.045, -0.118, 0.0015, pad_x + 0.04, 0.118, 0.018)
    pad_fibres = []
    for k in range(1500):
        side = rng.random()
        if side < 0.72:
            bx, by, dx, dy = pad_x - 0.045, rng.uniform(-0.118, 0.118), -1.0, rng.uniform(-0.5, 0.5)
        else:
            sgn = 1 if rng.random() < 0.5 else -1
            bx, by, dx, dy = rng.uniform(pad_x - 0.045, pad_x + 0.04), sgn * 0.118, rng.uniform(-0.5, 0.5), sgn * 1.0
        L = rng.uniform(0.004, 0.013)
        w = rng.uniform(0.0008, 0.0016)
        z = rng.uniform(0.002, 0.016)
        b = len(pv)
        pv += [(bx, by - w, z), (bx, by + w, z), (bx + dx * L, by + dy * L, z + rng.uniform(-0.004, 0.003))]
        pf.append((b, b + 1, b + 2))
    parts.append(mesh_obj("robot_pad", pv, pf, fibre))

    # Shell: side wall, shoulder, narrow rim, sharp drop to the panel. A rubber gasket fills the seam.
    rim = 0.027
    sect = [(0.004, zlo), (0.0012, zlo + 0.002), (0.0, zlo + 0.006), (0.0, zlo + 0.0205),
            (0.0006, zlo + 0.0212), (0.0026, zlo + 0.0218), (0.0026, zlo + 0.0232), (0.0006, zlo + 0.0238), (0.0, zlo + 0.0245),
            (0.0, ztop - 0.018)]
    sect += fillet(ztop - 0.018, ztop, 0.0, 0.018, seg=8)[1:]
    sect += [(rim - 0.002, ztop), (rim - 0.0008, ztop - 0.0003), (rim, ztop - 0.0015), (rim + 0.0004, ztop - 0.006)]
    rings = [ring(i, z, 0.030) for i, z in sect]
    v, f = loft(rings, close_top=False)
    shell_ob = mesh_obj("robot_shell", v, f, shell, smooth=True)
    v, f = loft([ring(0.0016, zlo + 0.0214), ring(0.0013, zlo + 0.0225), ring(0.0016, zlo + 0.0236)], close_top=False)
    parts.append(mesh_obj("robot_gasket", v, f, rubber, smooth=True))

    # Inset panel with concentric corners and a gasket in the shadow gap.
    pz = ztop - 0.0065
    pin = rim + 0.0012
    rings = [ring(pin, ztop - 0.012, 0.028), ring(pin + 0.0008, pz - 0.0012, 0.028), ring(pin + 0.002, pz, 0.028), ring(pin + 0.006, pz, 0.028)]
    v, f = loft(rings, close_top=True)
    panel_ob = mesh_obj("robot_panel", v, f, panel, smooth=True)
    v, f = loft([ring(rim + 0.0002, pz - 0.0005, 0.028), ring(rim + 0.0012, pz + 0.0014, 0.028), ring(pin + 0.0024, pz + 0.0003, 0.028)], close_top=False)
    panel_gasket = mesh_obj("robot_panel_gasket", v, f, rubber, smooth=True)

    # Fasteners and intake slots on the panel. Details only, sized to the body.
    fv, ff = [], []
    seg = 16
    for cx, cy in ((0.118, 0.118), (-0.118, 0.118), (0.118, -0.118), (-0.118, -0.118)):
        b = len(fv)
        for r, z in ((0.0058, pz + 0.0002), (0.0052, pz + 0.0012), (0.0028, pz + 0.0014)):
            for i in range(seg):
                a = 2 * math.pi * i / seg
                fv.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
        for k in range(2):
            for i in range(seg):
                j = (i + 1) % seg
                ff.append((b + k * seg + i, b + k * seg + j, b + (k + 1) * seg + j, b + (k + 1) * seg + i))
        ff.append(tuple(b + 2 * seg + i for i in range(seg)))
    fast_ob = mesh_obj("robot_fasteners", fv, ff, metal, smooth=False)
    sv, sf = [], []
    for k in range(7):
        y = -0.03 + k * 0.01
        add_box(sv, sf, -0.112, y - 0.0016, pz, -0.066, y + 0.0016, pz + 0.0004)
    slot_ob = mesh_obj("robot_slots", sv, sf, rubber)

    # Tether boot at the sim's tether point, centre of the body.
    hv, hf = [], []
    seg = 40
    prof = [(0.024, pz), (0.024, pz + 0.002), (0.020, pz + 0.004), (0.011, pz + 0.012), (0.007, pz + 0.024), (0.0052, pz + 0.032), (0.0, pz + 0.032)]
    for r, z in prof:
        for i in range(seg):
            a = 2 * math.pi * i / seg
            hv.append((r * math.cos(a), r * math.sin(a), z))
    for k in range(len(prof) - 1):
        for i in range(seg):
            a, b = k * seg + i, k * seg + (i + 1) % seg
            hf.append((a, b, b + seg, a + seg))
    hub_ob = mesh_obj("robot_hub", hv, hf, shell, smooth=True)

    root = bpy.data.objects.new("robot", None)
    bpy.context.scene.collection.objects.link(root)
    root.rotation_mode = "QUATERNION"
    top_parts = [shell_ob, panel_ob, hub_ob, panel_gasket, fast_ob, slot_ob]
    for ob in parts + top_parts:
        ob.parent = root
    # The white body mirrored 10 cm away reads as a second plate and breaks the silhouette.
    # Only what sits low stays in the glass, which grounds the robot. An art choice, like the sky.
    for ob in top_parts:
        ob.visible_glossy = False

    # Tether, as a unit cylinder scaled along its length each frame.
    tv, tf = [], []
    seg = 12
    for z in (0.0, 1.0):
        for i in range(seg):
            a = 2 * math.pi * i / seg
            tv.append((math.cos(a), math.sin(a), z))
    for i in range(seg):
        j = (i + 1) % seg
        tf.append((i, j, j + seg, i + seg))
    teth = mesh_obj("tether", tv, tf, cable, smooth=True)
    teth.rotation_mode = "QUATERNION"
    return root, teth, pz + 0.03


# ---------------------------------------------------------------- volumes

def build_cloud_deck(haze):
    """Thin drifting haze layer below the camera. Art only."""
    mat = new_mat("deck")
    tree = mat.node_tree
    n = N(mat)
    coord = n.add("ShaderNodeTexCoord")
    p = coord.outputs["Object"]
    wisps = n.noise(p, shot_list.DECK_NOISE, 6.0, 0.55)
    px, py, pz = n.split(p)
    # Soft floor and ceiling. Object z runs -1..1 inside the box.
    fade = n.mul(n.smooth(-1.0, -0.2, pz), n.sub(1.0, n.smooth(0.2, 1.0, pz)))
    dens = n.mul(n.mul(n.smooth(0.44, 0.72, wisps), fade), shot_list.DECK_DENSITY)
    v = n.add("ShaderNodeVolumePrincipled")
    v.inputs["Color"].default_value = (0.86, 0.89, 0.90, 1)
    n.link(dens, v.inputs["Density"])
    v.inputs["Anisotropy"].default_value = 0.3
    o = n.add("ShaderNodeOutputMaterial")
    n.link(v.outputs[0], o.inputs["Volume"])
    bpy.ops.mesh.primitive_cube_add(size=2, location=shot_list.DECK_CENTER)
    ob = bpy.context.object
    ob.name = "deck"
    ob.scale = shot_list.DECK_SCALE
    ob.data.materials.append(mat)
    return ob


def drift_deck(deck, run, t0, t):
    """The haze layer moves with the recorded wind speed and direction. Scenery only, not simulated."""
    a = math.radians(run.world["wind_dir_deg"])
    d = run.wind_run(t0, t)
    c = shot_list.DECK_CENTER
    deck.location = (c[0] + d * math.cos(a), c[1] + d * math.sin(a), c[2])


# ---------------------------------------------------------------- render set-up

def setup_render(args):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    used = []
    for d in prefs.devices:
        d.use = d.type == "METAL"
        if d.use:
            used.append(d.name)
    print("render devices:", used)
    if not used:
        raise SystemExit("no Metal device")
    sc.cycles.device = "GPU"
    sc.cycles.samples = args.samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.012
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 4
    sc.cycles.transmission_bounces = 0
    sc.cycles.volume_bounces = 1
    sc.cycles.volume_step_rate = 2.0
    sc.cycles.sample_clamp_indirect = 6.0
    sc.cycles.filter_width = 1.3
    sc.render.film_transparent = False
    if args.mode == "clip":
        # A half-open shutter. Blur comes only from the recorded poses keyed each frame.
        sc.render.use_motion_blur = True
        sc.render.motion_blur_shutter = 0.5
        sc.render.motion_blur_position = "CENTER"
    w, h = args.res.split("x")
    sc.render.resolution_x, sc.render.resolution_y = int(w), int(h)
    sc.render.resolution_percentage = 100
    sc.render.use_persistent_data = True
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "16"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"


def place_camera(cam, pos, target, lens, focus_point, fstop, roll_deg=0.0):
    cam.location = pos
    f = (Vector(target) - Vector(pos)).normalized()
    q = f.to_track_quat("-Z", "Y")
    if roll_deg:
        q = q @ Quaternion((0, 0, 1), math.radians(roll_deg))
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = q
    cam.data.lens = lens
    cam.data.sensor_width = 36.0
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = fstop
    cam.data.dof.aperture_blades = 7
    cam.data.dof.aperture_ratio = 1.0
    fwd = q @ Vector((0, 0, -1))
    cam.data.dof.focus_distance = (Vector(focus_point) - Vector(pos)).dot(fwd)
    cam.data.clip_start = 0.05
    cam.data.clip_end = 40000.0


# ---------------------------------------------------------------- main

def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = run_data.Run(args.trial)
    shot = shot_list.SHOTS[args.shot]
    default_t = shot["t"] if args.mode == "clip" else shot.get("still_t", shot["t"])
    t0 = args.t if args.t is not None else default_t

    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    setup_render(args)

    haze = shot_list.HAZE
    focus = (0.0, 0.0, run.area["z1"])
    build_world(args.sky, haze)

    img = bpy.data.images.new("dirt", run.tex_px_w, run.tex_px_h, float_buffer=True, alpha=False)
    img.colorspace_settings.name = "Non-Color"

    glass_mat = glass_material(run, img, haze, focus)
    alu = alu_material(haze, focus)
    seal = dark_material("seal", (0.008, 0.008, 0.009), 0.5, haze, focus)
    side = dark_material("side_glass", (0.018, 0.022, 0.025), 0.08, haze, focus)
    conc = dark_material("concrete", (0.28, 0.27, 0.25), 0.8, haze, focus)
    build_glass(run, glass_mat)
    build_frame(run, alu, seal)
    build_tower_body(run, alu, side, conc)
    t_c = time.time()
    city_gen.build(run, haze, focus, N, out, new_mat)
    print("city built in %.1f s" % (time.time() - t_c))
    if not args.no_volume and shot_list.DECK_DENSITY > 0:
        deck = build_cloud_deck(haze)

    robot, tether, boot_z = build_robot(run)
    if "deck" not in dir():
        deck = None

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    if args.mode == "still":
        n_frames = 1
    else:
        secs = args.seconds if args.seconds is not None else shot.get("seconds", 10.0)
        n_frames = int(round(secs * args.fps))
    end = args.end_frame if args.end_frame is not None else n_frames
    log = []
    timing = []

    def apply_pose(t):
        pos, quat = run.pose(t)
        robot.location = pos
        robot.rotation_quaternion = quat
        # Tether: the MuJoCo straight tendon, anchor to tether point. The visible end starts at the
        # tip of the boot so the line clears the rim.
        q = Quaternion(quat)
        tp = Vector(pos) + q @ Vector((0, 0, boot_z))
        d = Vector(run.anchor) - tp
        tether.location = tp
        tether.rotation_quaternion = d.to_track_quat("Z", "Y")
        tether.scale = (run.tether_radius, run.tether_radius, d.length)

    if args.mode == "clip":
        # Key the recorded pose on each frame, so the shutter blurs only recorded motion.
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        for fi in range(max(args.start_frame - 1, 0), end + 1):
            apply_pose(t0 + fi / args.fps)
            for ob, paths in ((robot, ("location", "rotation_quaternion")),
                              (tether, ("location", "rotation_quaternion", "scale"))):
                for path in paths:
                    ob.keyframe_insert(data_path=path, frame=fi + 1)

    for fi in range(args.start_frame, end):
        t = t0 + fi / args.fps if args.mode == "clip" else t0
        if args.mode == "clip":
            sc.frame_set(fi + 1)
        else:
            apply_pose(t)

        if deck is not None:
            drift_deck(deck, run, t0, t)
        grid = run.dirt_image(t)
        img.pixels.foreach_set(np.repeat(grid.ravel()[:, None], 4, axis=1).ravel())
        # With persistent data Cycles keeps the first texture unless both tags are set. A frozen lane
        # was the visible symptom: check a clip's last frame for a lane right up to the robot.
        img.update()
        img.update_tag()
        glass_mat.node_tree.update_tag()

        u = fi / max(n_frames - 1, 1) if args.mode == "clip" else 1.0
        if args.mode == "clip":
            r0, r1 = np.array(run.pose(t0)[0]), np.array(run.pose(t0 + (n_frames - 1) / args.fps)[0])
        else:
            r0 = r1 = np.array(run.pose(t0)[0])
        camp = shot_list.camera_at(shot, u, r0, r1, np.array(run.pose(t)[0]))
        place_camera(cam, camp["pos"], camp["target"], camp["lens"], camp["focus"], camp["fstop"], camp.get("roll", 0.0))

        path = out_dir / ("frame_%04d.exr" % fi if args.mode == "clip" else "still.exr")
        sc.render.filepath = str(path)
        t_s = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - t_s
        timing.append(dt)
        bpy.context.view_layer.update()
        from bpy_extras.object_utils import world_to_camera_view
        px = world_to_camera_view(sc, cam, robot.matrix_world.translation)
        log.append({"frame": fi, "t": t, "robot_loc": list(robot.matrix_world.translation),
                    "robot_quat": list(robot.matrix_world.to_quaternion()),
                    "screen": [px.x, px.y, px.z], "cam": list(cam.location), "seconds": dt,
                    "lens": cam.data.lens, "dirt_cov": run.coverage(t)})
        print("frame %d t=%.3f %.1f s" % (fi, t, dt), flush=True)
        (out_dir / ("poses_%04d_%04d.json" % (args.start_frame, end))).write_text(json.dumps(log, indent=0))
    print("mean seconds per frame %.1f" % (sum(timing) / max(len(timing), 1)))


main()
