"""Checks with a known answer, simulated, not calibrated. checks.py slope: a block on a 20 degree slope, Genesis against the formula and MuJoCo. checks.py mjcf: a MJCF file loaded by Genesis and MuJoCo, same passive run.
Block on a slope: tan(20)=0.364. Friction below that slides at g(sin - mu cos). Friction above that stays.
"""
import json, math, sys, time
import numpy as np


def slope_genesis(mu):
    scene = gs.Scene(sim_options=gs.options.SimOptions(dt=0.002, substeps=1), show_viewer=False)
    ang = 20.0
    r = math.radians(ang)
    scene.add_entity(gs.morphs.Box(pos=(0, 0, 0), size=(30, 2, 0.1), euler=(0, ang, 0), fixed=True), material=gs.materials.Rigid(friction=mu))
    n = np.array([math.sin(r), 0, math.cos(r)])
    block = scene.add_entity(gs.morphs.Box(pos=tuple(n * (0.05 + 0.05 + 0.0005)), size=(0.2, 0.2, 0.1), euler=(0, ang, 0)), material=gs.materials.Rigid(friction=mu, rho=1000.0))
    scene.build()
    start = block.get_pos().cpu().numpy().ravel().copy()
    for _ in range(500):
        scene.step()
    d = float(np.linalg.norm(block.get_pos().cpu().numpy().ravel() - start))
    return d


def slope_mujoco(mu):
    import mujoco
    ang = 20.0
    r = math.radians(ang)
    n = (math.sin(r), 0, math.cos(r))
    z = 0.1005
    xml = f"""<mujoco><option timestep="0.002" cone="elliptic"/><worldbody>
<geom type="box" size="15 1 0.05" euler="0 {ang} 0" friction="{mu} 0 0"/>
<body pos="{n[0]*z} 0 {n[2]*z}" euler="0 {ang} 0"><freejoint/><geom type="box" size="0.1 0.1 0.05" density="1000" friction="{mu} 0 0"/></body>
</worldbody></mujoco>"""
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    s = d.qpos[:3].copy()
    for _ in range(500):
        mujoco.mj_step(m, d)
    return float(np.linalg.norm(d.qpos[:3] - s))


mode = sys.argv[1]
import genesis as gs
gs.init(backend=gs.cpu, seed=0, logging_level="warning")
if mode == "slope":
    rows = []
    r = math.radians(20)
    for mu in (0.1, 0.2, 0.3, 0.5, 0.8):
        a = 9.81 * (math.sin(r) - mu * math.cos(r))
        rows.append({"mu": mu, "formula_m_at_1s": round(max(0.0, 0.5 * a), 4), "genesis_m": round(slope_genesis(mu), 4), "mujoco_m": round(slope_mujoco(mu), 4)})
    print("RESULT", json.dumps({"label": "sim genesis_lab, not calibrated", "slope_deg": 20, "rows": rows}))
if mode == "mjcf":
    import importlib.util, mujoco, os
    from pathlib import Path
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent / "highrise"))
    import world as W
    world = W.load(str(root.parent / "highrise" / "worlds" / "nominal.json"))
    xml = W.build_xml(world)
    path = root / "out" / "highrise_nominal.xml"
    path.write_text(xml)
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    rid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "robot")
    tid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_TENDON, "tether")
    mujoco.mj_forward(m, d)
    z0 = float(d.xpos[rid][2])
    n = int(round(5.0 / m.opt.timestep))
    t = time.perf_counter()
    trace = []
    for i in range(n):
        mujoco.mj_step(m, d)
        if i % (n // 5) == n // 5 - 1:
            trace.append(round(float(d.xpos[rid][2]), 3))
    mj = {"timestep": float(m.opt.timestep), "steps_per_s": round(n / (time.perf_counter() - t), 1), "robot_z_start": round(z0, 3), "robot_z_every_1s": trace, "robot_mass_kg": round(float(m.body_subtreemass[rid]), 3), "ntendon": int(m.ntendon), "ngeom": int(m.ngeom), "tether_force_end_n": round(float(np.abs(d.efc_force).max() if d.nefc else 0.0), 1)}
    scene = gs.Scene(sim_options=gs.options.SimOptions(dt=float(m.opt.timestep), substeps=1), show_viewer=False)
    e = scene.add_entity(gs.morphs.MJCF(file=str(path)))
    scene.build()
    links = [l.name for l in e.links]
    rl = e.get_link("robot")
    t = time.perf_counter()
    gtrace = []
    z0g = float(rl.get_pos().cpu().numpy().ravel()[2])
    for i in range(n):
        scene.step()
        if i % (n // 5) == n // 5 - 1:
            gtrace.append(round(float(rl.get_pos().cpu().numpy().ravel()[2]), 3))
    g = {"steps_per_s": round(n / (time.perf_counter() - t), 1), "robot_z_start": round(z0g, 3), "robot_z_every_1s": gtrace, "entity_mass_kg": round(float(e.get_mass()), 3), "robot_link_mass_kg": round(float(rl.get_mass()), 3), "links": len(links), "geoms": e.n_geoms}
    print("RESULT", json.dumps({"label": "sim genesis_lab, not calibrated", "note": "passive 5 s, suction off, same MJCF", "mujoco": mj, "genesis": g}))
