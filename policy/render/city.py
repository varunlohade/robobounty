"""Procedural city far below the tower. Invented, no real buildings. All numpy, seeded, re-runnable."""
import math

import bpy
import numpy as np

BLOCK = 86.0
STREET = 16.0
AVENUE_EVERY = 5
RADIUS = 5200.0
TREES = True  # The v2 look turns these off: close up they read as CG.
CLEAR = (-22.0, 24.0, -30.0, 38.0)  # x0, x1, y0, y1 plaza around the tower base, relative to its centre


class Mesh:
    def __init__(self):
        self.v, self.f, self.uv, self.col, self.kind = [], [], [], [], []

    def quad(self, a, b, c, d, uvs, col, kind):
        i = len(self.v)
        self.v += [a, b, c, d]
        self.f.append((i, i + 1, i + 2, i + 3))
        self.uv += uvs
        self.col += [col] * 4
        self.kind += [kind] * 4

    def box(self, cx, cy, w, d, z0, z1, rot, col, kind=0.0, roof_kind=None):
        c, s = math.cos(rot), math.sin(rot)
        def P(x, y, z):
            return (cx + c * x - s * y, cy + s * x + c * y, z)
        hw, hd = w / 2, d / 2
        p = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
        lens = [w, d, w, d]
        seed = (cx * 0.37 + cy * 0.73) % 97
        for i in range(4):
            x0, y0 = p[i]
            x1, y1 = p[(i + 1) % 4]
            L = lens[i]
            self.quad(P(x0, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y0, z1),
                      [(seed, z0), (seed + L, z0), (seed + L, z1), (seed, z1)], col, kind)
        rk = 1.0 if roof_kind is None else roof_kind
        self.quad(P(-hw, -hd, z1), P(hw, -hd, z1), P(hw, hd, z1), P(-hw, hd, z1),
                  [(0, 0), (w, 0), (w, d), (0, d)], col, rk)


def tower(m, rng, cx, cy, w, d, h, rot, col, near):
    """One building: podium, tiers, parapet, roof plant, sometimes a crown."""
    kind = float(rng.choice([0.0, 0.2, 0.4], p=[0.45, 0.25, 0.3]))
    if h > 90:
        kind = float(rng.choice([0.2, 0.4], p=[0.3, 0.7]))
    c, s = math.cos(rot), math.sin(rot)

    def at(ox, oy):
        return cx + c * ox - s * oy, cy + s * ox + c * oy

    z = 0.0
    W, D = w, d
    if h > 45 and rng.random() < 0.5:
        # A wider podium with its own facade.
        pod = float(rng.uniform(10, 22))
        m.box(cx, cy, w * 1.12, d * 1.12, 0.0, pod, rot, tuple(float(x) for x in np.array(col) * 1.15), 0.0)
        z = pod
    tiers = 1
    if h > 60 and rng.random() < 0.55:
        tiers = 2 if rng.random() < 0.6 else 3
    for t in range(tiers):
        top = h if t == tiers - 1 else z + (h - z) * rng.uniform(0.45, 0.72)
        m.box(cx, cy, W, D, z, top, rot, col, kind)
        z = top
        if t < tiers - 1:
            W *= rng.uniform(0.62, 0.84)
            D *= rng.uniform(0.62, 0.84)
    if not near:
        return
    rc = tuple(float(x) for x in np.array(col) * 0.8)
    # Parapet: four low walls around the roof.
    pw = 0.5
    for ox, oy, bw, bd in ((0, D / 2 - pw / 2, W, pw), (0, -D / 2 + pw / 2, W, pw), (W / 2 - pw / 2, 0, pw, D), (-W / 2 + pw / 2, 0, pw, D)):
        bx, by = at(ox, oy)
        m.box(bx, by, bw, bd, z, z + 1.1, rot, rc, 1.0)
    # Plant rooms, ducts and tanks on the roof.
    for _ in range(rng.integers(2, 6)):
        bw, bd = rng.uniform(2, W * 0.32 + 2), rng.uniform(2, D * 0.32 + 2)
        bx, by = at(rng.uniform(-0.32, 0.32) * W, rng.uniform(-0.32, 0.32) * D)
        m.box(bx, by, bw, bd, z, z + rng.uniform(1.5, 5), rot, rc, 1.0)
    if rng.random() < 0.3:
        # A water tank on legs reads at any distance.
        bx, by = at(rng.uniform(-0.3, 0.3) * W, rng.uniform(-0.3, 0.3) * D)
        m.box(bx, by, 4.5, 4.5, z + 3.2, z + 7.5, rot + 0.5, (0.2, 0.17, 0.14), 1.0)
    if h > 120:
        bx, by = at(0, 0)
        crown = rng.random()
        if crown < 0.5:
            m.box(bx, by, W * 0.55, D * 0.55, z, z + rng.uniform(6, 14), rot, col, kind)
        else:
            m.box(bx, by, 1.4, 1.4, z, z + rng.uniform(14, 34), rot, (0.2, 0.2, 0.21), 1.0)


def layout(run, rng):
    """Blocks and lots. Returns (mesh for buildings, mesh for ground plots, mesh for trees)."""
    b, g, tr = Mesh(), Mesh(), Mesh()
    pitch = BLOCK + STREET
    n = int(RADIUS / pitch) + 1
    tcx = run.glass_cx
    tcy = 14.0
    x0, x1, y0, y1 = CLEAR
    palette = np.array([[0.30, 0.30, 0.30], [0.36, 0.35, 0.33], [0.22, 0.24, 0.26], [0.42, 0.41, 0.39],
                        [0.17, 0.19, 0.21], [0.33, 0.30, 0.27], [0.48, 0.47, 0.45], [0.13, 0.15, 0.17]])
    # Hot spots of height, so the skyline has clusters rather than noise.
    hubs = [(-340, -520, 170), (420, -880, 210), (-1150, -700, 190), (150, -1700, 230), (-700, -2100, 210),
            (1300, -1450, 170), (-1900, -1500, 180), (620, 620, 170), (-800, 500, 190)]
    for ix in range(-n, n + 1):
        for iy in range(-n, n + 1):
            ox = sum(STREET * 0.9 for k in range(abs(ix)) if k % AVENUE_EVERY == 0) * np.sign(ix)
            oy = sum(STREET * 0.9 for k in range(abs(iy)) if k % AVENUE_EVERY == 0) * np.sign(iy)
            cx, cy = ix * pitch + ox + tcx + 34, iy * pitch + oy + tcy + 30
            r = math.hypot(cx, cy)
            if r > RADIUS:
                continue
            # Far districts turn off the near grid, as old cities do.
            ang = 0.0 if r < 1800 else 0.22
            if ang:
                ca, sa = math.cos(ang), math.sin(ang)
                cx, cy = ca * cx - sa * cy, sa * cx + ca * cy
            if x0 - BLOCK / 2 < cx - tcx < x1 + BLOCK / 2 and y0 - BLOCK / 2 < cy - tcy < y1 + BLOCK / 2:
                continue
            near = r < 1100
            # Ground plot for the block.
            gc = float(rng.uniform(0.15, 0.2))
            g.box(cx, cy, BLOCK, BLOCK, 0.0, 0.35, ang, (gc, gc, gc * 0.98), 1.0)
            if rng.random() < 0.05 and r > 200:
                # A park: a lower, darker green block.
                g.box(cx, cy, BLOCK - 6, BLOCK - 6, 0.35, 0.5, ang, (0.07, 0.10, 0.07), 1.0)
                for _ in range(26 if near else 6):
                    tree(tr, rng, cx + rng.uniform(-38, 38), cy + rng.uniform(-38, 38))
                continue
            heat = sum(hh * math.exp(-((cx - hx) ** 2 + (cy - hy) ** 2) / (2 * 300.0 ** 2)) for hx, hy, hh in hubs)
            lots = rng.choice([1, 2, 3, 4], p=[0.25, 0.3, 0.2, 0.25]) if r < 3000 else 2
            for k in range(lots):
                if lots == 1:
                    lx, ly, w, d = 0, 0, BLOCK * rng.uniform(0.72, 0.92), BLOCK * rng.uniform(0.72, 0.92)
                elif lots == 2:
                    lx, ly = (k - 0.5) * BLOCK * 0.5, rng.uniform(-3, 3)
                    w, d = BLOCK * rng.uniform(0.36, 0.45), BLOCK * rng.uniform(0.7, 0.92)
                else:
                    lx, ly = ((k % 2) - 0.5) * BLOCK * 0.5, ((k // 2) - 0.5) * BLOCK * 0.5
                    w, d = BLOCK * rng.uniform(0.32, 0.44), BLOCK * rng.uniform(0.32, 0.44)
                c, s = math.cos(ang), math.sin(ang)
                bx, by = cx + c * lx - s * ly, cy + s * lx + c * ly
                base = float(rng.lognormal(math.log(26), 0.55))
                h = min(base + heat * rng.uniform(0.25, 1.0), 270.0)
                # Each building keeps a slight hue of its own, cool stone to warm brick, then the post grade pulls it back.
                hue = np.array([1.0 + rng.normal(0, 0.05), 1.0, 1.0 + rng.normal(0, 0.05)])
                col = tuple(float(v) for v in palette[rng.integers(len(palette))] * hue * rng.uniform(0.8, 1.2))
                tower(b, rng, bx, by, w, d, h, ang, col, near)
            if r < 700:
                # Street trees along the block edge.
                for edge in range(4):
                    for t in range(-3, 4):
                        if rng.random() < 0.55:
                            e = BLOCK / 2 + 2.5
                            a, q = t * 12.0 + rng.uniform(-2, 2), e if edge % 2 else -e
                            tx, ty = (a, q) if edge < 2 else (q, a)
                            tree(tr, rng, cx + tx, cy + ty)
    return b, g, tr


def tree(m, rng, x, y):
    if not TREES:
        return
    r = float(rng.uniform(3.0, 5.2))
    h = 1.0
    g = float(rng.uniform(0.07, 0.13))
    col = (g * 0.72, g, g * 0.62)
    # A squat dome of quads: seen from 130 m it only has to read as a soft crown.
    ring0, ring1 = [], []
    for i in range(8):
        a = i * math.pi / 4 + 0.4
        ring0.append((x + r * math.cos(a), y + r * math.sin(a), h))
        ring1.append((x + r * 0.6 * math.cos(a), y + r * 0.6 * math.sin(a), h + r * 0.75))
    top = (x, y, h + r * 0.95)
    for i in range(8):
        j = (i + 1) % 8
        m.quad(ring0[i], ring0[j], ring1[j], ring1[i], [(0, 0)] * 4, col, 1.0)
        m.quad(ring1[i], ring1[j], top, top, [(0, 0)] * 4, col, 1.0)


def to_object(m, name, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata(m.v, [], m.f)
    me.update()
    uv = me.uv_layers.new(name="UVMap")
    fl = np.array(m.uv, dtype=np.float32)
    corner_v = np.zeros(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", corner_v)
    uv.data.foreach_set("uv", fl[corner_v].ravel())
    col = me.attributes.new("bcol", "FLOAT_COLOR", "POINT")
    rgba = np.ones((len(m.v), 4), np.float32)
    rgba[:, :3] = np.array(m.col, np.float32)
    col.data.foreach_set("color", rgba.ravel())
    kind = me.attributes.new("bkind", "FLOAT", "POINT")
    kind.data.foreach_set("value", np.array(m.kind, np.float32))
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def city_material(haze, focus, N, out, new_mat):
    mat = new_mat("city")
    n = N(mat)
    geo = n.add("ShaderNodeNewGeometry")
    tc = n.add("ShaderNodeUVMap", uv_map="UVMap")
    ux, uy, _ = n.split(tc.outputs[0])
    col = n.add("ShaderNodeAttribute", attribute_name="bcol").outputs["Color"]
    kind = n.add("ShaderNodeAttribute", attribute_name="bkind").outputs["Fac"]
    wall = n.math("LESS_THAN", kind, 0.5)
    # Window grid in metres.
    fu = n.math("FRACT", n.mul(ux, 1 / 2.8))
    fv = n.math("FRACT", n.mul(uy, 1 / 3.6))
    # Three facade styles: punched windows, ribbon windows, dark curtain wall.
    ribbon = n.math("GREATER_THAN", kind, 0.1)
    curtain = n.math("GREATER_THAN", kind, 0.3)
    wu = n.mix_f(ribbon, n.mul(n.math("GREATER_THAN", fu, 0.16), n.math("LESS_THAN", fu, 0.84)), 1.0)
    wv_lo = n.mix_f(curtain, n.mix_f(ribbon, 0.22, 0.32), 0.04)
    wv_hi = n.mix_f(curtain, n.mix_f(ribbon, 0.82, 0.82), 0.96)
    wv = n.mul(n.math("GREATER_THAN", fv, wv_lo), n.math("LESS_THAN", fv, wv_hi))
    win = n.mul(n.mul(wu, wv), wall)
    cell = n.add("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
    n.link(n.xyz(n.math("FLOOR", n.mul(ux, 1 / 2.8)), n.math("FLOOR", n.mul(uy, 1 / 3.6)), 1.0), cell.inputs["Vector"])
    # Glass that varies, curtains, a few rooms with the lights on.
    win_tone = n.add_(0.07, n.mul(0.035, cell.outputs[0]))
    win_col = n.add("ShaderNodeCombineColor")
    n.link(n.mul(win_tone, 0.9), win_col.inputs[0])
    n.link(win_tone, win_col.inputs[1])
    n.link(n.mul(win_tone, 1.08), win_col.inputs[2])
    grime = n.noise(n.xyz(n.mul(ux, 0.3), n.mul(uy, 0.08), 0.0), 2.0, 5.0, 0.6)
    wall_col = n.mix(n.mul(0.5, grime), col, (0.08, 0.08, 0.08, 1))
    # Roofs: gravel and membrane, lighter than the walls, whatever colour the building is.
    pos0 = geo.outputs["Position"]
    roof_n = n.noise(pos0, 0.35, 6.0, 0.65)
    roof_col = n.mix(n.smooth(0.3, 0.7, roof_n), (0.13, 0.128, 0.122, 1), (0.23, 0.226, 0.215, 1))
    is_roof = n.math("GREATER_THAN", kind, 0.95)
    flat = n.smooth(0.8, 0.95, n.split(geo.outputs["Normal"])[2])
    wall_col = n.mix(n.mul(is_roof, flat), wall_col, roof_col)
    base = n.mix(win, wall_col, win_col.outputs[0])
    # Roof and plot texture.
    pos = geo.outputs["Position"]
    b = n.add("ShaderNodeBsdfPrincipled")
    n.link(base, b.inputs["Base Color"])
    n.set(b.inputs["Roughness"], n.mix_f(win, 0.85, 0.12))
    n.set(b.inputs["Specular IOR Level"], n.mix_f(win, 0.3, 0.9))
    lit = n.mul(n.math("GREATER_THAN", cell.outputs[0], 0.985), win)
    b.inputs["Emission Color"].default_value = (1.0, 0.82, 0.62, 1)
    n.set(b.inputs["Emission Strength"], n.mul(lit, 0.07))
    out(n, n.fog(b.outputs[0], haze, focus))
    return mat


def build(run, haze, focus, N, out, new_mat):
    rng = np.random.default_rng(1307)
    mat = city_material(haze, focus, N, out, new_mat)
    b, g, tr = layout(run, rng)
    to_object(b, "city", mat)
    to_object(g, "plots", mat)
    if tr.v:
        to_object(tr, "trees", mat)
    # Street plane out past the fog, and on to the horizon.
    gm = new_mat("street")
    n = N(gm)
    geo = n.add("ShaderNodeNewGeometry")
    bs = n.add("ShaderNodeBsdfPrincipled")
    bs.inputs["Base Color"].default_value = (0.055, 0.057, 0.06, 1)
    bs.inputs["Roughness"].default_value = 0.55
    out(n, n.fog(bs.outputs[0], haze, focus))
    v = [(-40000, -40000, -0.05), (40000, -40000, -0.05), (40000, 40000, -0.05), (-40000, 40000, -0.05)]
    me = bpy.data.meshes.new("ground")
    me.from_pydata(v, [], [(0, 1, 2, 3)])
    me.update()
    me.materials.append(gm)
    ob = bpy.data.objects.new("ground", me)
    bpy.context.scene.collection.objects.link(ob)
    print("city: %d buildings quads, %d plots quads, %d tree quads" % (len(b.f), len(g.f), len(tr.f)))
