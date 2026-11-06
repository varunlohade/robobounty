"""NOT RUN YET. Builds a typed Newton lab world in Genesis, with no change to the typed functions, then runs Go2 and writes a record. Simulated, not calibrated.
adapter.py --steps N --envs N --backend cpu|metal. The world comes from policy/newton_lab/world.py. The drive is the scripted trot in rigid.py, not a trained policy.
Quaternions in Genesis are w x y z. Newton uses x y z w, so the record stores x y z w to match policy/newton_lab/out/*.npz.
"""
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "newton_lab"))
import world as W

ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, default=1000)
ap.add_argument("--envs", type=int, default=0)
ap.add_argument("--backend", default="cpu")
ap.add_argument("--record", action="store_true")
a = ap.parse_args()
import genesis as gs
gs.init(backend=getattr(gs, a.backend), seed=0, logging_level="warning")


def fixed_box(scene, name, center, size, pitch_deg, yaw_deg, mu):
    return scene.add_entity(gs.morphs.Box(pos=center, size=size, euler=(0, pitch_deg, yaw_deg), fixed=True), material=gs.materials.Rigid(friction=mu), name=name)


def add_object(scene, obj):
    mu = obj.get("mu", W.DEFAULT_MU)
    name, x, y = obj["name"], obj["x"], obj["y"]
    if obj["kind"] == "box":
        return [fixed_box(scene, name, (x, y, obj["sz"] / 2), (obj["sx"], obj["sy"], obj["sz"]), 0.0, obj.get("yaw_deg", 0.0), mu)]
    if obj["kind"] == "ramp":
        slope = math.atan2(obj["height"], obj["length"])
        thick = obj["height"] / math.cos(slope) + 0.02
        center = (x + obj["length"] / 2 + math.sin(slope) * thick / 2, y, obj["height"] / 2 - math.cos(slope) * thick / 2)
        return [fixed_box(scene, name, center, (math.hypot(obj["length"], obj["height"]), obj["width"], thick), -math.degrees(slope), 0.0, mu)]
    out = []
    for i in range(obj.get("count", 3)):
        top = obj["rise"] * (i + 1)
        out.append(fixed_box(scene, f"{name}_{i}", (x + obj["depth"] * (i + 0.5), y, top / 2), (obj["depth"], obj["width"], top), 0.0, 0.0, mu))
    return out


world = W.build(("set_ground", {"mu": 0.75}), ("add_box", {"name": "crate", "x": 1.8, "y": 0.3, "sx": 0.5, "sy": 0.8, "sz": 0.25}),
                ("add_ramp", {"name": "ramp", "x": 3.2, "y": 0.8, "length": 3.0, "width": 2.0, "height": 0.4}),
                ("add_steps", {"name": "stairs", "x": 7.0, "y": 1.0, "width": 2.0, "depth": 0.35, "rise": 0.05, "count": 5}))
t0 = time.perf_counter()
scene = gs.Scene(sim_options=gs.options.SimOptions(dt=0.005, substeps=2), show_viewer=False)
scene.add_entity(gs.morphs.Plane(), material=gs.materials.Rigid(friction=world["ground"]["mu"]))
go2 = scene.add_entity(gs.morphs.URDF(file="urdf/go2/urdf/go2.urdf", pos=(0, 0, 0.42), quat=(0, 0, 0, 1)), name="go2")
solids = []
for obj in world["objects"]:
    solids += add_object(scene, obj)
cam = scene.add_camera(res=(1280, 720), pos=(3.5, -5.5, 2.6), lookat=(3.5, 0.6, 0.2), fov=50, GUI=False) if a.record else None
if a.record:
    scene.export(ROOT / "out" / "typed_world.gs")
scene.build(n_envs=a.envs) if a.envs else scene.build()
build_s = time.perf_counter() - t0
names = [f"{leg}_{j}_joint" for leg in ("FR", "FL", "RR", "RL") for j in ("hip", "thigh", "calf")]
idx = [go2.get_joint(n).dofs_idx_local[0] for n in names]
stand = np.array([0, 0.8, -1.5] * 4, dtype=np.float32)
go2.set_dofs_kp([40.0] * 12, idx)
go2.set_dofs_kv([1.0] * 12, idx)
go2.set_dofs_position(np.tile(stand, (a.envs, 1)) if a.envs else stand, idx, zero_velocity=True)


def pose(t):
    q = stand.copy()
    for leg, off in enumerate((0, math.pi, math.pi, 0)):
        p = 2 * math.pi * 2.0 * t + off
        q[3 * leg + 1] -= 0.25 * math.sin(p)
        q[3 * leg + 2] += 0.25 * max(0.0, math.cos(p))
    return np.tile(q, (a.envs, 1)) if a.envs else q


log = {"t": [], "base_q": [], "joint_q": []}
sim_s, peak = 0.0, 0.0
frames = []
for i in range(a.steps):
    go2.control_dofs_position(pose(i * 0.005), idx)
    t1 = time.perf_counter()
    scene.step()
    sim_s += time.perf_counter() - t1
    if a.record:
        q = go2.get_qpos().cpu().numpy().ravel()
        log["t"].append((i + 1) * 0.005)
        log["base_q"].append(np.r_[q[:3], q[4:7], q[3]])
        log["joint_q"].append(q)
        f = go2.get_links_net_contact_force().cpu().numpy()
        peak = max(peak, float(np.linalg.norm(f, axis=-1).max()))
        if i % (a.steps // 4) == 0:
            frames.append(cam.render()[0])
r = {"label": "sim genesis_lab, not calibrated", "backend": a.backend, "envs": a.envs, "steps": a.steps, "build_s": round(build_s, 1), "steps_per_s": round(a.steps / sim_s, 1), "env_steps_per_s": round(a.steps * max(a.envs, 1) / sim_s, 0), "rtf_per_env": round(a.steps * 0.005 / sim_s, 2)}
if a.record:
    np.savez_compressed(ROOT / "out" / "typed_world.npz", t=np.array(log["t"]), base_q=np.array(log["base_q"]), joint_q=np.array(log["joint_q"]), meta=json.dumps({"world": world, "label": r["label"]}))
    r.update({"objects": len(world["objects"]), "solids": len(solids), "final_base_xyz": [round(float(v), 3) for v in log["base_q"][-1][:3]], "peak_link_contact_n": round(peak, 1), "export_kb": round((ROOT / "out" / "typed_world.gs").stat().st_size / 1024, 1), "record_kb": round((ROOT / "out" / "typed_world.npz").stat().st_size / 1024, 1)})
    from PIL import Image
    w, h = frames[0].shape[1], frames[0].shape[0]
    sheet = Image.new("RGB", (w * 2, h * 2))
    for k, f in enumerate(frames[:4]):
        sheet.paste(Image.fromarray(np.asarray(f, dtype=np.uint8)), ((k % 2) * w, (k // 2) * h))
    sheet.save(ROOT / "out" / "typed-world.png")
print("RESULT", json.dumps(r))
