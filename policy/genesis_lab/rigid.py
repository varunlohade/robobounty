"""Go2 from Genesis assets on a typed box and slope. Simulated, not calibrated: rigid.py --backend cpu|metal --seed N --steps N [--frames DIR] [--terrain flat|heightfield]
Genesis ships no walking policy for Go2. The drive is an open-loop trot written here, which walks rear-first, so the robot starts turned 180 degrees to head at +x. It can fall. That is not a Genesis fault.
"""
import argparse, hashlib, json, math, platform, time
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--backend", default="cpu")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--steps", type=int, default=1000)
ap.add_argument("--frames", default="")
ap.add_argument("--no-robot-self", action="store_true")
a = ap.parse_args()

import genesis as gs

gs.init(backend=getattr(gs, a.backend), seed=a.seed, logging_level="warning", precision="32")
t0 = time.perf_counter()
scene = gs.Scene(sim_options=gs.options.SimOptions(dt=0.005, substeps=2), show_viewer=False)
scene.add_entity(gs.morphs.Plane())
go2 = scene.add_entity(gs.morphs.URDF(file="urdf/go2/urdf/go2.urdf", pos=(0, 0, 0.42), quat=(0, 0, 0, 1)))
box = scene.add_entity(gs.morphs.Box(pos=(1.2, 0.0, 0.1), size=(0.3, 0.8, 0.2), fixed=False), material=gs.materials.Rigid(rho=200.0))
slope_deg = 12.0
slope = scene.add_entity(gs.morphs.Box(pos=(3.0, 0.0, 0.2), size=(2.0, 1.6, 0.05), euler=(0, -slope_deg, 0), fixed=True))
cam = None
if a.frames:
    cam = scene.add_camera(res=(960, 540), pos=(1.2, -3.6, 1.5), lookat=(1.3, 0, 0.25), fov=45, GUI=False)
scene.build()
build_s = time.perf_counter() - t0

names = [f"{leg}_{j}_joint" for leg in ("FR", "FL", "RR", "RL") for j in ("hip", "thigh", "calf")]
idx = [go2.get_joint(n).dofs_idx_local[0] for n in names]
stand = np.array([0, 0.8, -1.5] * 4, dtype=np.float32)
go2.set_dofs_kp([40.0] * 12, idx)
go2.set_dofs_kv([1.0] * 12, idx)
go2.set_dofs_position(stand, idx, zero_velocity=True)
print("mass", float(go2.get_mass()), "box mass", float(box.get_mass()), "nq", go2.n_qs, "ndof", go2.n_dofs, "links", go2.n_links, "geoms", go2.n_geoms)


def pose(t):
    phase = 2 * math.pi * 2.0 * t
    q = stand.copy()
    for leg, off in enumerate((0, math.pi, math.pi, 0)):
        s = -math.sin(phase + off)
        q[3 * leg + 1] += 0.25 * s
        q[3 * leg + 2] += 0.25 * max(0.0, math.cos(phase + off))
    return q


h = hashlib.sha256()
trace = []
frames = []
sim_s = 0.0
for i in range(a.steps):
    go2.control_dofs_position(pose(i * 0.005), idx)
    t1 = time.perf_counter()
    scene.step()
    sim_s += time.perf_counter() - t1
    q = np.concatenate([go2.get_qpos().cpu().numpy().ravel(), box.get_qpos().cpu().numpy().ravel()]).astype(np.float32)
    h.update(q.tobytes())
    if i % 200 == 0:
        trace.append([round(float(x), 3) for x in q[:3]])
    if cam is not None and i % 100 == 0:
        rgb = cam.render()[0]
        frames.append(rgb)
out = {
    "label": "sim genesis_lab, not calibrated",
    "backend": a.backend, "seed": a.seed, "steps": a.steps, "dt": 0.005, "substeps": 2, "build_s": round(build_s, 2),
    "steps_per_s": round(a.steps / sim_s, 1), "rtf": round(a.steps * 0.005 / sim_s, 2), "state_sha256": h.hexdigest()[:16],
    "base_xyz_every_1s": trace, "box_final": [round(float(x), 3) for x in box.get_pos().cpu().numpy().ravel()],
    "machine": platform.machine(),
}
print("RESULT", json.dumps(out))
if frames:
    from PIL import Image
    d = Path(a.frames)
    d.mkdir(parents=True, exist_ok=True)
    picks = frames[:: max(1, len(frames) // 4)][:4]
    w, h2 = picks[0].shape[1], picks[0].shape[0]
    sheet = Image.new("RGB", (w * 2, h2 * 2))
    for k, f in enumerate(picks):
        sheet.paste(Image.fromarray(np.asarray(f, dtype=np.uint8)), ((k % 2) * w, (k // 2) * h2))
    sheet.save(d / f"rigid-{a.backend}.png")
