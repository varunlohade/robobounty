"""Exports the inspection pack's ANYmal C (read only) from Newton's builder to an MJCF copy in work/robot. Run with .venv-newton from policy/."""
import sys
sys.dont_write_bytecode = True
import newton
from packs.inspection import model as M
b, cfg = M._robot_builder()
model = b.finalize()
newton.solvers.SolverMuJoCo(model, save_to_mjcf=sys.argv[1])
# Visual meshes too: the MJCF export above only carries collision primitives.
import json, numpy as np, warp as wp
from pathlib import Path
out = Path(sys.argv[1]).parent / "visuals"; out.mkdir(exist_ok=True)
parts = []
for i in range(len(b.shape_type)):
    if not (int(b.shape_flags[i]) & int(newton.ShapeFlags.VISIBLE)) or b.shape_source[i] is None or b.shape_body[i] < 0:
        continue
    mesh = b.shape_source[i]; xf = b.shape_transform[i]
    R = np.array(wp.quat_to_matrix(wp.quat(*xf[3:7])), dtype=np.float64).reshape(3, 3)
    pts = np.asarray(mesh.vertices, np.float64) * np.asarray(b.shape_scale[i]) @ R.T + np.asarray(xf[:3], np.float64)
    f = np.asarray(mesh.indices, np.int64).reshape(-1, 3) + 1
    name = f"p{i}.obj"
    with open(out / name, "w") as fh:
        np.savetxt(fh, pts, fmt="v %.6f %.6f %.6f"); np.savetxt(fh, f, fmt="f %d %d %d")
    parts.append(dict(file=name, body=str(b.body_label[b.shape_body[i]])))
json.dump(parts, open(out / "parts.json", "w"), indent=1)
print("visual parts", len(parts), parts[:2])
print("bodies", model.body_count, "joints", model.joint_count, "shapes", model.shape_count, "mass", float(model.body_mass.numpy().sum()))
