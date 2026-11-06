"""Turntable stills of a GLB: blender -b --python generated_turntable.py -- <glb> <out.png>. Three views on one sheet, neutral light, for checking a model."""
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generated_glb as G

glb, out = sys.argv[sys.argv.index("--") + 1:][:2]
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.device = "GPU"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
prefs.get_devices()
for device in prefs.devices:
    device.use = True
scene.render.resolution_x = scene.render.resolution_y = 700
scene.render.film_transparent = False
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.72, 0.73, 0.75, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
scene.world = world
root = G.import_glb(glb, 1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(30)))
bpy.context.object.data.energy = 3.0
bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -0.62))
bpy.ops.object.camera_add(location=(0, -2.2, 0.9), rotation=(math.radians(70), 0, 0))
scene.camera = bpy.context.object
scene.camera.data.lens = 50
paths = []
for i in range(3):
    root.rotation_euler = (0, 0, math.radians(35 + 120 * i))
    bpy.context.view_layer.update()
    scene.render.filepath = f"{out}.{i}.png"
    bpy.ops.render.render(write_still=True)
    paths.append(scene.render.filepath)
images = [bpy.data.images.load(p) for p in paths]
w, h = images[0].size
import numpy as np

sheet = np.zeros((h, w * 3, 4), dtype=np.float32)
for i, image in enumerate(images):
    sheet[:, i * w:(i + 1) * w] = np.array(image.pixels[:], dtype=np.float32).reshape(h, w, 4)
result = bpy.data.images.new("sheet", w * 3, h)
result.pixels = sheet.ravel().tolist()
result.filepath_raw = out
result.file_format = "PNG"
result.save()
for p in paths:
    Path(p).unlink()
