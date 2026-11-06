"""Water with SPH around a sphere, simulated, not calibrated. water.py --backend cpu|metal --rho-body R --psize P --steps N --frames DIR
A check with a known answer: a sphere lighter than water must float, a heavier one must sink. A sphere at rho 500 floats with its centre near the surface.
The tank is the SPH domain bound.
"""
import argparse, hashlib, json, time
from pathlib import Path
import numpy as np
ap = argparse.ArgumentParser()
ap.add_argument("--backend", default="cpu")
ap.add_argument("--rho-body", type=float, default=500.0)
ap.add_argument("--psize", type=float, default=0.02)
ap.add_argument("--steps", type=int, default=500)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--solver", default="WCSPH")
ap.add_argument("--frames", default="")
ap.add_argument("--tag", default="")
a = ap.parse_args()
import genesis as gs
gs.init(backend=getattr(gs, a.backend), seed=a.seed, logging_level="warning", precision="32")
dt = 4e-3
t0 = time.perf_counter()
scene = gs.Scene(
    sim_options=gs.options.SimOptions(dt=dt, substeps=10),
    sph_options=gs.options.SPHOptions(lower_bound=(-0.4, -0.4, 0.0), upper_bound=(0.4, 0.4, 1.0), particle_size=a.psize, pressure_solver=a.solver),
    vis_options=gs.options.VisOptions(visualize_sph_boundary=True),
    show_viewer=False,
)
scene.add_entity(gs.morphs.Plane())
water = scene.add_entity(material=gs.materials.SPH.Liquid(rho=1000.0), morph=gs.morphs.Box(pos=(0, 0, 0.2), size=(0.76, 0.76, 0.36)), surface=gs.surfaces.Glass(color=(0.3, 0.55, 0.9), vis_mode="particle"))
body = scene.add_entity(material=gs.materials.Rigid(rho=a.rho_body), morph=gs.morphs.Sphere(pos=(0, 0, 0.45), radius=0.08), surface=gs.surfaces.Rough(color=(0.95, 0.5, 0.1)))
cam = scene.add_camera(res=(800, 600), pos=(1.1, -1.1, 0.8), lookat=(0, 0, 0.2), fov=40, GUI=False) if a.frames else None
scene.build()
build_s = time.perf_counter() - t0
print("particles", water.n_particles, "body mass", float(body.get_mass()))
frames, sim_s, trace = [], 0.0, []
every = max(1, a.steps // 4)
for i in range(a.steps):
    t1 = time.perf_counter()
    scene.step()
    sim_s += time.perf_counter() - t1
    if cam is not None and (i % every == 0 or i == a.steps - 1):
        frames.append(cam.render()[0])
    if i % 50 == 49:
        trace.append(round(float(body.get_pos().cpu().numpy().ravel()[2]), 3))
p = water.get_particles_pos().cpu().numpy().reshape(-1, 3)
top = float(np.percentile(p[:, 2], 99))
out = {"label": "sim genesis_lab, not calibrated", "backend": a.backend, "solver": a.solver, "rho_body": a.rho_body, "psize": a.psize, "particles": int(water.n_particles), "dt": dt, "substeps": 10,
       "steps": a.steps, "sim_time_s": round(a.steps * dt, 3), "build_s": round(build_s, 1), "wall_s": round(sim_s, 1), "steps_per_s": round(a.steps / sim_s, 1), "rtf": round(a.steps * dt / sim_s, 4),
       "body_z_trace_m": trace, "water_top_p99_m": round(top, 3), "water_mean_z": round(float(p[:, 2].mean()), 3), "nan": bool(np.isnan(p).any()), "state_sha256": hashlib.sha256(p.astype(np.float32).tobytes()).hexdigest()[:16]}
print("RESULT", json.dumps(out))
if frames:
    from PIL import Image
    w, h = frames[0].shape[1], frames[0].shape[0]
    sheet = Image.new("RGB", (w * 2, h * 2))
    for k, f in enumerate(frames[-4:]):
        sheet.paste(Image.fromarray(np.asarray(f, dtype=np.uint8)), ((k % 2) * w, (k // 2) * h))
    d = Path(a.frames); d.mkdir(parents=True, exist_ok=True)
    sheet.save(d / f"water{a.tag}-{a.backend}.png")
