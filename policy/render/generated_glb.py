"""Imports a generated GLB into Blender, placed as the physics places it. Blender's glTF importer turns y up into z up the same way generate_object.py does. The GLB is data, and only Blender's importer reads it."""
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

WEB = Path(__file__).resolve().parent.parent.parent / "public" / "generated"


def bounds(objects):
    points = [o.matrix_world @ Vector(c) for o in objects if o.type == "MESH" for c in o.bound_box]
    return Vector(min(p[i] for p in points) for i in range(3)), Vector(max(p[i] for p in points) for i in range(3))


def import_glb(path, real_size_m, pos, quat_xyzw, collection=None):
    """pos is the model's centre. real_size_m is its longest side. Returns the root that holds the model."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    made = [o for o in bpy.data.objects if o not in before]
    bpy.context.view_layer.update()
    low, high = bounds(made)
    scale = real_size_m / max(high - low)
    x, y, z, w = quat_xyzw
    root = bpy.data.objects.new("generated", None)
    (collection or bpy.context.scene.collection).objects.link(root)
    root.matrix_world = Matrix.Translation(Vector(pos)) @ Quaternion((w, x, y, z)).to_matrix().to_4x4()
    fit = Matrix.Scale(scale, 4) @ Matrix.Translation(-(low + high) / 2)
    for o in made:
        if o.parent is None:
            o.parent = root
            o.matrix_parent_inverse = fit
        if collection:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            collection.objects.link(o)
    return root


def place_prim(prim, collection=None):
    """A hull or glb primitive from the inspection pack's replay data."""
    return import_glb(WEB / f"{prim['glb']}.glb", prim["real_size_m"], prim["pos"], prim["quat"], collection)
