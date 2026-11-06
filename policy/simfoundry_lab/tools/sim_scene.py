"""Loads the extracted example scene into plain MuJoCo, reports scale, mass, gaps and settling, then drops a box and the ANYmal copy and writes frames.
Simulated. Scene is NVIDIA's published example, not built on this Mac. Physics numbers are from this MuJoCo setup, not OmniGibson. Friction 0.75 is this script's choice: the USD files carry none.
Usage: sim_scene.py <work_dir> <out_mp4_stem>
"""
import json, re, subprocess, sys
from pathlib import Path
import numpy as np
import mujoco

WORK = Path(sys.argv[1]).resolve(); OUT = sys.argv[2]
SCENE = WORK / "scene"; man = json.load(open(SCENE / "manifest.json"))
DT = 0.002; FPS = 30
SETTLE_S, BOX_T, ROBOT_T, END_T = 3.0, 3.0, 5.0, 9.0
BOX_SIZE, BOX_MASS = 0.05, 1.0
BOX_POS = (0.59, -0.21, 0.35)
ROBOT_POS = (0.92, 0.05, 0.75)
FAR = (40.0, 40.0)

def look(pos, target):
    f = np.array(target, float) - pos; f /= np.linalg.norm(f)
    r = np.cross(f, [0, 0, 1]); r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return f'pos="{pos[0]} {pos[1]} {pos[2]}" xyaxes="{r[0]} {r[1]} {r[2]} {u[0]} {u[1]} {u[2]}"'

def quat(xyzw): return f"{xyzw[3]} {xyzw[0]} {xyzw[1]} {xyzw[2]}"

asset, bodies = [], []
for o in man["objects"]:
    n = o["name"]; d = SCENE / n
    asset.append(f'<texture name="t_{n}" type="2d" file="{d}/tex.png"/><material name="m_{n}" texture="t_{n}"/>')
    asset.append(f'<mesh name="v_{n}" file="{d}/visual.obj" inertia="shell"/>')
    hulls = ""
    for i, h in enumerate(o["hulls"]):
        asset.append(f'<mesh name="h_{n}_{i}" file="{d}/{h}" inertia="shell"/>')
        hulls += f'<geom type="mesh" mesh="h_{n}_{i}" group="3" contype="1" conaffinity="3" friction="0.75 0.005 0.0001" rgba="1 0.2 0.8 0.55" mass="0"/>'
    s = np.array(o["size"]); m = o["mass"]
    I = m / 12 * np.array([s[1]**2 + s[2]**2, s[0]**2 + s[2]**2, s[0]**2 + s[1]**2])
    bodies.append(f'<body name="{n}" pos="{" ".join(map(str, o["pos"]))}" quat="{quat(o["ori_xyzw"])}"><freejoint name="j_{n}"/>'
                  f'<inertial pos="{" ".join(map(str, o["com"]))}" mass="{m}" diaginertia="{I[0]} {I[1]} {I[2]}"/>'
                  f'<geom type="mesh" mesh="v_{n}" material="m_{n}" group="1" contype="0" conaffinity="0" mass="0"/>{hulls}</body>')

bg = man["background"]
asset.append(f'<texture name="t_bg" type="2d" file="{SCENE}/background/tex.png"/><material name="m_bg" texture="t_bg" emission="0.9" specular="0" shininess="0"/>'
             f'<mesh name="v_bg" file="{SCENE}/background/visual.obj" inertia="shell"/>')

rob = (WORK / "robot/anymal.xml").read_text()
rob_body = re.search(r"<worldbody>\s*(.*?)\s*</worldbody>", rob, re.S).group(1)
rob_act = re.search(r"<actuator>.*?</actuator>", rob, re.S)
rob_body = re.sub(r'contype="\d+"', "", rob_body); rob_body = re.sub(r'conaffinity="\d+"', "", rob_body)
rob_body = re.sub(r"<geom ", '<geom contype="2" conaffinity="0" group="1" rgba="0.15 0.15 0.17 1" ', rob_body)
rob_body = re.sub(r'(<geom [^>]*?)rgba="[^"]*"([^>]*?)rgba="', r'\1\2rgba="', rob_body)
parts = json.load(open(WORK / "robot/visuals/parts.json"))
for i, part in enumerate(parts):
    asset.append(f'<mesh name="rv_{i}" file="{WORK}/robot/visuals/{part["file"]}" inertia="shell"/>')
    body = "_" + part["body"].strip("/").replace("/", "_")
    tag = f'<body name="{body}"'
    at = rob_body.index(tag); close = rob_body.index(">", at) + 1
    rob_body = rob_body[:close] + f'<geom type="mesh" mesh="rv_{i}" group="1" contype="0" conaffinity="0" mass="0" rgba="0.72 0.3 0.12 1"/>' + rob_body[close:]
rob_body = re.sub(r'(<geom contype="2"[^>]*?)group="1"', r'\1group="3"', rob_body)
rob_body = rob_body.replace('pos="0 0 0.8"', f'pos="{FAR[0]} {FAR[1]} 1"', 1)

xml = f"""<mujoco><compiler angle="radian" inertiafromgeom="auto"/><option timestep="{DT}" gravity="0 0 -9.81" integrator="implicitfast"/>
<visual><global offwidth="1280" offheight="720"/><headlight ambient="0.45 0.45 0.45" diffuse="0.45 0.45 0.45" specular="0.05 0.05 0.05"/><quality shadowsize="4096"/></visual>
<asset>{''.join(asset)}</asset><worldbody>
<geom name="floor" type="plane" size="30 30 0.1" pos="0 0 {man['ground_z']}" group="4" contype="1" conaffinity="3" friction="0.75 0.005 0.0001" rgba="0.4 0.4 0.4 0.3"/>
<geom name="bg" type="mesh" mesh="v_bg" material="m_bg" pos="{' '.join(map(str, bg['pos']))}" quat="{quat(bg['ori_xyzw'])}" group="2" contype="0" conaffinity="0"/>
<light pos="0.5 0 2" dir="0 0 -1" diffuse="0.5 0.5 0.5" castshadow="true"/>
<camera name="view" {look((0.02, -0.62, 0.42), (0.57, 0.03, 0.0))} fovy="50"/>
<camera name="wide" {look((-0.45, -1.35, 1.0), (0.75, 0.05, 0.1))} fovy="50"/>
<body name="box" pos="{FAR[0]} {FAR[1] - 3} 1"><freejoint name="j_box"/><geom type="box" size="{BOX_SIZE} {BOX_SIZE} {BOX_SIZE}" mass="{BOX_MASS}" group="1" contype="1" conaffinity="3" friction="0.75 0.005 0.0001" rgba="0.9 0.9 0.92 1"/></body>
{''.join(bodies)}{rob_body}</worldbody>{rob_act.group(0) if rob_act else ''}</mujoco>"""
(WORK / "scene_mj.xml").write_text(xml)
m = mujoco.MjModel.from_xml_path(str(WORK / "scene_mj.xml")); d = mujoco.MjData(m)
mujoco.mj_forward(m, d)
print("nbody", m.nbody, "ngeom", m.ngeom, "nu", m.nu, "total mass", round(float(m.body_mass.sum()), 2))

names = [o["name"] for o in man["objects"]]
report = {"label": "SIMULATED. NVIDIA published example, not built here. Never claimed to match the real place.", "objects": {}}
ids = {n: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in names}
def hull_pts(n):
    out = []
    for g in range(m.ngeom):
        if m.geom_bodyid[g] == ids[n] and m.geom_contype[g]:
            mid = m.geom_dataid[g]; a = m.mesh_vertadr[mid]; c = m.mesh_vertnum[mid]
            v = m.mesh_vert[a:a + c]; out.append(d.geom_xpos[g] + v @ d.geom_xmat[g].reshape(3, 3).T)
    return np.vstack(out)
ground = man["ground_z"]
for o in man["objects"]:
    n = o["name"]; p = hull_pts(n); ext = p.max(0) - p.min(0)
    report["objects"][n] = dict(size_cm=[round(x * 100, 1) for x in sorted(o["size"], reverse=True)], mass_kg=round(o["mass"], 3), hulls=len(o["hulls"]),
        start_gap_to_ground_mm=round(float(p[:, 2].min() - ground) * 1000, 1), start_pos=d.xpos[ids[n]].round(4).tolist())
report["start_contacts"] = int(d.ncon)
report["start_worst_penetration_mm"] = round(float(min([d.contact[i].dist for i in range(d.ncon)] + [0.0])) * 1000, 2)

box_j = m.joint("j_box").qposadr[0]; box_v = m.joint("j_box").dofadr[0]
rob_j = m.joint("joint_1").qposadr[0]; rob_v = m.joint("joint_1").dofadr[0]
home = d.qpos.copy()
if m.nu:
    act_j = [m.actuator_trnid[i, 0] for i in range(m.nu)]
    d.ctrl[:] = [home[m.jnt_qposadr[j]] for j in act_j]
park_box = home[box_j:box_j + 7].copy(); park_rob = home[rob_j:rob_j + 7].copy()

def render_setup():
    r = mujoco.Renderer(m, 720, 1280)
    o = mujoco.MjvOption(); mujoco.mjv_defaultOption(o)
    o.geomgroup[:] = [0, 1, 1, 0, 0, 0]
    h = mujoco.MjvOption(); mujoco.mjv_defaultOption(h)
    h.geomgroup[:] = [0, 0, 0, 1, 1, 0]
    return r, o, h
r, opt, hopt = render_setup()
def writer(name):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", name], stdin=subprocess.PIPE)
w = writer(f"{OUT}_view.mp4"); wh = writer(f"{OUT}_hull.mp4"); ww = writer(f"{OUT}_wide.mp4")
every = round(1 / FPS / DT); step = 0; box_on = rob_on = False; settled = False; max_err = 0.0
while d.time < END_T:
    if not box_on and d.time >= BOX_T:
        d.qpos[box_j:box_j + 3] = BOX_POS; d.qpos[box_j + 3:box_j + 7] = [1, 0, 0, 0]; d.qvel[box_v:box_v + 6] = 0; box_on = True
    if not rob_on and d.time >= ROBOT_T:
        d.qpos[rob_j:rob_j + 3] = ROBOT_POS; d.qvel[rob_v:rob_v + 6] = 0; rob_on = True
    if not box_on: d.qpos[box_j:box_j + 7] = park_box; d.qvel[box_v:box_v + 6] = 0
    if not rob_on: d.qpos[rob_j:rob_j + 7] = park_rob; d.qvel[rob_v:rob_v + 6] = 0
    if box_on and "box_before_robot" not in report and d.time >= ROBOT_T - 0.01:
        report["box_before_robot"] = d.qpos[box_j:box_j + 3].round(3).tolist()
        report["plate_moved_by_box_cm"] = round(float(np.linalg.norm(d.xpos[ids[names[1]]] - np.array(report["objects"][names[1]]["start_pos"]))) * 100, 1)
    if not settled and d.time >= SETTLE_S:
        settled = True
        for n in names:
            e = report["objects"][n]
            e["moved_after_3s_mm"] = round(float(np.linalg.norm(d.xpos[ids[n]] - np.array(e["start_pos"]))) * 1000, 1)
            e["speed_at_3s_mm_s"] = round(float(np.linalg.norm(d.cvel[ids[n]][3:])) * 1000, 2)
    if step % every == 0:
        for wr, cam, o in ((w, "view", opt), (wh, "view", hopt), (ww, "wide", opt)):
            r.update_scene(d, camera=cam, scene_option=o); wr.stdin.write(r.render().tobytes())
    mujoco.mj_step(m, d); step += 1
    if np.isnan(d.qpos).any(): report["nan_at_s"] = float(d.time); break
for x in (w, wh, ww): x.stdin.close(); x.wait()
report["end_box_pos"] = d.qpos[box_j:box_j + 3].round(3).tolist(); report["box_landed_on_plate_top_mm"] = round(float(d.qpos[box_j + 2] - BOX_SIZE - ground) * 1000, 1)
report["end_robot_pos"] = d.qpos[rob_j:rob_j + 3].round(3).tolist()
for n in names:
    report["objects"][n]["moved_total_cm"] = round(float(np.linalg.norm(d.xpos[ids[n]] - np.array(report["objects"][n]["start_pos"]))) * 100, 1)
json.dump(report, open(f"{OUT}_report.json", "w"), indent=1); print(json.dumps(report, indent=1))
