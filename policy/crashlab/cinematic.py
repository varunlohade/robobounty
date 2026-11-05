"""Re-renders a recorded CrashLab run with a moving film camera. Physics comes only from the action log.

    cinematic.py record <run dir> <name>     replays the log, checks every step hash, keeps all physics substeps
    cinematic.py timeline <name>             prints what the target does per control step
    cinematic.py still <shot> <t>...         renders test stills
    cinematic.py clip <shot>                 renders the mp4, a manifest and a contact sheet

record writes a 270 MB .mjb per run. Delete it after rendering, and run record again before the next render.
Every drawn state is a real physics substep. No frame comes from interpolated poses.
This is a visual re-render. It is not what the robot's own camera saw.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("MUJOCO_GL", "cgl")

OUT = HERE.parent.parent / "design" / "cinematic"
CACHE = OUT / "_cache"


def record(run_dir, name):
    import numpy as np
    import mujoco
    import replay
    import scene as scene_schema
    import sim

    run = Path(run_dir)
    scene = scene_schema.load(run / "scene.json")
    stored = json.loads((run / "result.json").read_text())
    stored_final = json.loads((run / "final_state.json").read_text())
    rows, head = replay.read_log(run / "actions.jsonl", sim.step_digest)

    wrapper, _, _ = sim.prepare(scene)
    inner = wrapper._env.env
    world = inner.sim
    states, control = [world.data.qpos.copy()], [0]
    step_physics = world.step
    current = {"control": 0}

    def step_and_keep():
        step_physics()
        states.append(world.data.qpos.copy())
        control.append(current["control"])

    world.step = step_and_keep
    start_ok = sim.state_sha(world) == stored["start_state_sha256"]
    model_ok = sim.model_sha(world) == stored["model_state_sha256"]
    divergent = None
    success = False
    for n, row in enumerate(rows[1:], start=1):
        current["control"] = n
        _, _, _, _, info = wrapper.step(np.array(row["a"], dtype=np.float64))
        success = bool(info["is_success"])
        if divergent is None and sim.state_sha(world) != row["s"]:
            divergent = row["i"]
    final_sha_ok = sim.state_sha(world) == stored["final_state_sha256"]
    qpos_diff = float(np.max(np.abs(states[-1] - np.array(stored_final["qpos"]))))

    m = world.model._model
    CACHE.mkdir(parents=True, exist_ok=True)
    mujoco.mj_saveModel(m, str(CACHE / f"{name}.mjb"))
    np.savez_compressed(CACHE / f"{name}.npz", qpos=np.array(states), control=np.array(control),
                        timestep=m.opt.timestep)
    target = inner.get_object(sim.OBJECTS[sim.TARGET_OBJECT]).root_body
    goal = inner.get_object(sim.OBJECTS[sim.GOAL_OBJECT]).root_body
    check = {
        "run": str(run.resolve()), "task": stored["task"], "reason": stored["reason"], "steps": len(rows) - 1,
        "substeps": len(states) - 1, "chain_ok": head == stored["action_chain_head"],
        "model_match": model_ok, "start_state_match": start_ok, "first_divergent_step": divergent,
        "success_match": success == stored["success"], "final_state_sha_match": final_sha_ok,
        "final_qpos_max_abs_diff": qpos_diff, "target_body": target, "goal_body": goal,
        "gripper_body": "gripper0_eef",
    }
    check["match"] = bool(check["chain_ok"] and model_ok and start_ok and divergent is None
                          and check["success_match"] and final_sha_ok and qpos_diff == 0.0)
    (CACHE / f"{name}.check.json").write_text(json.dumps(check, indent=1) + "\n")
    wrapper.close()
    print(json.dumps(check, indent=1))
    return 0 if check["match"] else 1


def timeline(name):
    import mujoco
    import numpy as np

    m = mujoco.MjModel.from_binary_path(str(CACHE / f"{name}.mjb"))
    d = mujoco.MjData(m)
    rec = np.load(CACHE / f"{name}.npz")
    check = json.loads((CACHE / f"{name}.check.json").read_text())
    tb = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, check["target_body"])
    gb = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, check["goal_body"])
    eef = [b for b in range(m.nbody) if "eef" in (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or "")]
    sub = int((len(rec["qpos"]) - 1) / check["steps"])
    print("bodies with eef:", [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) for b in eef], "substeps per step", sub)
    for c in range(0, check["steps"] + 1, 5):
        d.qpos[:] = rec["qpos"][c * sub]
        mujoco.mj_kinematics(m, d)
        t, g = d.xpos[tb], d.xpos[gb]
        e = d.xpos[eef[0]] if eef else [0, 0, 0]
        print(f"{c:4d} {c/20:5.2f}s bowl {t[0]:+.3f} {t[1]:+.3f} {t[2]:.3f}  eef {e[0]:+.3f} {e[1]:+.3f} {e[2]:.3f}"
              f"  bowl-eef {np.linalg.norm(t-e):.3f}  plate {g[0]:+.3f} {g[1]:+.3f}")


W, H, FPS = 1920, 1080, 30
SAMPLES = 24  # draws per frame, averaged for depth of field, soft shadows and motion blur
SMOOTH_S = 1.0

# Keys: clip seconds -> value. Physics time keys are seconds of the recorded run.
SHOTS = {
    "failure": {
        "run": "failure", "seconds": 11.0, "aperture": 0.005,
        # Recorded: last contact 12.72 s, peak lift 1.6 cm at 12.65 s, bowl falls back by 12.85 s.
        "time": [(0.0, 9.6), (3.5, 12.0), (7.5, 13.0), (11.0, 14.0)],
        # lookat x y z, distance, azimuth, elevation, fovy
        "camera": [
            (0.0, (-0.05, 0.22, 1.01), 1.15, -100, -7, 26),
            (3.5, (-0.08, 0.24, 0.97), 0.80, -112, -6, 26),
            (7.5, (-0.09, 0.24, 0.945), 0.56, -122, -5, 26),
            (11.0, (-0.05, 0.24, 0.97), 0.80, -128, -5, 26),
        ],
    },
    "success": {
        "run": "success", "seconds": 10.0, "aperture": 0.005,
        # Recorded: grip closes by 2.78 s, peak lift 12.5 cm at 3.8 s, goal reached at 4.8 s.
        "time": [(0.0, 0.9), (4.0, 2.7), (7.0, 3.6), (10.0, 4.8)],
        "camera": [
            (0.0, (-0.16, 0.26, 1.07), 1.15, -115, -6, 26),
            (4.0, (-0.17, 0.30, 0.98), 0.72, -100, -5, 26),
            (7.0, (-0.06, 0.26, 1.04), 0.85, -88, -5, 26),
            (10.0, (0.05, 0.20, 0.97), 0.62, -74, -6, 26),
        ],
    },
}


def _smooth(y, n):
    """Hann filter with odd reflection, so the first and last values stay exact."""
    import numpy as np

    w = np.hanning(2 * n + 3)[1:-1]
    w = w / w.sum()
    pre = 2 * y[0] - y[n:0:-1]
    post = 2 * y[-1] - y[-2:-n - 2:-1]
    return np.array([np.convolve(np.r_[pre[:, c], y[:, c], post[:, c]], w, mode="valid")
                     for c in range(y.shape[1])]).T


def _path(shot):
    """Per-frame physics time and camera values, one row per frame."""
    import numpy as np

    n = round(shot["seconds"] * FPS)
    t = np.arange(n) / (n - 1) * shot["seconds"]
    half = round(SMOOTH_S * FPS / 2)
    keys = shot["time"]
    phys = _smooth(np.interp(t, [k[0] for k in keys], [k[1] for k in keys])[:, None], half)[:, 0]
    rows = np.array([[*k[1], *k[2:]] for k in shot["camera"]], dtype=float)
    times = [k[0] for k in shot["camera"]]
    cam = _smooth(np.stack([np.interp(t, times, rows[:, c]) for c in range(rows.shape[1])], axis=1), half)
    return phys, cam


class Film:
    def __init__(self, shot):
        import mujoco
        import numpy as np

        self.mj, self.np = mujoco, np
        self.shot = shot
        name = shot["run"]
        m = mujoco.MjModel.from_binary_path(str(CACHE / f"{name}.mjb"))
        self.m = m
        self.d = mujoco.MjData(m)
        rec = np.load(CACHE / f"{name}.npz")
        self.qpos = rec["qpos"]
        self.dt = float(rec["timestep"])
        m.vis.global_.offwidth, m.vis.global_.offheight = W, H
        m.vis.quality.shadowsize = 8192
        m.vis.quality.offsamples = 8
        m.vis.map.shadowscale = 1.0
        m.stat.extent = 3.0
        m.vis.map.znear = 0.005
        m.vis.map.zfar = 30.0
        m.vis.headlight.active = 0
        m.vis.rgba.haze[:] = [0.015, 0.016, 0.02, 1]
        self.r = mujoco.Renderer(m, H, W, max_geom=4000)
        self.r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 1
        self.r.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = 1
        self.opt = mujoco.MjvOption()
        self.opt.geomgroup[:] = 0
        self.opt.geomgroup[1] = 1
        self.opt.sitegroup[:] = 0
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.rng = np.random.default_rng(1)
        # Rig: warm key from the camera side, cool rim behind the robot, weak fill at table height.
        self.rig = [
            {"pos": (0.20, 1.40, 1.55), "at": (-0.05, 0.24, 0.97), "rgb": (0.86, 0.77, 0.66), "cut": 30, "exp": 9, "shadow": 1, "soft": 0.07, "amb": 0.03},
            {"pos": (-1.00, -0.70, 1.70), "at": (-0.10, 0.20, 1.00), "rgb": (0.26, 0.35, 0.50), "cut": 30, "exp": 6, "shadow": 0, "soft": 0.0, "amb": 0.0},
            {"pos": (0.30, 1.30, 1.00), "at": (-0.05, 0.24, 0.95), "rgb": (0.11, 0.105, 0.10), "cut": 40, "exp": 2, "shadow": 0, "soft": 0.0, "amb": 0.0},
        ]
        g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "table_texture")
        m.mat_reflectance[g] = 0.03
        m.mat_specular[g] = 0.05
        m.mat_rgba[g] = [0.85, 0.80, 0.74, 1]
        back = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "walls_mat")
        m.mat_rgba[back] = [0.07, 0.07, 0.08, 1]
        m.mat_specular[back] = 0.0
        # The maker's wordmark on the forearm is its own white mesh. Paint it the colour of the part beneath it.
        mark = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "robot0_Shell_001_001_003")
        m.mat_rgba[mark] = [0.25, 0.25, 0.25, 1]

    def _light(self):
        s, np = self.r.scene, self.np
        s.nlight = len(self.rig)
        for i, l in enumerate(self.rig):
            pos = np.array(l["pos"], float) + self.rng.normal(0, 1, 3) * l["soft"]
            v = np.array(l["at"], float) - pos
            sl = s.lights[i]
            sl.pos[:] = pos
            sl.dir[:] = v / np.linalg.norm(v)
            sl.type = self.mj.mjtLightType.mjLIGHT_SPOT
            sl.castshadow = l["shadow"]
            sl.cutoff = l["cut"]
            sl.exponent = l["exp"]
            sl.attenuation[:] = (1, 0, 0)
            sl.ambient[:] = [l["amb"]] * 3
            sl.diffuse[:] = l["rgb"]
            sl.specular[:] = [0.35 * c for c in l["rgb"]]

    def _sample_disc(self):
        np = self.np
        a, r = self.rng.uniform(0, 2 * math.pi), math.sqrt(self.rng.uniform())
        return r * math.cos(a), r * math.sin(a)

    def frame(self, phys_t, c, shutter_s):
        np, mj = self.np, self.mj
        total = np.zeros((H, W, 3), np.float32)
        used = []
        for s in range(SAMPLES):
            t = phys_t + ((s + self.rng.uniform()) / SAMPLES - 0.5) * shutter_s
            k = int(np.clip(round(t / self.dt), 0, len(self.qpos) - 1))
            used.append(k)
            self.d.qpos[:] = self.qpos[k]
            mj.mj_kinematics(self.m, self.d)
            dx, dy = self._sample_disc()
            dist = c[3]
            self.cam.lookat[:] = c[:3]
            self.cam.distance = dist
            self.cam.azimuth = c[4] + math.degrees(self.shot["aperture"] * dx / (dist * math.cos(math.radians(c[5]))))
            self.cam.elevation = c[5] + math.degrees(self.shot["aperture"] * dy / dist)
            self.m.vis.global_.fovy = c[6]
            self.r.update_scene(self.d, self.cam, self.opt)
            self._light()
            total += self.r.render()
        return _grade(np, total / SAMPLES / 255.0, self.rng), used


def _grade(np, im, rng):
    """Tone curve, slight warm highlights and cool shadows, vignette, dither."""
    x = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    y = np.linspace(-0.56, 0.56, H, dtype=np.float32)[:, None]
    vig = 1 - 0.42 * np.clip(x * x + y * y, 0, 1.3) ** 1.3
    im = im * vig[..., None] * 1.12
    im = np.clip(im, 0, 1)
    im = im * im * (3 - 2 * im) * 0.55 + im * 0.45
    luma = im.mean(axis=2, keepdims=True)
    tint = np.array([1.03, 1.0, 0.95], np.float32) * luma + np.array([0.96, 1.0, 1.06], np.float32) * (1 - luma)
    im = im * tint
    im = im + rng.normal(0, 0.006, (H, W, 1)).astype(np.float32)
    return (np.clip(im, 0, 1) * 255 + 0.5).astype(np.uint8)


def _shutter(phys, i):
    """A 180-degree shutter in recorded time."""
    a, b = phys[max(i - 1, 0)], phys[min(i + 1, len(phys) - 1)]
    return (b - a) / (2 if 0 < i < len(phys) - 1 else 1) / 2


def still(shot_name, times):
    import numpy as np
    from PIL import Image

    shot = SHOTS[shot_name]
    phys, cam = _path(shot)
    film = Film(shot)
    d = CACHE / "stills"
    d.mkdir(exist_ok=True)
    for t in times:
        i = min(round(t * FPS), len(phys) - 1)
        t0 = time.time()
        im, _ = film.frame(phys[i], cam[i], _shutter(phys, i))
        path = d / f"{shot_name}_{t:05.2f}.png"
        Image.fromarray(im).resize((W // 2, H // 2)).save(path)
        print(path, f"phys {phys[i]:.2f}s render {time.time() - t0:.2f}s")


def clip(shot_name):
    import mujoco
    import numpy as np
    from PIL import Image

    shot = SHOTS[shot_name]
    phys, cam = _path(shot)
    film = Film(shot)
    mp4 = OUT / f"{shot_name}.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    frames, t0 = [], time.time()
    for i in range(len(phys)):
        im, used = film.frame(phys[i], cam[i], _shutter(phys, i))
        enc.stdin.write(im.tobytes())
        c = cam[i]
        az, el = math.radians(c[4]), math.radians(c[5])
        forward = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        eye = c[:3] - forward * c[3]
        gid = np.zeros(1, np.int32)
        hit = mujoco.mj_ray(film.m, film.d, eye, forward, np.array([0, 1, 0, 0, 0, 0], np.uint8), 1, -1, gid)
        frames.append({"frame": i, "physics_s": round(float(phys[i]), 4), "substep_first": min(used), "substep_last": max(used),
                       "eye": [round(float(x), 4) for x in eye], "first_hit_m": round(float(hit), 4),
                       "mean_luma": round(float(im.mean()), 2)})
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    seconds = time.time() - t0

    check = json.loads((CACHE / f"{shot['run']}.check.json").read_text())
    stored_final = json.loads((Path(check["run"]) / "final_state.json").read_text())
    last = frames[-1]["substep_last"]
    manifest = {
        "note": "Visual re-render of recorded physics. Not what the robot's own camera saw.",
        "clip": mp4.name, "render_seconds": round(seconds, 1), "samples_per_frame": SAMPLES, "fps": FPS,
        "replay_check": check,
        "last_frame_substep": last, "total_substeps": len(film.qpos) - 1,
        "last_frame_qpos_vs_final_state": float(np.max(np.abs(film.qpos[last] - np.array(stored_final["qpos"])))),
        "physics_monotonic": bool(np.all(np.diff(phys) > 0)),
        "min_mean_luma": min(f["mean_luma"] for f in frames),
        "min_first_hit_m": min(f["first_hit_m"] for f in frames if f["first_hit_m"] >= 0),
        "min_eye_z": min(f["eye"][2] for f in frames),
        "frames": frames,
    }
    (OUT / f"{shot_name}.manifest.json").write_text(json.dumps(manifest, indent=0) + "\n")

    picks = [round(x) for x in np.linspace(0, len(phys) - 1, 9)]
    sheet = Image.new("RGB", (640 * 3, 360 * 3))
    for n, i in enumerate(picks):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-vf", f"select=eq(n\\,{i}),scale=640:360",
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        sheet.paste(Image.frombytes("RGB", (640, 360), raw), ((n % 3) * 640, (n // 3) * 360))
    sheet.save(OUT / f"{shot_name}_sheet.png")
    print({k: v for k, v in manifest.items() if k not in ("frames", "replay_check")})
    print("frames in sheet", picks, "physics", [frames[i]["physics_s"] for i in picks])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("run_dir"); r.add_argument("name")
    t = sub.add_parser("timeline"); t.add_argument("name")
    st = sub.add_parser("still"); st.add_argument("shot"); st.add_argument("t", nargs="+", type=float)
    cl = sub.add_parser("clip"); cl.add_argument("shot")
    a = ap.parse_args()
    if a.cmd == "still":
        still(a.shot, a.t)
    elif a.cmd == "clip":
        clip(a.shot)
    else:
        sys.exit(record(a.run_dir, a.name) if a.cmd == "record" else timeline(a.name))
