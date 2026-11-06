"""Loose sand with MPM, simulated, not calibrated. sand.py --backend cpu|metal --mode column|sink --rho-body R --seed N --grid G --steps N --frames DIR --g G
column: a sand column collapses. A real pile has a slope near the friction angle, a liquid would spread flat.
sink: a sphere drops on a bed. A heavy sphere must sink further than a light one.
"""
import argparse, hashlib, json, math, time
from pathlib import Path
import numpy as np
ap = argparse.ArgumentParser()
ap.add_argument("--backend", default="cpu")
ap.add_argument("--mode", default="column")
ap.add_argument("--rho-body", type=float, default=2000.0)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--grid", type=float, default=64)
ap.add_argument("--steps", type=int, default=400)
ap.add_argument("--g", type=float, default=3.71)
ap.add_argument("--friction-angle", type=float, default=35.0)
ap.add_argument("--frames", default="")
ap.add_argument("--tag", default="")
a = ap.parse_args()
import genesis as gs
gs.init(backend=getattr(gs, a.backend), seed=a.seed, logging_level="warning", precision="32")
dt = 2e-3
t0 = time.perf_counter()
scene = gs.Scene(
    sim_options=gs.options.SimOptions(dt=dt, substeps=10, gravity=(0, 0, -a.g)),
    mpm_options=gs.options.MPMOptions(lower_bound=(-0.6, -0.6, -0.1), upper_bound=(0.6, 0.6, 0.8), grid_density=a.grid),
    vis_options=gs.options.VisOptions(visualize_mpm_boundary=False),
    show_viewer=False,
)
scene.add_entity(gs.morphs.Plane(), material=gs.materials.Rigid(coup_friction=2.0))
sandm = gs.materials.MPM.Sand(rho=1500.0, E=1e6, nu=0.2, friction_angle=a.friction_angle)
surf = gs.surfaces.Rough(color=(0.76, 0.42, 0.22), vis_mode="particle")
body = None
if a.mode == "column":
    sand = scene.add_entity(material=sandm, morph=gs.morphs.Box(pos=(0, 0, 0.17), size=(0.2, 0.2, 0.3)), surface=surf)
else:
    sand = scene.add_entity(material=sandm, morph=gs.morphs.Box(pos=(0, 0, 0.09), size=(0.4, 0.4, 0.16)), surface=surf)
    body = scene.add_entity(material=gs.materials.Rigid(rho=a.rho_body, coup_friction=0.5), morph=gs.morphs.Sphere(pos=(0, 0, 0.32), radius=0.07), surface=gs.surfaces.Rough(color=(0.8, 0.8, 0.85)))
cam = scene.add_camera(res=(800, 600), pos=(0.9, -0.9, 0.6), lookat=(0, 0, 0.08), fov=40, GUI=False) if a.frames else None
scene.build()
build_s = time.perf_counter() - t0
print("particles", sand.n_particles)
frames, sim_s, trace = [], 0.0, []
every = max(1, a.steps // 4)
for i in range(a.steps):
    t1 = time.perf_counter()
    scene.step()
    sim_s += time.perf_counter() - t1
    if cam is not None and (i % every == 0 or i == a.steps - 1):
        frames.append(cam.render()[0])
    if body is not None and i % 50 == 49:
        trace.append(round(float(body.get_pos().cpu().numpy().ravel()[2]), 4))
p = sand.get_particles_pos().cpu().numpy().reshape(-1, 3)
v = sand.get_particles_vel().cpu().numpy().reshape(-1, 3)
out = {"label": "sim genesis_lab, not calibrated", "mode": a.mode, "backend": a.backend, "seed": a.seed, "grid": a.grid, "g": a.g, "friction_angle": a.friction_angle,
       "particles": int(sand.n_particles), "dt": dt, "substeps": 10, "steps": a.steps, "sim_time_s": round(a.steps * dt, 3), "build_s": round(build_s, 1), "wall_s": round(sim_s, 1),
       "steps_per_s": round(a.steps / sim_s, 1), "rtf": round(a.steps * dt / sim_s, 4), "state_sha256": hashlib.sha256(p.astype(np.float32).tobytes()).hexdigest()[:16],
       "mean_speed_mps": round(float(np.linalg.norm(v, axis=1).mean()), 4), "nan": bool(np.isnan(p).any()), "min_z": round(float(p[:, 2].min()), 4)}
if a.mode == "column":
    r = np.hypot(p[:, 0], p[:, 1])
    bins = np.arange(0, 0.5, 0.02)
    tops = []
    for lo in bins:
        m = (r >= lo) & (r < lo + 0.02)
        tops.append(float(np.percentile(p[m, 2], 98)) if m.sum() > 20 else float("nan"))
    tops = np.array(tops)
    ok = ~np.isnan(tops) & (tops > 0.03)
    rr = (bins + 0.01)[ok]
    tt = tops[ok]
    out["peak_height_m"] = round(float(np.nanmax(tops)), 3)
    out["runout_m_p99"] = round(float(np.percentile(r, 99)), 3)
    if ok.sum() >= 3:
        mid = (tt < 0.8 * tt.max()) & (tt > 0.15 * tt.max())
        if mid.sum() >= 3:
            out["pile_slope_deg"] = round(float(math.degrees(math.atan(-np.polyfit(rr[mid], tt[mid], 1)[0]))), 1)
else:
    out["rho_body"] = a.rho_body
    out["body_z_trace_m"] = trace
    out["bed_top_start_m"] = 0.17
    out["body_bottom_final_m"] = round(trace[-1] - 0.07, 4)
print("RESULT", json.dumps(out))
if frames:
    from PIL import Image
    w, h = frames[0].shape[1], frames[0].shape[0]
    n = len(frames[-4:])
    sheet = Image.new("RGB", (w * 2, h * 2))
    for k, f in enumerate(frames[-4:]):
        sheet.paste(Image.fromarray(np.asarray(f, dtype=np.uint8)), ((k % 2) * w, (k // 2) * h))
    d = Path(a.frames); d.mkdir(parents=True, exist_ok=True)
    sheet.save(d / f"sand-{a.mode}{a.tag}-{a.backend}.png")
