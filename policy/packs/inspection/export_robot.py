"""Writes the robot's real meshes to public/robots/<robot>/ for the browser's poses player. Picture only: the physics never reads these files.

.venv-newton/bin/python -m packs.inspection.export_robot (from policy/). It reads the visual shapes of the same USD asset that model.py loads, with each shape's offset and scale baked in, so a part is in its body's frame.
robot.json lists the parts and the buffer layout. robot.bin holds positions (float32), normals (int8, padded to 4), uvs (float32) and indices (uint32). The asset's LICENSE travels with the files.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import warp as wp

import newton

from . import model as M

ROOT = Path(__file__).resolve().parents[3]
ROBOT = "anymal_c"
OUT = ROOT / "public" / "robots" / ROBOT
VISIBLE = int(newton.ShapeFlags.VISIBLE)
WELD_DIGITS = 5


def _mesh_of(builder, i):
    source = builder.shape_source[i]
    if source is not None:
        return source
    if builder.shape_type[i] == newton.GeoType.BOX:
        return newton.Mesh.create_box(*builder.shape_scale[i], compute_inertia=False)
    raise ValueError(f"no mesh for visual shape {builder.shape_label[i]}, type {builder.shape_type[i]}")


def _part(builder, i):
    """Vertices in the body's frame, welded so a triangle list shares its corners."""
    mesh = _mesh_of(builder, i)
    faces = np.asarray(mesh.indices, dtype=np.int64).reshape(-1)
    scale = np.ones(3) if builder.shape_source[i] is None else np.asarray(builder.shape_scale[i], dtype=np.float64)
    xform = builder.shape_transform[i]
    rotate = np.array(wp.quat_to_matrix(wp.quat(*xform[3:7])), dtype=np.float64).reshape(3, 3)
    points = np.asarray(mesh.vertices, dtype=np.float64) * scale @ rotate.T + np.asarray(xform[:3], dtype=np.float64)
    normals = np.asarray(mesh.normals, dtype=np.float64) @ rotate.T
    uvs = np.asarray(mesh.uvs, dtype=np.float64) if mesh.uvs is not None else np.zeros((len(points), 2))
    key = np.round(np.hstack((points, normals, uvs)), WELD_DIGITS)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    return points[first], normals[first], uvs[first], inverse[faces], mesh


def main():
    builder, _ = M._robot_builder()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "textures").mkdir(exist_ok=True)
    positions, normals, uvs, indices, parts = [], [], [], [], []
    at_vertex, at_index = 0, 0
    for i in range(builder.shape_count):
        if not builder.shape_flags[i] & VISIBLE:
            continue
        p, n, uv, faces, mesh = _part(builder, i)
        texture = None
        if isinstance(mesh.texture, str):
            texture = Path(mesh.texture).name
            shutil.copyfile(mesh.texture, OUT / "textures" / texture)
        parts.append({"body": builder.body_label[builder.shape_body[i]].rsplit("/", 1)[-1], "colour": [round(float(c), 4) for c in builder.shape_color[i]],
                      "texture": texture, "first_index": at_index, "index_count": len(faces)})
        positions.append(p)
        normals.append(n)
        uvs.append(uv)
        indices.append(faces + at_vertex)
        at_vertex += len(p)
        at_index += len(faces)
    unit = np.vstack(normals)
    unit /= np.maximum(np.linalg.norm(unit, axis=1, keepdims=True), 1e-9)
    packed_normals = np.zeros((at_vertex, 4), dtype=np.int8)
    packed_normals[:, :3] = np.round(unit * 127)
    blobs = [np.vstack(positions).astype(np.float32), packed_normals, np.vstack(uvs).astype(np.float32), np.concatenate(indices).astype(np.uint32)]
    layout, offset = {}, 0
    for name, blob in zip(("position", "normal", "uv", "index"), blobs):
        layout[name] = offset
        offset += blob.nbytes
    (OUT / "robot.bin").write_bytes(b"".join(b.tobytes() for b in blobs))
    (OUT / "robot.json").write_text(json.dumps({"format": "robot-mesh/1", "robot": ROBOT, "source": f"{M.ASSET} {M.USD}, the asset Newton loads", "vertices": at_vertex, "indices": at_index, "layout": layout, "parts": parts}, indent=1))
    shutil.copyfile(Path(M.asset_dir()) / "LICENSE", OUT / "LICENSE")
    print(f"{len(parts)} parts, {at_vertex} vertices, {at_index // 3} triangles, {offset / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
