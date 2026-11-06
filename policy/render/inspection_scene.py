"""Blender side of the inspection render. Run through inspection.py, not directly.

Axes as in the record: z up, metres. Every solid comes from the record's lists. Objects named solid_* are the physics solids, at their recorded positions.
Objects named visual_* are picture only: the physics never reads them, and nothing here writes back to the record.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inspection_record as R  # noqa: E402

TEX = HERE.parents[1] / "design" / "render" / "_cache" / "tex"
HAZE_K = 0.016
HAZE = (0.36, 0.37, 0.38)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="still", choices=["still", "clip", "probe"])
    ap.add_argument("--t", type=float, default=None)
    ap.add_argument("--probe-times", default="")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--device", default="auto", choices=["auto", "metal", "optix", "cuda"])
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    ap.add_argument("--override", default=None)
    ap.add_argument("--no-blur", action="store_true")
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1:])


# ---------------------------------------------------------------- device

ORDER = {"auto": ["OPTIX", "CUDA", "METAL"], "metal": ["METAL"], "optix": ["OPTIX"], "cuda": ["CUDA"]}


def set_device(choice):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ORDER[choice]:
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        used = [d for d in prefs.devices if d.type == kind]
        if used:
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = "GPU"
            print("render devices:", kind, [d.name for d in used], flush=True)
            return kind
    raise SystemExit(f"no GPU found for --device {choice}. Cycles lists: " + str([(d.type, d.name) for d in prefs.devices]))


def setup_render(a):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    set_device(a.device)
    c = sc.cycles
    c.samples = a.samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = a.threshold
    c.adaptive_min_samples = min(16, a.samples)
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    c.denoising_prefilter = "ACCURATE"
    c.max_bounces = 7
    c.diffuse_bounces = 3
    c.glossy_bounces = 4
    c.transmission_bounces = 2
    c.volume_bounces = 0
    c.transparent_max_bounces = 4
    c.sample_clamp_direct = 0.0
    c.sample_clamp_indirect = 6.0
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.blur_glossy = 0.5
    c.filter_width = 1.3
    c.use_auto_tile = False
    sc.render.use_persistent_data = True
    w, h = a.res.split("x")
    sc.render.resolution_x, sc.render.resolution_y = int(w), int(h)
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    sc.render.image_settings.exr_codec = "DWAA"
    sc.render.use_motion_blur = not a.no_blur
    sc.render.motion_blur_shutter = 0.4
    sc.world = bpy.data.worlds.new("hall")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.013, 0.015, 1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0


# ---------------------------------------------------------------- shader helpers

class G:
    """A small node-graph writer. Sockets or plain numbers both work as inputs."""

    def __init__(self, name):
        self.mat = bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.obj = self.nt.nodes.new("ShaderNodeTexCoord").outputs["Object"]

    def n(self, kind):
        return self.nt.nodes.new(kind)

    def link(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.nt.links.new(val, sock)
        elif isinstance(val, (tuple, list)) and len(val) == 3:
            sock.default_value = (*val, 1.0) if len(sock.default_value) == 4 else val
        else:
            sock.default_value = val

    def math(self, op, a, b=0.0, clamp=False):
        m = self.n("ShaderNodeMath")
        m.operation = op
        m.use_clamp = clamp
        self.link(m.inputs[0], a)
        self.link(m.inputs[1], b)
        return m.outputs[0]

    def mul(self, a, b, clamp=False):
        return self.math("MULTIPLY", a, b, clamp)

    def lerp(self, f, a, b):
        m = self.n("ShaderNodeMix")
        m.data_type = "FLOAT"
        self.link(m.inputs[0], f)
        self.link(m.inputs[2], a)
        self.link(m.inputs[3], b)
        return m.outputs[0]

    def cmix(self, f, a, b, blend="MIX"):
        m = self.n("ShaderNodeMix")
        m.data_type = "RGBA"
        m.blend_type = blend
        self.link(m.inputs[0], f)
        self.link(m.inputs[6], a)
        self.link(m.inputs[7], b)
        return m.outputs[2]

    def cmul(self, c, f):
        return self.cmix(1.0, c, self.gray(f), "MULTIPLY")

    def gray(self, f):
        m = self.n("ShaderNodeCombineColor")
        for i in range(3):
            self.link(m.inputs[i], f)
        return m.outputs[0]

    def luma(self, c):
        m = self.n("ShaderNodeRGBToBW")
        self.nt.links.new(c, m.inputs[0])
        return m.outputs[0]

    def rng(self, v, a, b, c, d, smooth=True):
        m = self.n("ShaderNodeMapRange")
        m.interpolation_type = "SMOOTHSTEP" if smooth else "LINEAR"
        m.clamp = True
        self.link(m.inputs["Value"], v)
        for key, val in (("From Min", a), ("From Max", b), ("To Min", c), ("To Max", d)):
            self.link(m.inputs[key], val)
        return m.outputs[0]

    def noise(self, scale, detail=5.0, rough=0.55, vec=None, coords=None):
        m = self.n("ShaderNodeTexNoise")
        self.nt.links.new(vec or self.obj, m.inputs["Vector"])
        m.inputs["Scale"].default_value = scale
        m.inputs["Detail"].default_value = detail
        m.inputs["Roughness"].default_value = rough
        return m.outputs["Fac"]

    def scaled(self, s):
        m = self.n("ShaderNodeMapping")
        self.nt.links.new(self.obj, m.inputs["Vector"])
        m.inputs["Scale"].default_value = s if isinstance(s, (tuple, list)) else (s, s, s)
        return m.outputs[0]

    def img(self, path, vec, colour=False, box=True):
        t = self.n("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(path), check_existing=True)
        t.image.colorspace_settings.name = "sRGB" if colour else "Non-Color"
        if box:
            t.projection = "BOX"
            t.projection_blend = 0.2
        self.nt.links.new(vec, t.inputs[0])
        return t

    def tex(self, name, vec, part, colour=False):
        files = list((TEX / name).glob(f"*_{part}.jpg"))
        if not files:
            raise SystemExit(f"map missing: {name} {part}. Run policy/render/inspection_assets.py")
        return self.img(files[0], vec, colour).outputs[0]

    def finish(self, shader):
        """Depth haze on camera rays only: cheap air, without a volume."""
        lp = self.n("ShaderNodeLightPath")
        fog = self.math("SUBTRACT", 1.0, self.math("EXPONENT", self.mul(self.mul(lp.outputs["Ray Length"], -HAZE_K), 1.0)))
        f = self.mul(fog, lp.outputs["Is Camera Ray"])
        e = self.n("ShaderNodeEmission")
        e.inputs[0].default_value = (*HAZE, 1)
        e.inputs[1].default_value = 1.0
        m = self.n("ShaderNodeMixShader")
        self.nt.links.new(f, m.inputs[0])
        self.nt.links.new(shader, m.inputs[1])
        self.nt.links.new(e.outputs[0], m.inputs[2])
        o = self.n("ShaderNodeOutputMaterial")
        self.nt.links.new(m.outputs[0], o.inputs[0])
        return self.mat

    def principled(self):
        return self.n("ShaderNodeBsdfPrincipled")


def surface(name, tex=None, scale=1.0, tint=(1, 1, 1), color=None, metal=0.0, rough=0.5, rough_tex=0.0, bump=0.0, rust=0.0, streak=0.0, grime=0.6, coat=0.0, dust=0.15, wear=0.5):
    """A weathered PBR surface in object (here world) coordinates, in metres. Box projection so nothing needs UVs."""
    g = G(name)
    uv = g.scaled(1.0 / scale)
    if tex:
        base = g.cmix(1.0, g.tex(tex, uv, "Color", True), tint, "MULTIPLY")
    else:
        c = g.n("ShaderNodeRGB")
        c.outputs[0].default_value = (*(color or tint), 1)
        base = c.outputs[0]
    # Large-scale unevenness, so that no surface is a flat tone.
    mac = g.noise(1.3, 2.0, 0.55)
    base = g.cmul(base, g.rng(mac, 0.3, 0.7, 0.8, 1.1, False))
    # CC0 imperfection maps: dull patches and fine mottling in colour and gloss.
    imp = g.luma(g.tex("SurfaceImperfections015", g.scaled(1 / 1.9), "Color", True))
    base = g.cmul(base, g.rng(imp, 0.1, 0.7, 1.0 - 0.14 * wear, 1.0, False))
    r = g.math("ADD", rough, g.mul(g.rng(imp, 0.15, 0.6, 0.16, -0.05, False), wear * 2))
    if rough_tex and tex and list((TEX / tex).glob("*_Roughness.jpg")):
        r = g.lerp(rough_tex, r, g.tex(tex, uv, "Roughness"))
    m = metal
    if dust:
        speck = g.noise(38.0, 2.0, 0.6)
        base = g.cmix(g.mul(g.rng(speck, 0.42, 0.72, 0.0, 1.0), dust), base, (0.32, 0.30, 0.27))
    if wear and not metal:
        # Bright scratches through the paint to steel.
        sc_ = g.luma(g.tex("Scratches003", g.scaled(1 / 1.2), "Color", True))
        f = g.mul(g.rng(sc_, 0.2, 0.55, 0.0, 1.0), wear)
        base = g.cmix(f, base, (0.34, 0.33, 0.31))
        r = g.lerp(f, r, 0.35)
        m = g.mul(f, 0.8)
    if streak:
        # Run-off: long vertical marks.
        sv = g.noise(1.0, 2.0, 0.5, g.scaled((9.0, 9.0, 0.28)))
        base = g.cmul(base, g.rng(sv, 0.4, 0.68, 1.0 - 0.34 * streak, 1.0, False))
    if rust:
        rv = g.noise(4.5, 4.0, 0.62, g.scaled((1.0, 1.0, 0.5)))
        fine = g.noise(40.0, 2.0, 0.6)
        v = g.math("ADD", rv, g.mul(fine, 0.14))
        hi = 0.735 - 0.08 * rust
        fr = g.rng(v, hi - 0.015, hi + 0.02, 0.0, 1.0)
        rc = g.cmix(0.72, g.tex("Rust009", g.scaled(1 / 0.5), "Color", True), (0.075, 0.048, 0.03))
        base = g.cmix(fr, base, rc)
        r = g.lerp(fr, r, 0.82)
        m = g.lerp(fr, m, 0.0)
        # A brown tea stain under and round the rust.
        halo = g.rng(g.noise(4.5, 2.0, 0.5, g.scaled((1.0, 1.0, 0.25))), 0.6, 0.74, 0.0, 0.22 * rust + 0.04)
        base = g.cmix(halo, base, (0.09, 0.055, 0.03))
    if grime:
        sep = g.n("ShaderNodeSeparateXYZ")
        g.nt.links.new(g.obj, sep.inputs[0])
        low = g.rng(sep.outputs[2], 0.0, 0.9, 1.0 - grime * 0.55, 1.0, True)
        base = g.cmul(base, low)
    b = g.principled()
    g.link(b.inputs["Base Color"], base)
    g.link(b.inputs["Metallic"], m)
    g.link(b.inputs["Roughness"], r)
    if coat:
        g.link(b.inputs["Coat Weight"], coat)
        g.link(b.inputs["Coat Roughness"], 0.2)
    if bump and tex:
        files = list((TEX / tex).glob("*_Displacement.jpg"))
        if files:
            bn = g.n("ShaderNodeBump")
            bn.inputs["Strength"].default_value = bump
            bn.inputs["Distance"].default_value = 0.01
            g.nt.links.new(g.img(files[0], uv).outputs[0], bn.inputs["Height"])
            g.nt.links.new(bn.outputs[0], b.inputs["Normal"])
    return g.finish(b.outputs[0])


def emission(name, col, strength):
    g = G(name)
    e = g.n("ShaderNodeEmission")
    e.inputs[0].default_value = (*col, 1)
    # A low-frequency variation, like dirty polycarbonate or a yellowing lens.
    g.link(e.inputs[1], g.mul(g.rng(g.noise(3.0, 4.0), 0.3, 0.7, 0.7, 1.15, False), strength))
    return g.finish(e.outputs[0])


def hazard(name, a=(0.72, 0.5, 0.02), b=(0.012, 0.012, 0.012), period=0.2):
    g = G(name)
    w = g.n("ShaderNodeTexWave")
    g.nt.links.new(g.obj, w.inputs["Vector"])
    w.wave_type = "BANDS"
    w.bands_direction = "DIAGONAL"
    w.wave_profile = "SAW"
    w.inputs["Scale"].default_value = 1.0 / period / 1.42
    w.inputs["Distortion"].default_value = 0.0
    f = g.rng(w.outputs["Fac"], 0.49, 0.51, 0.0, 1.0, False)
    c = g.cmix(f, b, a)
    wear = g.rng(g.noise(9.0, 6.0, 0.6), 0.6, 0.72, 0.0, 1.0)
    c = g.cmix(wear, c, (0.2, 0.19, 0.17))
    p = g.principled()
    g.link(p.inputs["Base Color"], c)
    g.link(p.inputs["Roughness"], 0.55)
    return g.finish(p.outputs[0])


# ---------------------------------------------------------------- floor masks, baked from the record

def fbm(shape, cells, seed, octaves=4, gain=0.55):
    """Band-limited noise through the FFT, -1..1-ish. Numpy only. Cells is the number of blobs across the longer side."""
    rng = np.random.default_rng(seed)
    h, w = shape
    fy, fx = np.fft.fftfreq(h)[:, None] * h, np.fft.rfftfreq(w)[None, :] * w
    out = np.zeros(shape, np.float32)
    amp = 1.0
    for _ in range(octaves):
        spec = np.fft.rfft2(rng.normal(size=shape).astype(np.float32))
        r = np.hypot(fy, fx)
        out += amp * np.fft.irfft2(spec * np.exp(-((r / cells) ** 2)), s=shape).astype(np.float32)
        amp *= gain
        cells *= 2.0
    return out / (out.std() + 1e-9) / 2.5


def blur(a, px):
    h, w = a.shape
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
    return np.fft.irfft2(np.fft.rfft2(a) * np.exp(-2 * (math.pi * px) ** 2 * (fx ** 2 + fy ** 2)), s=a.shape).astype(np.float32)


FLOOR = (-5.0, 17.0, -10.0, 10.0)
FLOOR_PX = 180  # per metre


def segment_mask(xx, yy, a, b, half):
    a, b = np.array(a, float), np.array(b, float)
    d = b - a
    L = np.hypot(*d)
    u = ((xx - a[0]) * d[0] + (yy - a[1]) * d[1]) / L
    v = np.abs(-(xx - a[0]) * d[1] + (yy - a[1]) * d[0]) / L
    return (v <= half) & (u >= 0) & (u <= L)


def bake_floor(rec, out_dir):
    x0, x1, y0, y1 = FLOOR
    w, h = int((x1 - x0) * FLOOR_PX), int((y1 - y0) * FLOOR_PX)
    xs = x0 + (np.arange(w) + 0.5) / FLOOR_PX
    ys = y0 + (np.arange(h) + 0.5) / FLOOR_PX
    xx, yy = np.meshgrid(xs.astype(np.float32), ys.astype(np.float32))
    wear = fbm((h, w), 180.0, 3)
    wear_big = fbm((h, w), 22.0, 4)
    # Paint: only where the record has a floor line, 10 cm wide, chipped by wear.
    paint = np.zeros((h, w), np.float32)
    for o in rec.world["scenery"]:
        if o["kind"] == "floor_line":
            paint[segment_mask(xx, yy, (o["x0"], o["y0"]), (o["x1"], o["y1"]), 0.05)] = 1.0
    keep = (wear + 0.45 * wear_big) > -0.55
    paint = blur(paint * keep, 0.7)
    # Saw-cut joints every 3 m, 8 mm wide, slightly wandering.
    jw = fbm((h, w), 12.0, 5) * 0.006
    jx = np.abs(((xx + jw + 0.5) % 3.0) - 1.5) > 1.5 - 0.005
    jy = np.abs(((yy + jw + 0.5) % 3.0) - 1.5) > 1.5 - 0.005
    joint = blur((jx | jy).astype(np.float32), 0.6)
    # Oil: soft stains under the pumps and where things stood, with tracked-off drips. Art: no record of these.
    oil = np.zeros((h, w), np.float32)
    rng = np.random.default_rng(21)
    spots = [(o["x"], o["y"] + rng.uniform(-0.2, 0.2), 0.85) for o in rec.world["scenery"] if o["kind"] == "pump"]
    spots += [(o["x"], o["y"], 0.6) for o in rec.world["scenery"] if o["kind"] == "tank"]
    spots += [(rng.uniform(-3, 15), rng.uniform(-1.6, 5.5), rng.uniform(0.12, 0.45)) for _ in range(26)]
    wob = fbm((h, w), 90.0, 6)
    for sx, sy, r in spots:
        d = np.hypot(xx - sx, (yy - sy) * rng.uniform(0.8, 1.3)) / r
        oil = np.maximum(oil, np.clip(1.15 - d + 0.5 * wob, 0, 1) ** 0.7 * rng.uniform(0.25, 0.75))
    # Tyre tracks and foot traffic along the walkway centre: faint and darker.
    scuff = np.zeros((h, w), np.float32)
    for side in (-0.55, 0.55):
        scuff[segment_mask(xx, yy, (-4.0, side), (6.0, side), 0.09)] = 1
        scuff[segment_mask(xx, yy, (4.0, 4.0 + side), (16.0, 4.0 + side), 0.09)] = 1
    scuff = blur(scuff, 9.0) * np.clip(0.55 + 0.9 * fbm((h, w), 60.0, 7), 0, 1)
    oil = np.clip(oil + 0.18 * scuff, 0, 1)
    # Wet: the union of the record's wet_patch cylinders. The edge wanders by at most 4 cm; visual only.
    wet = np.zeros((h, w), np.float32)
    damp = np.zeros((h, w), np.float32)
    edge = fbm((h, w), 45.0, 8)
    edge = np.clip(edge, -1, 1) * 0.04
    circles = [(s["pos"][0], s["pos"][1], s["size"][0]) for s in rec.solids if s["material"] == "wet"]
    if rec.world["floor"]["friction"] < 0.2:
        wet[:] = 1.0
    for cx, cy, r in circles:
        d = np.hypot(xx - cx, yy - cy) + edge
        wet = np.maximum(wet, (d <= r).astype(np.float32))
    wet = blur(wet, 1.2)
    damp = np.clip(blur(wet, 22.0) * 1.3, 0, 1)
    wetness = np.clip(np.maximum(wet, 0.5 * damp), 0, 1)
    if circles:
        np.save(out_dir / "floor_wet.npy", wet[::2, ::2])
    px = np.stack([paint, oil, wetness, joint], axis=2).astype(np.float32)
    img = bpy.data.images.new("floor_masks", w, h, float_buffer=True, alpha=True)
    img.colorspace_settings.name = "Non-Color"
    img.alpha_mode = "CHANNEL_PACKED"
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.pack()
    return img, circles


def floor_material(img):
    g = G("floor")
    x0, x1, y0, y1 = FLOOR
    m = g.n("ShaderNodeMapping")
    g.nt.links.new(g.obj, m.inputs["Vector"])
    m.inputs["Location"].default_value = (-x0 / (x1 - x0), -y0 / (y1 - y0), 0)
    m.inputs["Scale"].default_value = (1 / (x1 - x0), 1 / (y1 - y0), 1)
    t = g.n("ShaderNodeTexImage")
    t.image = img
    t.interpolation = "Cubic"
    t.extension = "EXTEND"
    g.nt.links.new(m.outputs[0], t.inputs[0])
    sep = g.n("ShaderNodeSeparateColor")
    g.nt.links.new(t.outputs[0], sep.inputs[0])
    paint, oil, wet = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    joint = t.outputs[1]
    uv = g.scaled(1 / 3.1)
    uv2 = g.scaled(1 / 7.3)
    col = g.tex("Concrete042A", uv, "Color", True)
    alt = g.tex("Concrete034", uv2, "Color", True)
    alt = g.cmix(1.0, alt, (0.42, 0.41, 0.39), "MULTIPLY")
    macro = g.rng(g.noise(0.45, 3.0, 0.58), 0.36, 0.64, 0.0, 1.0)
    col = g.cmix(macro, col, alt)
    col = g.cmix(1.0, col, (0.86, 0.85, 0.82), "MULTIPLY")
    col = g.cmul(col, g.rng(g.noise(0.9, 3.0, 0.6), 0.28, 0.72, 0.6, 1.12, False))
    imp = g.tex("SurfaceImperfections016", g.scaled(1 / 2.9), "Color", True)
    col = g.cmul(col, g.rng(g.luma(imp), 0.15, 0.55, 0.62, 1.08, False))
    spots = g.tex("SurfaceImperfections013", g.scaled(1 / 1.7), "Color", True)
    col = g.cmul(col, g.rng(g.luma(spots), 0.15, 0.7, 1.0, 1.25, False))
    col = g.cmix(g.mul(oil, 0.88), col, (0.018, 0.016, 0.014))
    col = g.cmix(paint, col, (0.66, 0.42, 0.03))
    col = g.cmul(col, g.math("SUBTRACT", 1.0, g.mul(joint, 0.9)))
    # Water darkens what it wets.
    col = g.cmul(col, g.math("SUBTRACT", 1.0, g.mul(wet, 0.42)))
    rg = g.tex("Concrete042A", uv, "Roughness")
    r = g.lerp(0.6, 0.72, rg)
    r = g.lerp(g.mul(oil, 0.8), r, 0.28)
    r = g.lerp(paint, r, 0.5)
    r = g.lerp(wet, r, 0.3)
    b = g.principled()
    g.link(b.inputs["Base Color"], col)
    g.link(b.inputs["Roughness"], r)
    g.link(b.inputs["Coat Weight"], g.mul(wet, g.rng(g.noise(2.2, 3.0, 0.55), 0.35, 0.6, 0.72, 1.0, False)))
    g.link(b.inputs["Coat Roughness"], g.rng(g.noise(3.0, 3.0), 0.3, 0.7, 0.006, 0.055, False))
    g.link(b.inputs["Coat IOR"], 1.33)
    # Bump: concrete where dry, and a meniscus at the water's edge. Wet concrete keeps a little relief.
    h = g.mul(g.tex("Concrete042A", uv, "Displacement"), g.math("SUBTRACT", 1.0, g.mul(wet, 0.85)))
    bn = g.n("ShaderNodeBump")
    bn.inputs["Strength"].default_value = 0.6
    bn.inputs["Distance"].default_value = 0.006
    g.nt.links.new(g.math("ADD", g.mul(h, 0.5), g.mul(joint, -2.0)), bn.inputs["Height"])
    g.nt.links.new(bn.outputs[0], b.inputs["Normal"])
    cn = g.n("ShaderNodeBump")
    cn.inputs["Strength"].default_value = 0.22
    cn.inputs["Distance"].default_value = 0.01
    g.nt.links.new(g.math("ADD", g.mul(wet, 1.0), g.mul(g.noise(7.0, 3.0), 0.12)), cn.inputs["Height"])
    g.nt.links.new(cn.outputs[0], b.inputs["Coat Normal"])
    return g.finish(b.outputs[0])


# ---------------------------------------------------------------- geometry

def qmat(q):
    """3x3 rotation from an (x, y, z, w) quaternion."""
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def frame_of(axis):
    """A right-handed frame whose third column is the axis."""
    a = np.array(axis, float)
    a /= np.linalg.norm(a)
    u = np.cross(a, (0, 0, 1)) if abs(a[2]) < 0.9 else np.cross(a, (1, 0, 0))
    u /= np.linalg.norm(u)
    return np.column_stack([u, np.cross(a, u), a])


class Batch:
    """Triangles and quads gathered per material into one object. Flat or smooth per face, with hard edges by split vertices."""

    def __init__(self):
        self.v, self.f, self.s, self.n = [], [], [], 0

    def add(self, verts, faces, smooth=False):
        verts = np.asarray(verts, float)
        self.v.append(verts)
        self.f += [tuple(i + self.n for i in face) for face in faces]
        self.s += [smooth] * len(faces)
        self.n += len(verts)

    def build(self, name, mat, visual, coll):
        if not self.v:
            return None
        me = bpy.data.meshes.new(name)
        me.from_pydata(np.vstack(self.v).tolist(), [], self.f)
        me.polygons.foreach_set("use_smooth", self.s)
        me.update()
        me.materials.append(mat)
        ob = bpy.data.objects.new(name, me)
        ob["visual_only"] = visual
        coll.objects.link(ob)
        return ob


BOX_CORNERS = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], float)


def box_mesh(half, ch):
    """A box with chamfered edges, so that its edges catch light. Local to its centre."""
    hx, hy, hz = half
    ch = min(ch, 0.45 * min(half))
    v, idx = [], {}
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                for a in range(3):
                    p = [sx * hx, sy * hy, sz * hz]
                    for k in range(3):
                        if k != a:
                            p[k] -= [sx, sy, sz][k] * ch
                    idx[(sx, sy, sz, a)] = len(v)
                    v.append(p)
    f = []
    for a, (b, c) in enumerate(((1, 2), (0, 2), (0, 1))):
        for s in (-1, 1):
            cs = []
            for t in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                sg = [0, 0, 0]
                sg[a], sg[b], sg[c] = s, t[0], t[1]
                cs.append(idx[(*sg, a)])
            f.append(tuple(cs if s > 0 and a != 1 or s < 0 and a == 1 else cs[::-1]))
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            f.append((idx[(s1, s2, -1, 0)], idx[(s1, s2, -1, 1)], idx[(s1, s2, 1, 1)], idx[(s1, s2, 1, 0)]))
            f.append((idx[(s1, -1, s2, 0)], idx[(s1, -1, s2, 2)], idx[(s1, 1, s2, 2)], idx[(s1, 1, s2, 0)]))
            f.append((idx[(-1, s1, s2, 1)], idx[(-1, s1, s2, 2)], idx[(1, s1, s2, 2)], idx[(1, s1, s2, 1)]))
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                f.append((idx[(sx, sy, sz, 0)], idx[(sx, sy, sz, 1)], idx[(sx, sy, sz, 2)]))
    return np.array(v), f


def box(b, pos, half, q=(0, 0, 0, 1), ch=0.002, rot=None):
    v, f = box_mesh(half, ch)
    m = rot if rot is not None else qmat(q)
    b.add(v @ m.T + np.asarray(pos, float), f)


def lathe(b, pos, axis, profile, seg=32, smooth=True, caps=True):
    """Revolves (radius, height) pairs about the axis. Sides are smooth between rows unless a row repeats, which makes a hard edge."""
    m = frame_of(axis)
    a = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    c = np.column_stack([np.cos(a), np.sin(a)])
    p = np.asarray(pos, float)
    rows = [(i, j) for i, j in zip(profile[:-1], profile[1:])]
    for (r0, h0), (r1, h1) in rows:
        if (r0, h0) == (r1, h1):
            continue
        ring0 = np.column_stack([c * r0, np.full(seg, h0)])
        ring1 = np.column_stack([c * r1, np.full(seg, h1)])
        v = np.vstack([ring0, ring1]) @ m.T + p
        f = [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)]
        b.add(v, f, smooth=smooth)
    if caps:
        for (r, h), flip in ((profile[0], True), (profile[-1], False)):
            if r > 1e-5:
                v = np.column_stack([c * r, np.full(seg, h)]) @ m.T + p
                ids = list(range(seg))
                b.add(v, [tuple(ids[::-1] if flip else ids)])


def cyl(b, p0, p1, r, seg=24, ch=0.0, caps=True):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.linalg.norm(p1 - p0)
    ch = min(ch, r * 0.4, L * 0.3)
    prof = [(r - ch, 0.0), (r, ch), (r, ch), (r, L - ch), (r, L - ch), (r - ch, L)] if ch > 0 else [(r, 0.0), (r, L)]
    lathe(b, p0, p1 - p0, prof, seg, smooth=True, caps=caps)


def tube(b, pts, r, bend=None, seg=20):
    """A pipe along points, with round elbows."""
    pts = [np.asarray(p, float) for p in pts]
    bend = bend if bend is not None else r * 2.2
    a = pts[0]
    for i in range(1, len(pts)):
        p = pts[i]
        if i == len(pts) - 1:
            cyl(b, a, p, r, seg, caps=True)
            return
        n = pts[i + 1]
        d0, d1 = (p - a) / np.linalg.norm(p - a), (n - p) / np.linalg.norm(n - p)
        s, e = p - d0 * bend, p + d1 * bend
        cyl(b, a, s, r, seg, caps=False)
        ring = []
        steps = 6
        for k in range(steps + 1):
            u = k / steps
            c = (1 - u) ** 2 * s + 2 * u * (1 - u) * p + u ** 2 * e
            tan = 2 * (1 - u) * (p - s) + 2 * u * (e - p)
            tan /= np.linalg.norm(tan)
            ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
            # A frame carried through the bend keeps the rings aligned.
            axis = np.cross(d0, d1)
            axis /= np.linalg.norm(axis)
            side = np.cross(tan, axis)
            ring.append(np.outer(np.cos(ang), axis * r) + np.outer(np.sin(ang), side * r) + c)
        v = np.vstack(ring)
        f = [(k * seg + j, k * seg + (j + 1) % seg, (k + 1) * seg + (j + 1) % seg, (k + 1) * seg + j) for k in range(steps) for j in range(seg)]
        b.add(v, f, smooth=True)
        a = e


def flange(b_f, b_bolt, pos, axis, r_pipe, gap=0.004):
    """A bolted pipe joint: two faces and a ring of bolts."""
    a = np.array(axis, float)
    a /= np.linalg.norm(a)
    R = r_pipe * (1.65 if r_pipe < 0.12 else 1.28)
    th = max(0.018, r_pipe * 0.22)
    p = np.asarray(pos, float)
    prof = [(r_pipe * 1.03, -th * 1.9), (R * 0.72, -th), (R, -th + 0.002), (R, -gap), (R * 0.97, 0.0), (R * 0.97, 0.0), (R, gap), (R, th - 0.002), (R * 0.72, th), (r_pipe * 1.03, th * 1.9)]
    lathe(b_f, p, a, prof, 40)
    m = frame_of(a)
    nb = max(6, int(R * 70) // 2 * 2)
    for i in range(nb):
        ang = 2 * math.pi * i / nb
        c = p + m @ np.array([math.cos(ang), math.sin(ang), 0.0]) * (R * 0.84)
        rb = max(0.0055, R * 0.055)
        cyl(b_bolt, c - a * (th + rb * 1.6), c + a * (th + rb * 1.6), rb, 6, caps=True)


def i_beam(b, p0, p1, depth, width, web=None, flange_t=None, up=(0, 0, 1)):
    """An I-section between two points, its web in the plane of up."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.linalg.norm(p1 - p0)
    x = (p1 - p0) / L
    z = np.asarray(up, float) - x * np.dot(up, x)
    z /= np.linalg.norm(z)
    y = np.cross(z, x)
    rot = np.column_stack([x, y, z])
    c = (p0 + p1) / 2
    web = web or depth * 0.05
    ft = flange_t or depth * 0.08
    box(b, c, (L / 2, web / 2, depth / 2 - ft), rot=rot, ch=0.001)
    box(b, c + z * (depth / 2 - ft / 2), (L / 2, width / 2, ft / 2), rot=rot, ch=0.002)
    box(b, c - z * (depth / 2 - ft / 2), (L / 2, width / 2, ft / 2), rot=rot, ch=0.002)


def rot_between(p0, p1, up=(0, 0, 1)):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    x = (p1 - p0) / np.linalg.norm(p1 - p0)
    z = np.asarray(up, float) - x * np.dot(up, x)
    if np.linalg.norm(z) < 1e-6:
        z = np.array((0, 1.0, 0))
    z /= np.linalg.norm(z)
    return np.column_stack([x, np.cross(z, x), z]), (p0 + p1) / 2, np.linalg.norm(p1 - p0)


def beam_box(b, p0, p1, sy, sz, ch=0.002, up=(0, 0, 1)):
    rot, c, L = rot_between(p0, p1, up)
    box(b, c, (L / 2, sy, sz), rot=rot, ch=ch)


def capsule(b, pos, axis, r, half, seg=28):
    """Same envelope as the record's capsule: a cylinder of half length `half` with round ends."""
    a = np.array(axis, float)
    a /= np.linalg.norm(a)
    prof = [(r * math.sin(u), -half - r * math.cos(u)) for u in np.linspace(0.05, math.pi / 2, 7)]
    prof += [(r * math.cos(u), half + r * math.sin(u)) for u in np.linspace(0.0, math.pi / 2 - 0.05, 7)]
    lathe(b, pos, a, prof, seg)


# ---------------------------------------------------------------- the plant

class Plant:
    def __init__(self, rec):
        self.rec = rec
        self.coll = bpy.context.scene.collection
        self.mats = make_materials()
        self.solid = {}
        self.visual = {}
        self.manifest = []
        self.visual_boxes = []

    def S(self, mat):
        return self.solid.setdefault(mat, Batch())

    def V(self, mat):
        return self.visual.setdefault(mat, Batch())

    # ---- physics solids, exactly as in the record

    def solids(self):
        for s in self.rec.solids:
            if s["material"] == "wet":
                continue  # A water film drawn in the floor shader, from these same circles.
            b = self.S(s["material"])
            n0 = len(b.v)
            q, pos, size = s["quat"], s["pos"], s["size"]
            axis = qmat(q) @ np.array((0, 0, 1.0))
            if s["type"] == "box":
                box(b, pos, size, q, ch=0.003)
            elif s["type"] == "cylinder":
                cyl(b, np.array(pos) - axis * size[1], np.array(pos) + axis * size[1], size[0], 40, ch=0.002)
            elif s["type"] == "capsule":
                capsule(b, pos, axis, size[0], size[1], 40)
            else:
                raise SystemExit("unknown solid type " + s["type"])
            v = np.vstack(b.v[n0:])
            self.manifest.append({"name": s["name"], "material": s["material"], "min": v.min(axis=0).tolist(), "max": v.max(axis=0).tolist()})

    # ---- detail on the physics objects, visual only

    def object_detail(self):
        for o in self.rec.world["objects"]:
            if o["kind"] == "grating":
                self.grating(o)
            elif o["kind"] == "ramp":
                self.ramp(o)
            elif o["kind"] == "pipe":
                self.pipe_ends(o)
            elif o["kind"] == "cable_tray":
                self.tray_detail(o)

    def grating(self, o):
        c, s = math.cos(math.radians(o.get("yaw_deg", 0))), math.sin(math.radians(o.get("yaw_deg", 0)))
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        L, W = o["length"], o["width"]
        at = lambda lx, ly, z: np.array((o["x"] + c * lx - s * ly, o["y"] + s * lx + c * ly, z))
        bar_z = o.get("bar_height", 0.02)
        g = self.V("galvanised")
        # Fine bearing bars between the recorded bars, lower than them, then cross rods and a frame. The tray under them is dark.
        pitch = o.get("pitch", 0.15)
        for i in range(int(L / pitch * 4) + 1):
            if i % 4 == 0:
                continue
            box(g, at(0.015 + i * pitch / 4, 0, bar_z * 0.42), (0.0025, W / 2, bar_z * 0.42), rot=rot, ch=0.0005)
        for j in range(int(W / 0.1) + 1):
            box(g, at(L / 2, -W / 2 + j * 0.1, bar_z * 0.36), (L / 2, 0.003, 0.003), rot=rot, ch=0.0008)
        box(self.V("dark_steel"), at(L / 2, 0, 0.0008), (L / 2 + 0.02, W / 2 + 0.02, 0.0008), rot=rot, ch=0.0)
        for ly in (-W / 2, W / 2):
            box(g, at(L / 2, ly, bar_z * 0.5), (L / 2 + 0.03, 0.022, bar_z * 0.5), rot=rot)
        for lx in (-0.01, L + 0.01):
            box(g, at(lx, 0, bar_z * 0.5), (0.022, W / 2 + 0.03, bar_z * 0.5), rot=rot)

    def ramp(self, o):
        c, s = math.cos(math.radians(o.get("yaw_deg", 0))), math.sin(math.radians(o.get("yaw_deg", 0)))
        L = 2 * o["length"] + o.get("landing", 1.0)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        for lx in (-0.1, L + 0.1):
            p = (o["x"] + c * lx, o["y"] + s * lx, 0.0012)
            box(self.V("hazard"), p, (0.1, o["width"] / 2, 0.0012), rot=rot, ch=0.0)

    def pipe_ends(self, o):
        # Pipes do not end in mid air: visual runs carry a low pipe on past the walkway, one up to the rack and one into the floor.
        if o.get("clearance", 0.05) > 1.0:
            return
        c, s = math.cos(math.radians(o.get("yaw_deg", 0))), math.sin(math.radians(o.get("yaw_deg", 0)))
        z = o.get("clearance", 0.05) + o["radius"]
        half = o["length"] / 2
        dy = np.array((-s, c, 0.0))
        base = np.array((o["x"], o["y"], z))
        if o["radius"] >= 0.03:
            for side in (-1, 1):
                p = base + dy * side * o["length"] * 0.3
                flange_bolts(self.V("bolt"), p, dy, o["radius"] * 1.5, 0.02)
                for d_ in (-1, 1):
                    lathe(self.V("flange"), p + dy * d_ * 0.02, dy * d_, [(o["radius"] * 1.22, 0.0), (o["radius"] * 1.02, 0.05)], 32, caps=False)
        b = self.V("pipe_paint")
        tube(b, [base - dy * (half - 0.01), base - dy * (half + 0.9), base - dy * (half + 0.9) + np.array((0, 0, 3.6))], o["radius"])
        tube(b, [base + dy * (half - 0.01), base + dy * (half + 0.8), base + dy * (half + 0.8) - np.array((0, 0, z + 0.05))], o["radius"])
        if o["radius"] >= 0.03:
            flange(self.V("flange"), self.V("bolt"), base - dy * (half + 0.45), dy, o["radius"])
            flange(self.V("flange"), self.V("bolt"), base + dy * (half + 0.45), dy, o["radius"])
            lathe(self.V("flange"), base + dy * (half + 0.8) - np.array((0, 0, z)), (0, 0, 1), [(o["radius"] * 2.1, 0.0), (o["radius"] * 2.1, 0.02), (o["radius"] * 1.1, 0.04)], 32)

    def tray_detail(self, o):
        # Loose cable ends and a torn bracket at the tray. Visual only: flat on the floor and thin.
        c, s = math.cos(math.radians(o.get("yaw_deg", 0))), math.sin(math.radians(o.get("yaw_deg", 0)))
        L = o["length"] / 2
        at = lambda lx, ly, z: np.array((o["x"] + c * lx - s * ly, o["y"] + s * lx + c * ly, z))
        r = self.V("rubber")
        tube(r, [at(-0.08, L - 0.05, 0.03), at(-0.09, L + 0.25, 0.018), at(-0.22, L + 0.5, 0.013)], 0.013, 0.07, 12)
        tube(r, [at(0.0, L - 0.05, 0.03), at(0.05, L + 0.2, 0.018), at(0.21, L + 0.36, 0.013)], 0.013, 0.06, 12)
        tube(r, [at(0.08, -L + 0.05, 0.03), at(0.1, -L - 0.2, 0.018), at(0.02, -L - 0.42, 0.013)], 0.013, 0.06, 12)

    # ---- the record's scenery, kept where the record puts it

    def scenery(self):
        for o in self.rec.world["scenery"]:
            getattr(self, "s_" + o["kind"])(o)

    def s_floor_line(self, o):
        pass  # In the floor mask.

    def s_wall(self, o):
        a, b_ = np.array((o["x0"], o["y0"], 0.0)), np.array((o["x1"], o["y1"], 0.0))
        h = o.get("height", 7.0)
        d = b_ - a
        L = np.linalg.norm(d)
        x = d / L
        centre = (a + b_) / 2
        inward = np.array((6.0, 0.0, 0.0)) - centre
        n = np.cross((0, 0, 1.0), x)
        if np.dot(n, inward) < 0:
            n = -n
        rot = np.column_stack([x, np.cross((0, 0, 1.0), x), (0, 0, 1.0)])
        box(self.V("wall_concrete"), centre + np.array((0, 0, 0.6)), (L / 2, 0.14, 0.6), rot=rot, ch=0.01)
        # Trapezoid sheet: 0.3 m ribs, real geometry from the plinth to the eaves, on the inner face.
        pitch = 0.3
        ribs = int(L / pitch)
        prof = []
        for i in range(ribs):
            u = i * pitch
            prof += [(u, 0.0), (u + 0.11, 0.0), (u + 0.15, 0.035), (u + 0.26, 0.035)]
        prof.append((ribs * pitch, 0.0))
        z0, z1 = 1.16, h + 0.15
        verts, faces = [], []
        for u, dz in prof:
            p = a + x * u + n * (0.1 + dz)
            verts += [p + np.array((0, 0, z0)), p + np.array((0, 0, z1))]
        for i in range(len(prof) - 1):
            faces.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
        self.V("cladding").add(np.array(verts), faces)
        # Laps between sheets, every 3 m up the wall.
        for z in (3.6, 6.6):
            box(self.V("flashing"), centre + n * 0.148 + np.array((0, 0, z)), (L / 2, 0.006, 0.012), rot=rot)
        # Clerestory: translucent sheets in the top of the wall, every second bay.
        for k in range(int(L / 5.0)):
            if k % 2 == 0:
                continue
            u = (k + 0.5) * 5.0
            c = a + x * u + n * 0.152 + np.array((0, 0, 6.95))
            box(self.V("glow_day_soft"), c, (1.9, 0.004, 0.42), rot=rot, ch=0.0)
            for side in (-1, 1):
                box(self.V("dark_steel"), c + x * side * 1.92, (0.02, 0.01, 0.44), rot=rot)
            for side in (-1, 1):
                box(self.V("dark_steel"), c + np.array((0, 0, side * 0.43)), (1.94, 0.01, 0.018), rot=rot)
        # Gable infill up to the roof, so the far wall closes.
        if abs(x[1]) > 0.5:
            v = np.array([(a[0], -10.0, h), (a[0], 0.0, 9.45), (a[0], 10.0, h)])
            self.V("cladding").add(v + n * 0.12, [(0, 1, 2)])

    def s_column(self, o):
        h = o["height"]
        x, y = o["x"], o["y"]
        b = self.V("column")
        box(b, (x, y, h / 2), (0.014, 0.15, h / 2))
        box(b, (x - 0.15, y, h / 2), (0.012, 0.15, h / 2))
        box(b, (x + 0.15, y, h / 2), (0.012, 0.15, h / 2))
        box(self.V("dark_steel"), (x, y, 0.02), (0.26, 0.26, 0.02), ch=0.004)
        for dx in (-0.2, 0.2):
            for dy in (-0.2, 0.2):
                cyl(self.V("bolt"), (x + dx, y + dy, 0.0), (x + dx, y + dy, 0.08), 0.012, 8)
                lathe(self.V("bolt"), (x + dx, y + dy, 0.04), (0, 0, 1), [(0.024, 0.0), (0.024, 0.016), (0.017, 0.02)], 6, smooth=False)

    def s_beam(self, o):
        # The record's beam is the bottom chord. A truss above it holds the roof.
        x = o["x0"]
        z = o["height"]
        c = self.V("column")
        i_beam(c, (o["x0"], o["y0"], z), (o["x1"], o["y1"], z), 0.44, 0.18)
        top = lambda y: 8.12 + (1 - abs(y) / 10.0) * 1.25
        for s in (-1, 1):
            i_beam(c, (x, s * 10.0, top(10.0)), (x, 0.0, top(0.0)), 0.2, 0.12)
        ys = np.arange(-10.0, 10.01, 2.0)
        for k in range(len(ys) - 1):
            y0, y1 = ys[k], ys[k + 1]
            a, b = (x, y0, z + 0.2), (x, y1, top(y1) - 0.1)
            if k % 2:
                a, b = (x, y0, top(y0) - 0.1), (x, y1, z + 0.2)
            beam_box(c, a, b, 0.05, 0.03)
            beam_box(c, (x, y0, z + 0.2), (x, y0, top(y0) - 0.1), 0.04, 0.03, up=(0, 1, 0))
        self.ensure_roof()

    def ensure_roof(self):
        if getattr(self, "_roof", False):
            return
        self._roof = True
        top = lambda y: 8.12 + (1 - abs(y) / 10.0) * 1.25
        r = self.V("roof")
        for y0, y1 in ((-10.0, 0.0), (0.0, 10.0)):
            r.add([(-5.0, y0, top(y0) + 0.11), (17.0, y0, top(y0) + 0.11), (17.0, y1, top(y1) + 0.11), (-5.0, y1, top(y1) + 0.11)], [(0, 1, 2, 3)])
        for y in np.arange(-9.0, 9.1, 1.5):
            beam_box(self.V("dark_steel"), (-5.0, y, top(y) + 0.04), (17.0, y, top(y) + 0.04), 0.03, 0.06)
        for xc in (-0.5, 4.5, 9.5, 14.5):
            for ya, yb in ((-8.2, -1.5), (1.5, 8.2)):
                self.V("glow_day").add([(xc - 0.8, ya, top(ya) + 0.09), (xc + 0.8, ya, top(ya) + 0.09), (xc + 0.8, yb, top(yb) + 0.09), (xc - 0.8, yb, top(yb) + 0.09)], [(0, 1, 2, 3)])
        for x in (-3.0, 2.0, 7.0, 12.0):
            beam_box(self.V("dark_steel"), (x, -10.0, 7.82), (x + 5.0, -5.0, 7.82), 0.01, 0.01)

    def s_light(self, o):
        x, y, z = o["x"], o["y"], o["height"]
        lathe(self.V("lamp_body"), (x, y, z), (0, 0, 1), [(0.26, 0.0), (0.27, 0.005), (0.23, 0.12), (0.12, 0.2), (0.09, 0.32), (0.09, 0.32), (0.05, 0.34)], 40)
        lathe(self.V("glow_lamp"), (x, y, z - 0.005), (0, 0, 1), [(0.0, -0.01), (0.25, 0.0)], 40, caps=False)
        cyl(self.V("lamp_body"), (x, y, z + 0.34), (x, y, 7.36), 0.012, 8)
        box(self.V("rubber"), (x + 0.03, y, z + 1.0), (0.004, 0.004, 0.66))
        self.add_highbay(x, y, z)

    def add_highbay(self, x, y, z):
        lt = bpy.data.lights.new("visual_highbay", "AREA")
        lt.shape = "DISK"
        lt.size = 0.44
        lt.energy = HIGHBAY_W
        lt.color = (1.0, 0.86, 0.69)
        lt.use_shadow = True
        ob = bpy.data.objects.new("visual_highbay", lt)
        ob.location = (x, y, z - 0.03)
        self.coll.objects.link(ob)

    def s_railing(self, o):
        a = np.array((o["x0"], o["y0"], 0.0))
        b_ = np.array((o["x1"], o["y1"], 0.0))
        d = b_ - a
        L = np.linalg.norm(d)
        x = d / L
        y = self.V("rail")
        cyl(y, a + (0, 0, 1.08), b_ + (0, 0, 1.08), 0.0215, 16)
        cyl(y, a + (0, 0, 0.58), b_ + (0, 0, 0.58), 0.0165, 16)
        rot = np.column_stack([x, np.cross((0, 0, 1.0), x), (0, 0, 1.0)])
        box(self.V("toe_board"), (a + b_) / 2 + np.array((0, 0, 0.05)), (L / 2, 0.005, 0.05), rot=rot, ch=0.001)
        count = int(L / 1.5) + 1
        for i in range(count + 1):
            p = a + x * (i * L / count)
            cyl(y, p, p + np.array((0, 0, 1.08)), 0.0215, 16)
            lathe(y, p + np.array((0, 0, 1.08)), (0, 0, 1), [(0.0, 0.03), (0.024, 0.024), (0.028, 0.0), (0.028, -0.03), (0.0215, -0.04)], 16, caps=False)
            box(self.V("dark_steel"), p + np.array((0, 0, 0.005)), (0.05, 0.05, 0.005))
            lathe(y, p + np.array((0, 0, 0.58)), (0, 0, 1), [(0.024, -0.03), (0.026, 0.0), (0.024, 0.03)], 16, caps=False)

    def s_tank(self, o):
        r, h, x, y = o["radius"], o.get("height", 3.5), o["x"], o["y"]
        legs = min(0.6, h * 0.2)
        body = h - legs
        z0, z1 = legs, h
        head = r * 0.55
        prof = []
        for u in np.linspace(0, math.pi / 2, 12):
            prof.append((r * math.sin(u) + 1e-4, z0 + head * (1 - math.cos(u))))
        for u in np.linspace(math.pi / 2, 0, 12):
            prof.append((r * math.sin(u) + 1e-4, z1 - head * (1 - math.cos(u))))
        t = self.V("tank")
        lathe(t, (x, y, 0), (0, 0, 1), prof, 96, caps=False)
        # Bands as in the record, and girth welds.
        half = max(body / 2 - r, 0.01)
        zc = legs + body / 2
        for level in (-0.6, 0.0, 0.6):
            lathe(self.V("flange"), (x, y, zc + level * half), (0, 0, 1), [(r, -0.03), (r + 0.012, -0.028), (r + 0.012, 0.028), (r, 0.03)], 96, caps=False)
        for zw in (z0 + head, z1 - head):
            lathe(t, (x, y, zw), (0, 0, 1), [(r, -0.012), (r + 0.004, 0.0), (r, 0.012)], 96, caps=False)
        # Legs, as in the record's positions, carried up to the shell.
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            lx, ly = x + dx * r * 0.7, y + dy * r * 0.7
            box(self.V("dark_steel"), (lx, ly, (legs + 0.5 * head) / 2 + 0.05), (0.06, 0.06, (legs + 0.5 * head) / 2 + 0.05), ch=0.004)
            box(self.V("dark_steel"), (lx, ly, 0.012), (0.14, 0.14, 0.012), ch=0.003)
        ladder_y = y - r - 0.12
        g = self.V("galvanised")
        for side in (-0.2, 0.2):
            cyl(g, (x + side, ladder_y, legs), (x + side, ladder_y, h), 0.016, 12)
        for i in range(int(body / 0.3)):
            cyl(g, (x - 0.2, ladder_y, legs + 0.2 + i * 0.3), (x + 0.2, ladder_y, legs + 0.2 + i * 0.3), 0.011, 8)
        # Safety cage above reach.
        for zh in np.arange(legs + 1.9, h, 0.75):
            ang = np.linspace(-0.1, math.pi + 0.1, 15)
            pts = [np.array((x + 0.38 * math.cos(u), ladder_y - 0.32 * math.sin(u), zh)) for u in ang]
            for p, q in zip(pts[:-1], pts[1:]):
                beam_box(g, p, q, 0.012, 0.004)
        # Nozzle as in the record, then a pipe down and away.
        n = np.array((x + r * 0.8, y - r * 0.8, legs + body * 0.35))
        out = np.array((math.sqrt(0.5), -math.sqrt(0.5), 0.0))
        tube(self.V("pipe_paint"), [n - out * 0.2, n + out * 0.55, n + out * 0.55 + np.array((0, 0, -(n[2] - 0.32))), n + out * 1.1 + np.array((0, 0, -(n[2] - 0.32)))], 0.055)
        flange(self.V("flange"), self.V("bolt"), n + out * 0.22, out, 0.055)
        # Manway with a bolted cover, facing the walkway side.
        mw = np.array((x - r * math.sin(0.5), y - r * math.cos(0.5), legs + head + 0.75))
        mo = np.array((-math.sin(0.5), -math.cos(0.5), 0.0))
        lathe(t, mw - mo * 0.02, mo, [(0.27, 0.0), (0.27, 0.2)], 40, caps=False)
        flange(self.V("flange"), self.V("bolt"), mw + mo * 0.2, mo, 0.26)
        # Top nozzle and level bridle.
        cyl(self.V("pipe_paint"), (x, y, h - 0.02), (x, y, h + 0.35), 0.05, 20)
        flange(self.V("flange"), self.V("bolt"), (x, y, h + 0.22), (0, 0, 1), 0.05)
        bx = x - r - 0.09
        cyl(self.V("steel"), (bx, y, legs + 0.6), (bx, y, h - 0.8), 0.022, 12)
        for zb in (legs + 0.75, h - 0.95):
            cyl(self.V("steel"), (x - r + 0.01, y, zb), (bx, y, zb), 0.016, 10)

    def s_pipe_rack(self, o):
        a = np.array((o["x0"], o["y0"], o["height"]))
        b_ = np.array((o["x1"], o["y1"], o["height"]))
        d = b_ - a
        L = np.linalg.norm(d)
        x = d / L
        side = np.cross((0, 0, 1.0), x)
        centre = (a + b_) / 2
        half = L / 2
        for j, (offset, r, mat) in enumerate(((-0.42, 0.11, "clad_pipe"), (0.0, 0.07, "pipe_paint"), (0.34, 0.05, "steel"))):
            c = centre + side * offset
            cyl(self.V(mat), c - x * half, c + x * half, r, 32)
            for k in range(int(half // 2.0) + 1):
                for sign in (-1, 1):
                    off = sign * (k * 2.0 + 0.7 + j * 0.3)
                    if abs(off) < half - 0.1:
                        if mat == "clad_pipe":
                            lathe(self.V("flange"), c + x * off, x, [(r + 0.002, -0.012), (r + 0.006, -0.01), (r + 0.006, 0.01), (r + 0.002, 0.012)], 32, caps=False)
                        else:
                            flange(self.V("flange"), self.V("bolt"), c + x * off, x, r)
        # Two more lines above the record's three: visual only.
        for offset, r, mat in ((0.62, 0.035, "pipe_green"), (-0.72, 0.03, "pipe_paint")):
            c = centre + side * offset
            cyl(self.V(mat), c - x * half, c + x * half, r, 16)
        for k in range(int(half // 2.5) + 1):
            for sign in (-1, 1):
                p = centre + x * sign * k * 2.5 + np.array((0, 0, -0.16))
                if abs(sign * k * 2.5) > half:
                    continue
                beam_box(self.V("dark_steel"), p - side * 0.82, p + side * 0.82, 0.03, 0.025, ch=0.003)
                for off in (-0.5, 0.5):
                    rod = p + side * off
                    cyl(self.V("dark_steel"), rod, rod + np.array((0, 0, 7.5 - rod[2])), 0.012, 8)

    def s_gauge(self, o):
        x, y = o["x"], o["y"]
        box(self.V("column"), (x, y, 0.6), (0.025, 0.025, 0.6), ch=0.003)
        box(self.V("dark_steel"), (x, y, 0.006), (0.09, 0.09, 0.006))
        lathe(self.V("flange"), (x, y - 0.025, 1.2), (0, -1, 0), [(0.09, 0.0), (0.092, 0.002), (0.092, 0.045), (0.08, 0.05)], 40)
        lathe(self.V("dial"), (x, y - 0.075, 1.2), (0, -1, 0), [(0.0, 0.0), (0.08, 0.0)], 40, caps=False)
        for k in range(21):
            a = math.radians(225 - 13.5 * k)
            ln = 0.012 if k % 5 == 0 else 0.007
            p = np.array((x + math.cos(a) * (0.07 - ln / 2), y - 0.0755, 1.2 + math.sin(a) * (0.07 - ln / 2)))
            rot = frame_of((math.cos(a), 0, math.sin(a)))
            box(self.V("ink"), p, (0.0012, 0.0005, ln / 2), rot=rot, ch=0.0)
        a = math.radians(115)
        p = np.array((x + math.cos(a) * 0.03, y - 0.077, 1.2 + math.sin(a) * 0.03))
        box(self.V("needle"), p, (0.0014, 0.0006, 0.04), rot=frame_of((math.cos(a), 0, math.sin(a))), ch=0.0)
        tube(self.V("steel"), [(x, y + 0.03, 1.15), (x, y + 0.12, 1.15), (x, y + 0.12, 0.05)], 0.008, 0.03, 8)

    def s_pump(self, o):
        a = math.radians(o.get("yaw_deg", 0.0))
        c, s = math.cos(a), math.sin(a)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        at = lambda along, z, side=0.0: np.array((o["x"] + c * along - s * side, o["y"] + s * along + c * side, z))
        axis = np.array((c, s, 0.0))
        box(self.V("dark_steel"), at(0.0, 0.08), (0.8, 0.3, 0.08), rot=rot, ch=0.006)
        for sx in (-0.72, 0.72):
            for sy in (-0.24, 0.24):
                cyl(self.V("bolt"), at(sx, 0.16, sy), at(sx, 0.19, sy), 0.012, 6)
        # Motor: finned barrel on the record's axis and position.
        m = self.V("motor")
        prof = [(0.0, -0.36), (0.17, -0.36), (0.2, -0.33)]
        for k in range(16):
            z = -0.3 + k * 0.038
            prof += [(0.183, z), (0.2, z + 0.008), (0.2, z + 0.022), (0.183, z + 0.03)]
        prof += [(0.2, 0.32), (0.17, 0.36), (0.0, 0.36)]
        lathe(m, at(-0.35, 0.42), axis, prof, 48, smooth=True, caps=False)
        box(m, at(-0.35, 0.65), (0.09, 0.08, 0.05), rot=rot, ch=0.004)
        box(m, at(-0.35, 0.2), (0.2, 0.18, 0.05), rot=rot, ch=0.004)
        # Coupling guard in safety yellow, where the record has the coupling.
        lathe(self.V("guard"), at(0.08, 0.42), axis, [(0.0, -0.09), (0.1, -0.09), (0.11, -0.08), (0.11, 0.08), (0.1, 0.09), (0.0, 0.09)], 28)
        box(self.V("flange"), at(0.08, 0.2), (0.07, 0.1, 0.12), rot=rot)
        # Volute and nozzles at the record's body.
        v = self.V("valve_body")
        lathe(v, at(0.42, 0.42), axis, [(0.0, -0.1), (0.14, -0.1), (0.22, -0.05), (0.22, 0.05), (0.14, 0.1), (0.06, 0.16), (0.06, 0.2)], 40)
        cyl(self.V("pipe_paint"), at(0.42, 0.55), at(0.42, 1.25), 0.05, 20)
        flange(self.V("flange"), self.V("bolt"), at(0.42, 0.68), (0, 0, 1), 0.05)
        tube(self.V("pipe_paint"), [at(0.42, 1.2), at(0.42, 1.55), at(0.42, 1.55, -2.0), at(0.42, 0.62, -2.0)], 0.05)
        tube(self.V("pipe_paint"), [at(0.62, 0.42), at(1.0, 0.42), at(1.0, 0.42, -1.7)], 0.065)
        flange(self.V("flange"), self.V("bolt"), at(0.8, 0.42), axis, 0.065)
        lathe(self.V("flange"), at(0.42, 1.0), (0, 0, 1), [(0.05, -0.06), (0.1, -0.05), (0.1, 0.05), (0.05, 0.06)], 24, caps=False)
        wheel(self.V("handwheel"), at(0.42, 1.0) + np.array((0, 0, 0.26)), (0, 0, 1), 0.1)
        cyl(self.V("steel"), at(0.42, 1.0), at(0.42, 1.28), 0.012, 8)
        box(self.V("drip_tray"), at(0.0, 0.004), (0.95, 0.45, 0.004), rot=rot, ch=0.002)

    # ---- scenery that is not in the record: visual only. Kept off the walkway; the check measures that.

    def mark(self, kind, a, b):
        self.visual_boxes.append({"kind": kind, "min": np.minimum(a, b).tolist(), "max": np.maximum(a, b).tolist()})

    def extras(self):
        self.rack_frames()
        self.low_headers()
        self.heat_exchanger((-0.4, 3.45))
        self.cable_trays()
        self.mcc_row()
        self.drums((-3.3, 3.2), 6)
        self.drums((14.6, -0.3), 4)
        self.bulkheads()
        self.safety_items()
        self.signs()
        self.leak_source()

    def rack_frames(self):
        c = self.V("column")
        for x in (-3.0, 2.0, 7.0, 12.0):
            for y in (-1.98, -3.25):
                i_beam(c, (x, y, 0.0), (x, y, 4.02), 0.2, 0.2, up=(1, 0, 0))
                box(self.V("dark_steel"), (x, y, 0.012), (0.17, 0.17, 0.012), ch=0.003)
                self.mark("rack_column", (x - 0.15, y - 0.15, 0), (x + 0.15, y + 0.15, 4.0))
            i_beam(c, (x, -1.88, 4.02), (x, -3.35, 4.02), 0.18, 0.1)
            beam_box(self.V("dark_steel"), (x, -1.98, 3.2), (x, -3.25, 3.2), 0.015, 0.03)

    def low_headers(self):
        # Two low lines beside the walkway: the eye-level pipework. On sleepers, with flanges and gate valves.
        for y, z, r, mat, x0, x1 in ((-2.35, 0.42, 0.075, "pipe_paint", -4.9, 16.9), (-2.85, 0.62, 0.11, "clad_pipe", -4.9, 16.9)):
            cyl(self.V(mat), (x0, y, z), (x1, y, z), r, 32)
            self.mark("header", (x0, y - r, z - r), (x1, y + r, z + r))
            for x in np.arange(-4.0, 16.5, 3.0):
                beam_box(self.V("dark_steel"), (x, y, 0.0), (x, y, z - r), 0.05, 0.05, up=(1, 0, 0))
                box(self.V("dark_steel"), (x, y, z - r - 0.008), (0.05, 0.1, 0.008), ch=0.002)
                box(self.V("dark_steel"), (x, y, 0.008), (0.1, 0.1, 0.008), ch=0.002)
            for x in np.arange(-3.3, 16.5, 5.0 if r < 0.1 else 4.0):
                if mat == "clad_pipe":
                    lathe(self.V("flange"), (x, y, z), (1, 0, 0), [(r + 0.002, -0.012), (r + 0.006, -0.01), (r + 0.006, 0.01), (r + 0.002, 0.012)], 32, caps=False)
                else:
                    flange(self.V("flange"), self.V("bolt"), (x, y, z), (1, 0, 0), r)
        for x, handed in ((0.6, 1), (6.2, -1), (11.4, 1)):
            self.gate_valve((x, -2.35, 0.42), (1, 0, 0), 0.075)
        # Risers from the header to the rack.
        for x in (-1.2, 4.3, 9.7, 14.2):
            tube(self.V("pipe_paint"), [(x, -2.35, 0.5), (x, -2.35, 3.2), (x, -2.6, 3.7), (x, -2.6, 4.13)], 0.05, 0.12)
            flange(self.V("flange"), self.V("bolt"), (x, -2.35, 1.5), (0, 0, 1), 0.05)

    def gate_valve(self, pos, axis, r):
        p = np.array(pos, float)
        ax = np.array(axis, float)
        v = self.V("valve_body")
        flange(self.V("flange"), self.V("bolt"), p - ax * r * 1.6, ax, r)
        flange(self.V("flange"), self.V("bolt"), p + ax * r * 1.6, ax, r)
        lathe(v, p, ax, [(r * 1.05, -r * 1.5), (r * 1.3, -r * 0.8), (r * 1.3, r * 0.8), (r * 1.05, r * 1.5)], 28, caps=False)
        lathe(v, p, (0, 0, 1), [(r * 0.95, 0.0), (r * 0.85, r * 2.2), (r * 1.1, r * 2.3), (r * 1.1, r * 2.5), (r * 0.5, r * 2.6), (r * 0.25, r * 3.2)], 24)
        cyl(self.V("steel"), p + (0, 0, r * 2.5), p + (0, 0, r * 5.2), r * 0.17, 10)
        wheel(self.V("handwheel"), p + (0, 0, r * 4.4), (0, 0, 1), r * 1.65)

    def heat_exchanger(self, c):
        x, y = c
        r, L, z = 0.42, 3.4, 0.92
        t = self.V("tank")
        lathe(t, (x, y, z), (1, 0, 0), [(0.0, -L / 2 - 0.18), (r * 0.6, -L / 2 - 0.14), (r * 0.9, -L / 2 - 0.05), (r, -L / 2), (r, L / 2), (r * 0.9, L / 2 + 0.05), (r * 0.6, L / 2 + 0.14), (0.0, L / 2 + 0.18)], 64, caps=False)
        for s in (-1, 1):
            flange(self.V("flange"), self.V("bolt"), (x + s * L / 2, y, z), (1, 0, 0), r)
            box(self.V("column"), (x + s * L * 0.3, y, (z - r) / 2), (0.05, r * 0.8, (z - r) / 2 + 0.05), ch=0.004)
            box(self.V("dark_steel"), (x + s * L * 0.3, y, 0.012), (0.1, r * 0.9, 0.012), ch=0.003)
            tube(self.V("pipe_paint"), [(x + s * L * 0.42, y, z + r - 0.02), (x + s * L * 0.42, y, z + r + 0.3), (x + s * L * 0.42, y + 1.6 * s, z + r + 0.3), (x + s * L * 0.42, y + 1.6 * s, 5.0)], 0.05, 0.12)
            flange(self.V("flange"), self.V("bolt"), (x + s * L * 0.42, y, z + r + 0.1), (0, 0, 1), 0.05)
        self.mark("exchanger", (x - L / 2 - 0.2, y - r, 0), (x + L / 2 + 0.2, y + r, z + r))

    def cable_trays(self):
        # A ladder tray beside the walkway at 3.2 m on the rack columns, one on the north wall.
        for y, x0, x1, z in ((-1.98, -4.9, 16.9, 3.2), (9.55, -4.9, 16.9, 4.0), (-3.25, -4.9, 16.9, 2.9)):
            self.ladder_tray(x0, x1, y, z, 0.4)

    def ladder_tray(self, x0, x1, y, z, w):
        g = self.V("galvanised")
        for s in (-1, 1):
            box(g, ((x0 + x1) / 2, y + s * w / 2, z), ((x1 - x0) / 2, 0.003, 0.04), ch=0.001)
        for x in np.arange(x0, x1, 0.3):
            box(g, (x, y, z - 0.03), (0.012, w / 2, 0.006), ch=0.001)
        rng = np.random.default_rng(int(abs(y) * 100))
        for k in range(9):
            oy = rng.uniform(-w / 2 + 0.03, w / 2 - 0.03)
            cyl(self.V("rubber"), (x0, y + oy, z - 0.015 + 0.012 * (k % 3)), (x1, y + oy, z - 0.015 + 0.012 * (k % 3)), rng.uniform(0.006, 0.014), 8)

    def mcc_row(self):
        # Motor control cabinets, at the back of the south side. Invented tags.
        y = -4.6
        for i, x in enumerate(np.arange(7.0, 13.0, 0.95)):
            box(self.V("cabinet"), (x, y, 1.15), (0.46, 0.3, 1.05), ch=0.006)
            box(self.V("dark_steel"), (x, y, 0.05), (0.47, 0.31, 0.05), ch=0.003)
            box(self.V("cabinet"), (x, y + 0.305, 1.15), (0.43, 0.005, 1.0), ch=0.002)
            box(self.V("steel"), (x + 0.36, y + 0.32, 1.15), (0.012, 0.008, 0.08), ch=0.002)
            for row in range(4):
                box(self.V("rubber"), (x, y + 0.312, 0.5 + row * 0.03), (0.2, 0.002, 0.006), ch=0.0)
            for j, m in enumerate(("glow_green", "glow_amber", "glow_red")):
                on = (i + j) % 3 != 2
                cyl(self.V(m if on else "rubber"), (x - 0.2 + j * 0.06, y + 0.31, 1.8), (x - 0.2 + j * 0.06, y + 0.318, 1.8), 0.012, 12)
            sign(self.coll, self.mats, (x, y + 0.316, 1.98), (0, 1, 0), 0.3, 0.06, f"MCC-4{i + 1}", "plate")
            cyl(self.V("dark_steel"), (x, y, 2.2), (x, y, 2.9), 0.02, 8)
        self.mark("mcc", (6.5, y - 0.3, 0), (12.9, y + 0.32, 2.9))

    def drums(self, c, n):
        rng = np.random.default_rng(int(abs(c[0] * 10)))
        rows = [(i % 3, i // 3) for i in range(n)]
        box(self.V("pallet"), (c[0] + 0.6, c[1] + 0.3, 0.07), (1.05, 0.72, 0.07), ch=0.01)
        for (i, j) in rows:
            x, y = c[0] + i * 0.62, c[1] + j * 0.62
            prof = [(0.0, 0.0), (0.285, 0.0), (0.29, 0.015)]
            for z in (0.3, 0.6):
                prof += [(0.285, z - 0.02), (0.295, z), (0.285, z + 0.02)]
            prof += [(0.285, 0.875), (0.292, 0.885), (0.28, 0.885), (0.28, 0.87), (0.0, 0.87)]
            lathe(self.V("drum_blue" if rng.random() < 0.7 else "drum_grey"), (x, y, 0.14), (0, 0, 1), prof, 40, caps=False)
            self.mark("drum", (x - 0.3, y - 0.3, 0), (x + 0.3, y + 0.3, 1.02))

    def bulkheads(self):
        for (x, y, n) in ((-2.0, 9.7, -1), (3.0, 9.7, -1), (10.0, 9.7, -1), (15.0, 9.7, -1), (-2.0, -9.7, 1), (5.0, -9.7, 1), (12.0, -9.7, 1)):
            box(self.V("lamp_body"), (x, y, 3.0), (0.32, 0.04, 0.07), ch=0.01)
            box(self.V("glow_lamp_soft"), (x, y + n * 0.042, 3.0), (0.29, 0.002, 0.05), ch=0.0)
        for (x, y) in ((16.7, -5.0), (16.7, 0.0), (16.7, 5.0), (-4.7, -5.0), (-4.7, 0.0), (-4.7, 5.0)):
            s = 1 if x < 0 else -1
            box(self.V("lamp_body"), (x, y, 3.0), (0.04, 0.32, 0.07), ch=0.01)
            box(self.V("glow_lamp_soft"), (x + s * 0.042, y, 3.0), (0.002, 0.29, 0.05), ch=0.0)

    def safety_items(self):
        # Extinguisher on a rack column; bollards at the corners, outside the rails.
        x, y = 2.15, -1.86
        lathe(self.V("extinguisher"), (x, y - 0.04, 0.32), (0, 0, 1), [(0.0, 0.0), (0.075, 0.0), (0.08, 0.02), (0.08, 0.44), (0.055, 0.5), (0.02, 0.53)], 32, caps=False)
        box(self.V("dark_steel"), (x, y - 0.04, 0.87), (0.03, 0.012, 0.018))
        tube(self.V("rubber"), [(x + 0.02, y - 0.04, 0.85), (x + 0.12, y - 0.04, 0.8), (x + 0.12, y - 0.04, 0.45)], 0.007, 0.04, 8)
        self.mark("extinguisher", (x - 0.09, y - 0.13, 0.3), (x + 0.15, y + 0.05, 0.9))
        for (bx, by) in ((6.95, -1.95), (3.05, 1.95), (14.25, 2.05), (14.25, 5.95)):
            lathe(self.V("guard"), (bx, by, 0.0), (0, 0, 1), [(0.0, 0.0), (0.06, 0.0), (0.06, 1.0), (0.05, 1.02), (0.0, 1.03)], 24, caps=False)
            box(self.V("dark_steel"), (bx, by, 0.006), (0.1, 0.1, 0.006))
            self.mark("bollard", (bx - 0.06, by - 0.06, 0), (bx + 0.06, by + 0.06, 1.03))

    def signs(self):
        # Invented wording, no brand. Plates on rails, columns and vessels.
        s = lambda *a: sign(self.coll, self.mats, *a)
        s((-1.6, -1.73, 0.82), (0, 1, 0), 0.44, 0.3, "CAUTION\nTRIP HAZARD", "yellow")
        s((1.2, 1.73, 0.82), (0, -1, 0), 0.44, 0.3, "EAR AND EYE\nPROTECTION", "blue")
        s((10.5, 2.27, 0.82), (0, 1, 0), 0.44, 0.3, "HOT SURFACE\nDO NOT TOUCH", "yellow")
        s((6.73, -0.6, 0.82), (-1, 0, 0), 0.44, 0.3, "AREA 4\nPUMP HOUSE", "white")
        s((3.27, 3.6, 0.82), (1, 0, 0), 0.44, 0.3, "CAUTION\nHOT PIPES", "yellow")
        s((9.1, 6.34, 2.05), (0, -1, 0.0), 0.5, 0.17, "V-101A", "white")
        s((12.8, 6.34, 2.05), (0, -1, 0.0), 0.5, 0.17, "V-101B", "white")
        s((1.0, 5.86, 1.75), (0, -1, 0.0), 0.44, 0.16, "V-102", "white")
        s((9.0, 0.28, 0.55), (0, -1, 0.0), 0.34, 0.1, "P-201A", "plate")
        s((12.4, 0.28, 0.55), (0, -1, 0.0), 0.34, 0.1, "P-201B", "plate")
        s((1.87, -1.82, 2.0), (0, 1, 0), 0.5, 0.34, "FIRE POINT 7", "red")

    def leak_source(self):
        # A weeping small-bore joint above each leak. Where the water comes from, as picture only.
        for o in self.rec.world["objects"]:
            if o["kind"] != "wet_patch":
                continue
            y = o["y"] - o["sy"] / 2 - 0.25
            y = min(y, -1.85)
            x = o["x"] - 0.4
            tube(self.V("pipe_green"), [(x - 1.2, y, 1.3), (x + 1.2, y, 1.3)], 0.03)
            flange(self.V("flange"), self.V("bolt"), (x, y, 1.3), (1, 0, 0), 0.03)
            for xs in (x - 1.1, x + 1.1):
                cyl(self.V("dark_steel"), (xs, y, 0.0), (xs, y, 1.27), 0.02, 8)
            lathe(self.V("water"), (x, y, 1.265), (0, 0, 1), [(0.0, -0.015), (0.006, -0.008), (0.003, 0.0)], 12, caps=False)

    def build(self):
        self.solids()
        self.object_detail()
        self.scenery()
        self.extras()
        for key, b in self.solid.items():
            b.build(f"solid_{key}", self.mats[key], False, self.coll)
        for key, b in self.visual.items():
            b.build(f"visual_{key}", self.mats[key], True, self.coll)


def flange_bolts(b, pos, axis, R, half):
    a = np.array(axis, float)
    m = frame_of(a)
    p = np.asarray(pos, float)
    nb = max(6, int(R * 70) // 2 * 2)
    for i in range(nb):
        ang = 2 * math.pi * i / nb
        c = p + m @ np.array([math.cos(ang), math.sin(ang), 0.0]) * (R * 0.8)
        rb = max(0.0055, R * 0.06)
        cyl(b, c - a * (half + rb * 1.6), c + a * (half + rb * 1.6), rb, 6, caps=True)


def wheel(b, pos, axis, r):
    """A handwheel: rim and three spokes."""
    p = np.asarray(pos, float)
    m = frame_of(axis)
    a = np.linspace(0, 2 * math.pi, 28, endpoint=False)
    t = r * 0.11
    prof = np.linspace(0, 2 * math.pi, 8, endpoint=False)
    rows = [np.array([(p + m @ np.array(((r + t * math.cos(u)) * math.cos(x), (r + t * math.cos(u)) * math.sin(x), t * math.sin(u)))) for u in prof]) for x in a]
    v = np.vstack(rows)
    f = [(i * 8 + j, i * 8 + (j + 1) % 8, ((i + 1) % 28) * 8 + (j + 1) % 8, ((i + 1) % 28) * 8 + j) for i in range(28) for j in range(8)]
    b.add(v, f, smooth=True)
    for x in (0.0, 2.1, 4.2):
        cyl(b, p, p + m @ np.array((math.cos(x), math.sin(x), 0.0)) * r, t * 0.75, 8, caps=False)
    cyl(b, p - m[:, 2] * t, p + m[:, 2] * t, t * 1.8, 12)


SIGN_STYLES = {"yellow": ((0.72, 0.5, 0.02), (0.01, 0.01, 0.01)), "blue": ((0.02, 0.1, 0.34), (0.8, 0.8, 0.8)), "white": ((0.75, 0.75, 0.72), (0.01, 0.01, 0.01)), "red": ((0.5, 0.02, 0.015), (0.85, 0.85, 0.85)), "plate": ((0.35, 0.35, 0.34), (0.01, 0.01, 0.01))}


def sign(coll, mats, pos, normal, w, h, text, style):
    """A plate with real letters. Invented wording only."""
    n = np.array(normal, float)
    n /= np.linalg.norm(n)
    right = np.cross((0, 0, 1.0), n)
    right /= np.linalg.norm(right)
    up = np.cross(n, right)
    rot = np.column_stack([right, n, up])
    b = Batch()
    box(b, np.asarray(pos), (w / 2, 0.002, h / 2), rot=rot, ch=0.0008)
    plate = mats["sign_" + style]
    b.build("visual_sign_plate", plate, True, coll)
    cu = bpy.data.curves.new("visual_sign_text", "FONT")
    cu.body = text
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    lines = text.count("\n") + 1
    cu.size = min(h * 0.62 / lines, w * 1.5 / max(len(t) for t in text.split("\n")))
    ob = bpy.data.objects.new("visual_sign_text", cu)
    ob["visual_only"] = True
    # Text lies in local xy, facing local +z.
    ob.matrix_world = Matrix(((right[0], up[0], n[0], pos[0] + n[0] * 0.0028), (right[1], up[1], n[1], pos[1] + n[1] * 0.0028), (right[2], up[2], n[2], pos[2] + n[2] * 0.0028), (0, 0, 0, 1)))
    cu.materials.append(mats["sign_ink_" + style])
    coll.objects.link(ob)


HIGHBAY_W = 520.0
DAY = (0.86, 0.93, 1.0)


def make_materials():
    M = {}
    M["concrete"] = surface("concrete", "Concrete034", 2.4, rough=0.85, bump=0.3, streak=0.3, wear=0.3)
    M["wall_concrete"] = surface("wall_concrete", "Concrete042A", 2.3, tint=(0.95, 0.93, 0.9), rough=0.9, bump=0.5, streak=0.7, grime=1.0, wear=0.6)
    M["cladding"] = surface("cladding", color=(0.2, 0.225, 0.22), rough=0.46, streak=0.8, rust=0.0, dust=0.12, grime=0.3, wear=0.4)
    M["flashing"] = surface("flashing", color=(0.14, 0.16, 0.16), rough=0.5, streak=0.3)
    M["roof"] = surface("roof", color=(0.075, 0.08, 0.085), rough=0.75, grime=0.0, wear=0.2)
    M["column"] = surface("column", color=(0.075, 0.105, 0.14), rough=0.42, rust=0.12, streak=0.4, wear=0.7)
    M["dark_steel"] = surface("dark_steel", color=(0.035, 0.037, 0.04), rough=0.5, rust=0.2, wear=0.7)
    M["steel"] = surface("steel", "Metal032", 0.8, tint=(0.75, 0.75, 0.74), metal=1.0, rough=0.42, rough_tex=0.5)
    M["galvanised"] = surface("galvanised", "Metal049A", 0.45, tint=(0.62, 0.63, 0.62), metal=1.0, rough=0.4, rough_tex=0.5, bump=0.05, dust=0.28, grime=0.7)
    M["plate"] = surface("plate", "DiamondPlate008A", 0.6, tint=(0.8, 0.8, 0.78), metal=1.0, rough=0.42, rough_tex=0.5, bump=1.0, dust=0.3)
    M["pipe_paint"] = surface("pipe_paint", color=(0.06, 0.115, 0.1), rough=0.4, rust=0.18, streak=0.35, wear=0.7)
    M["pipe_green"] = surface("pipe_green", color=(0.34, 0.25, 0.06), rough=0.42, rust=0.18, streak=0.3, wear=0.7)
    M["flange"] = surface("flange", color=(0.05, 0.075, 0.08), rough=0.42, rust=0.12, wear=0.45)
    M["bolt"] = surface("bolt", color=(0.36, 0.31, 0.24), metal=1.0, rough=0.5, rust=0.5, grime=0.0)
    M["clad_pipe"] = surface("clad_pipe", "Metal032", 1.6, tint=(0.82, 0.83, 0.84), metal=1.0, rough=0.34, rough_tex=0.5, dust=0.2, streak=0.3)
    M["tank"] = surface("tank", color=(0.42, 0.42, 0.38), rough=0.46, rust=0.1, streak=1.0, grime=0.8, wear=0.9)
    M["motor"] = surface("motor", color=(0.025, 0.09, 0.17), rough=0.36, rust=0.06, wear=0.6)
    M["valve_body"] = surface("valve_body", color=(0.03, 0.05, 0.09), rough=0.42, rust=0.2, wear=0.7)
    M["handwheel"] = surface("handwheel", color=(0.42, 0.035, 0.03), rough=0.4, rust=0.2, grime=0, wear=0.8)
    M["guard"] = surface("guard", color=(0.72, 0.48, 0.02), rough=0.42, rust=0.08, grime=0.8, dust=0.25)
    M["rail"] = surface("rail", color=(0.62, 0.38, 0.015), rough=0.38, rust=0.08, streak=0.25, grime=0.5, dust=0.2, wear=0.8)
    M["toe_board"] = surface("toe_board", color=(0.55, 0.34, 0.02), rough=0.45, rust=0.15, grime=1.0, dust=0.35, wear=0.8)
    M["rubber"] = surface("rubber", color=(0.012, 0.012, 0.013), rough=0.6, grime=0, dust=0.05, wear=0.0)
    M["cabinet"] = surface("cabinet", color=(0.42, 0.42, 0.38), rough=0.46, streak=0.4, rust=0.03, wear=0.5)
    M["pallet"] = surface("pallet", color=(0.25, 0.17, 0.09), rough=0.8, wear=0.0)
    M["drum_blue"] = surface("drum_blue", color=(0.02, 0.07, 0.2), rough=0.42, rust=0.3, streak=0.4, wear=0.9)
    M["drum_grey"] = surface("drum_grey", color=(0.2, 0.21, 0.21), rough=0.42, rust=0.35, streak=0.4, wear=0.9)
    M["extinguisher"] = surface("extinguisher", color=(0.45, 0.02, 0.015), rough=0.3, coat=0.5, grime=0, dust=0.05, wear=0.2)
    M["lamp_body"] = surface("lamp_body", color=(0.15, 0.16, 0.16), rough=0.5, grime=0, wear=0.3)
    M["dial"] = surface("dial", color=(0.8, 0.8, 0.78), rough=0.25, grime=0, dust=0)
    M["ink"] = surface("ink", color=(0.01, 0.01, 0.01), rough=0.5, grime=0, dust=0)
    M["needle"] = surface("needle", color=(0.5, 0.02, 0.01), rough=0.5, grime=0, dust=0)
    M["drip_tray"] = surface("drip_tray", color=(0.03, 0.03, 0.03), rough=0.25, metal=0.6, grime=0)
    M["hazard"] = hazard("hazard")
    M["glow_day"] = emission("glow_day", DAY, 7.0)
    M["glow_day_soft"] = emission("glow_day_soft", DAY, 2.2)
    M["glow_lamp"] = emission("glow_lamp", (1.0, 0.86, 0.69), 22.0)
    M["glow_lamp_soft"] = emission("glow_lamp_soft", (1.0, 0.9, 0.76), 9.0)
    M["glow_green"] = emission("glow_green", (0.05, 1.0, 0.15), 3.0)
    M["glow_amber"] = emission("glow_amber", (1.0, 0.5, 0.03), 3.0)
    M["glow_red"] = emission("glow_red", (1.0, 0.04, 0.02), 3.0)
    g = G("water")
    gp = g.principled()
    g.link(gp.inputs["Base Color"], (0.8, 0.82, 0.85))
    g.link(gp.inputs["Roughness"], 0.03)
    g.link(gp.inputs["Transmission Weight"], 1.0)
    g.link(gp.inputs["IOR"], 1.33)
    M["water"] = g.finish(gp.outputs[0])
    for key, (bg, fg) in SIGN_STYLES.items():
        M["sign_" + key] = surface("sign_" + key, color=bg, rough=0.42, grime=0, dust=0.1, streak=0.2)
        M["sign_ink_" + key] = surface("sign_ink_" + key, color=fg, rough=0.45, grime=0, dust=0)
    return M


# ---------------------------------------------------------------- the robot

def build_robot(rec, coll):
    """The real meshes from public/robots/anymal_c, one object per recorded body."""
    meta = json.loads((R.ROBOT / "robot.json").read_text())
    raw = (R.ROBOT / "robot.bin").read_bytes()
    nv, ni = meta["vertices"], meta["indices"]
    lay = meta["layout"]
    pos = np.frombuffer(raw, np.float32, nv * 3, lay["position"]).reshape(-1, 3)
    nor = np.frombuffer(raw, np.int8, nv * 4, lay["normal"]).reshape(-1, 4)[:, :3].astype(np.float32) / 127.0
    uvs = np.frombuffer(raw, np.float32, nv * 2, lay["uv"]).reshape(-1, 2)
    idx = np.frombuffer(raw, np.uint32, ni, lay["index"])
    cache = {}

    def mat_for(p):
        key = (p["texture"], tuple(p["colour"]))
        if key in cache:
            return cache[key]
        g = G("robot_" + (p["texture"] or "plain").replace(".jpg", "") + str(len(cache)))
        b = g.principled()
        if p["texture"]:
            uv = g.n("ShaderNodeUVMap")
            uv.uv_map = "UV"
            t = g.img(R.ROBOT / "textures" / p["texture"], uv.outputs[0], colour=True, box=False)
            base = t.outputs[0]
            lum = g.luma(base)
            # The shell maps are flat colour: paint reads glossier than bare parts.
            sep = g.n("ShaderNodeSeparateColor")
            g.nt.links.new(base, sep.inputs[0])
            red = g.rng(g.math("SUBTRACT", sep.outputs[0], sep.outputs[1]), 0.1, 0.3, 0.0, 1.0)
            g.link(b.inputs["Roughness"], g.lerp(red, 0.46, 0.3))
            g.link(b.inputs["Coat Weight"], g.mul(red, 0.25))
            g.link(b.inputs["Coat Roughness"], 0.25)
            g.link(b.inputs["Base Color"], g.cmix(g.mul(red, 1.0), base, g.cmix(1.0, base, (0.62, 0.3, 0.26), "MULTIPLY")))
            g.link(b.inputs["Metallic"], g.mul(g.rng(lum, 0.25, 0.6, 0.0, 1.0), g.math("SUBTRACT", 1.0, red)))
        else:
            g.link(b.inputs["Base Color"], tuple(p["colour"][:3]))
            g.link(b.inputs["Roughness"], 0.4)
        cache[key] = g.finish(b.outputs[0])
        return cache[key]

    objs = {}
    for body in rec.labels:
        parts = [p for p in meta["parts"] if p["body"] == body]
        tris, mats, slot = [], [], []
        for k, p in enumerate(parts):
            tri = idx[p["first_index"]:p["first_index"] + p["index_count"]]
            tris.append(tri)
            slot.append(np.full(len(tri) // 3, k, np.int32))
            mats.append(mat_for(p))
        tri = np.concatenate(tris)
        used, inv = np.unique(tri, return_inverse=True)
        me = bpy.data.meshes.new("robot_" + body)
        me.from_pydata(pos[used].astype(np.float64).tolist(), [], inv.reshape(-1, 3).tolist())
        for m in mats:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", np.concatenate(slot))
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        uvl = me.uv_layers.new(name="UV")
        lv = np.zeros(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", lv)
        uvl.uv.foreach_set("vector", uvs[used][lv].ravel())
        # The asset has degenerate triangles, and custom normals read out of bounds on them. Validate after the per-face data is set.
        if me.validate(verbose=False, clean_customdata=False):
            print("robot mesh cleaned:", body, flush=True)
        me.update()
        n = nor[used]
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
        me.normals_split_custom_set_from_vertices(n.tolist())
        ob = bpy.data.objects.new("solid_robot_" + body, me)
        ob.rotation_mode = "QUATERNION"
        coll.objects.link(ob)
        objs[body] = ob
    return objs


def set_pose(rec, objs, t):
    pos, q = rec.pose(t)
    for i, body in enumerate(rec.labels):
        ob = objs[body]
        ob.location = pos[i].tolist()
        ob.rotation_quaternion = (q[i, 3], q[i, 0], q[i, 1], q[i, 2])


def place_camera(cam, eye, target, focus, lens, fstop):
    cam.location = eye.tolist()
    f = Vector((target - eye).tolist()).normalized()
    q = f.to_track_quat("-Z", "Y")
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = q
    d = cam.data
    d.lens = lens
    d.sensor_width = 36.0
    d.clip_start = 0.03
    d.clip_end = 80.0
    d.dof.use_dof = True
    d.dof.aperture_fstop = fstop
    d.dof.aperture_blades = 7
    fwd = q @ Vector((0, 0, -1))
    d.dof.focus_distance = max(0.2, (Vector(focus.tolist()) - Vector(eye.tolist())).dot(fwd))


# ---------------------------------------------------------------- main

def main():
    a = parse_args()
    shot = dict(R.SHOTS[a.shot])
    if a.override:
        shot.update(json.loads(a.override))
    rec = R.Record(shot["run"])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    setup_render(a)
    t_build = time.time()
    if a.mode != "probe":
        plant = Plant(rec)
        floor_img, circles = bake_floor(rec, out)
        me = bpy.data.meshes.new("floor")
        x0, x1, y0, y1 = FLOOR
        me.from_pydata([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)], [], [(0, 1, 2, 3)])
        me.materials.append(floor_material(floor_img))
        fl = bpy.data.objects.new("solid_floor", me)
        sc.collection.objects.link(fl)
        plant.build()
        (out / "manifest.json").write_text(json.dumps({"solids": plant.manifest, "visual_boxes": plant.visual_boxes, "visual_objects": sorted(o.name for o in bpy.data.objects if o.name.startswith("visual_")), "other_objects": sorted(o.name for o in bpy.data.objects if not o.name.startswith(("visual_", "solid_")))}))
        print("plant built in %.1f s, %d triangles" % (time.time() - t_build, sum(len(o.data.polygons) for o in bpy.data.objects if o.type == "MESH")), flush=True)
    robot = build_robot(rec, sc.collection)

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam

    # Times per frame.
    if a.mode == "clip":
        t0, t1 = shot["t0"], shot["t1"]
        if t1 > rec.t[-1] + 1e-6:
            raise SystemExit(f"shot ends at {t1} s, after the record's end at {rec.t[-1]:.2f} s")
        n = int(round((t1 - t0) * a.fps))
        times = [t0 + i / a.fps for i in range(n)]
    elif a.mode == "still":
        times = [a.t if a.t is not None else shot["t"]]
    else:
        times = [float(x) for x in a.probe_times.split(",")]
    lo, hi = float(rec.t[0]), float(rec.t[-1])
    clamp = lambda t: min(max(t, lo), hi)

    if a.mode == "clip":
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        for fi, t in enumerate(times):
            set_pose(rec, robot, t)
            eye, tgt, foc, lens, fstop = R.camera(shot, rec, t)
            place_camera(cam, eye, tgt, foc, lens, fstop)
            for ob in robot.values():
                ob.keyframe_insert("location", frame=fi + 1)
                ob.keyframe_insert("rotation_quaternion", frame=fi + 1)
            cam.keyframe_insert("location", frame=fi + 1)
            cam.keyframe_insert("rotation_quaternion", frame=fi + 1)
    elif a.mode == "still" and not a.no_blur:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        t = times[0]
        for f, tt in ((0, t - 1 / a.fps), (1, t), (2, t + 1 / a.fps)):
            set_pose(rec, robot, clamp(tt))
            for ob in robot.values():
                ob.keyframe_insert("location", frame=f)
                ob.keyframe_insert("rotation_quaternion", frame=f)
    if a.mode == "probe":
        for body, ob in robot.items():
            ob.hide_render = body != "base"
        g = G("flat")
        e = g.n("ShaderNodeEmission")
        o = g.n("ShaderNodeOutputMaterial")
        g.nt.links.new(e.outputs[0], o.inputs[0])
        base = robot["base"].data
        for i in range(len(base.materials)):
            base.materials[i] = g.mat
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
    end = a.end_frame if a.end_frame is not None else len(times)
    for fi in range(a.start_frame, min(end, len(times))):
        t = times[fi]
        eye, tgt, foc, lens, fstop = R.camera(shot, rec, t)
        if a.mode == "clip":
            sc.frame_set(fi + 1)
            place_camera(cam, eye, tgt, foc, lens, fstop)
            sc.frame_set(fi + 1)
        else:
            if a.mode == "probe" or a.no_blur:
                set_pose(rec, robot, t)
            place_camera(cam, eye, tgt, foc, lens, fstop)
            if a.mode == "probe":
                cam.data.dof.use_dof = False
            sc.frame_set(1)
        bpy.context.view_layer.update()
        name = {"clip": "frame_%04d.exr" % fi, "still": "still.exr", "probe": "probe_%02d.png" % fi}[a.mode]
        sc.render.filepath = str(out / name)
        ts = time.time()
        bpy.ops.render.render(write_still=True)
        dt = time.time() - ts
        timing.append(dt)
        dg = bpy.context.evaluated_depsgraph_get()
        bodies = {b: {"loc": list(ob.evaluated_get(dg).matrix_world.translation), "quat": list(ob.evaluated_get(dg).matrix_world.to_quaternion())} for b, ob in robot.items()}
        base_px = world_to_camera_view(sc, cam, robot["base"].evaluated_get(dg).matrix_world.translation)
        log.append({"frame": fi, "t": t, "bodies": bodies, "cam": [list(r) for r in cam.evaluated_get(dg).matrix_world], "lens": cam.data.lens, "sensor": cam.data.sensor_width,
                    "res": [sc.render.resolution_x, sc.render.resolution_y], "screen": list(base_px), "seconds": dt})
        print("frame %d t=%.3f %.1f s" % (fi, t, dt), flush=True)
        (out / ("poses_%s_%04d.json" % (a.mode, a.start_frame))).write_text(json.dumps(log))
    print("mean seconds per frame %.1f" % (sum(timing) / max(len(timing), 1)), flush=True)


if __name__ == "__main__":
    main()
