"""Bakes Blender's own AgX view (Medium High Contrast) to a LUT for post_v2.py. Run through Blender:
blender --background --factory-startup --python policy/render/bake_agx.py -- <out.npy>"""
import sys
from pathlib import Path

import bpy
import numpy as np

out = Path(sys.argv[sys.argv.index("--") + 1])
out.parent.mkdir(parents=True, exist_ok=True)
N = 65
g = 2.0 ** (np.linspace(0, 1, N) * 25.0 - 12.47393)
r, gg, b = np.meshgrid(g, g, g, indexing="ij")
px = np.stack([r.ravel(), gg.ravel(), b.ravel(), np.ones(N ** 3)], axis=1).astype(np.float32)
w, h = N * N, N
img = bpy.data.images.new("lut", w, h, float_buffer=True, alpha=False)
img.colorspace_settings.name = "Linear Rec.709"
img.pixels.foreach_set(px.ravel())
sc = bpy.context.scene
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "AgX - Medium High Contrast"
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0
sc.display_settings.display_device = "sRGB"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.render.image_settings.color_depth = "16"
tmp = out.with_suffix(".tmp.png")
img.save_render(str(tmp), scene=sc)
sc.render.image_settings.file_format = "OPEN_EXR"  # nothing else reads this scene


def read_png16(path):
    """Minimal PNG reader through Blender: load as data, keep values as stored."""
    im = bpy.data.images.load(str(path))
    im.colorspace_settings.name = "Non-Color"
    a = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(-1, 4)[:, :3]


v = read_png16(tmp)
lut = v.reshape(N, N, N, 3)
np.save(out, lut.astype(np.float32))
tmp.unlink()
print("baked", out, lut.min(), lut.max(), "mid grey maps to", lut[int((np.log2(0.18) + 12.47393) / 25 * 64)] [int((np.log2(0.18) + 12.47393) / 25 * 64)][int((np.log2(0.18) + 12.47393) / 25 * 64)])
