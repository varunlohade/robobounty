"""Runs inside sandbox-exec, started by harness.py. check <scene.xml> | trial <scene.xml> <seed> <out> | replay <out> | probe <path>."""
import hashlib
import json
import math
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

try:
    os.nice(15)
except PermissionError:
    pass
_cpu, _file = int(os.environ["GENERATOR_CPU_S"]), int(os.environ["GENERATOR_FILE_MB"]) * 2**20
resource.setrlimit(resource.RLIMIT_CPU, (_cpu, _cpu))
resource.setrlimit(resource.RLIMIT_FSIZE, (_file, _file))
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

# mujoco's import asks sysctl about Rosetta, and the sandbox forbids new processes. Same answer as policy/crashlab/sandbox_worker.py.
_real_run = subprocess.run
subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"0", stderr=b"")
import mujoco  # noqa: E402
subprocess.run = _real_run

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as G  # noqa: E402
import scene_sim as X  # noqa: E402

SETTLE_S = 3.0
SANE_DRIFT_M = 0.10
SANE_ENERGY_J = 5.0
MIN_REACH_SHARE = 0.20

MUJOCO_WORDS = ((r"repeated name", "Two elements share one name."), (r"material|texture", "MuJoCo rejected a material or texture."),
                (r"size|mass|inertia", "MuJoCo rejected a geom size."), (r"quat|euler|orientation", "MuJoCo rejected a rotation."))


def fail(stage, code, plain, **extra):
    return {"ok": False, "stage": stage, "code": code, "plain": plain, **extra}


def compile_error(text):
    for pattern, plain in MUJOCO_WORDS:
        if re.search(pattern, text, re.I):
            return plain
    return "MuJoCo could not compile the scene."


def check(scene_path):
    text = Path(scene_path).read_bytes()
    t0 = time.time()
    try:
        merged = X.install(text)
    except G.Reject as e:
        return fail("gate", e.code, e.plain)
    try:
        model = mujoco.MjModel.from_xml_string(merged)
    except Exception as e:  # MuJoCo raises ValueError; its text may quote the file, so it stays in the log and out of the repair prompt
        return fail("compile", "compile_failed", compile_error(str(e)), raw_mujoco=str(e)[:500])
    world = X.base_world()
    compile_s = round(time.time() - t0, 3)
    base = {"compile_s": compile_s, "nbody": model.nbody, "ngeom": model.ngeom}
    try:
        sim = X.S.Sim(world, 1000)
    except X.W.WorldError:
        return fail("stability", "no_glass_left", "Solids cover all of the assigned glass.", **base)
    except Exception as e:
        return fail("stability", "sim_init_failed", "The sim could not start on this scene.", raw=str(e)[:500], **base)
    table = X.geom_table(sim.m, sim.d)
    base["geoms"] = table
    if not all(math.isfinite(v) for r in table for k, v in r.items() if k in ("x0", "x1", "y0", "y1", "z0", "z1")):
        return fail("stability", "nan_geometry", "A geom has a non-finite position after compile.", **base)
    if X.start_blocked(table, world):
        return fail("stability", "start_blocked", "A solid geom overlaps the keep-clear box around the robot start.", **base)
    share = X.reachable_share(sim.el_rects, world)
    base["reachable_share"] = round(share, 3)
    if share < MIN_REACH_SHARE:
        return fail("stability", "no_reachable_surface", f"Solids leave under {MIN_REACH_SHARE:.0%} of the assigned area reachable from the start.", **base)
    sim.m.opt.enableflags |= mujoco.mjtEnableBit.mjENBL_ENERGY
    x0, z0 = sim.body_xz()
    peak = 0.0
    for _ in range(int(SETTLE_S * X.S.CONTROL_HZ)):
        sim.step([0.0, 0.0, 0.85, 0.0, 0.0, 0.0])
        if not (sim.d.qpos == sim.d.qpos).all() or not (sim.d.qvel == sim.d.qvel).all():
            return fail("stability", "nan_state", "The state went non-finite while settling.", **base)
        peak = max(peak, float(sim.d.energy[1]))
        if sim.diverged:
            return fail("stability", "diverged", "The robot diverged while settling on the glass.", diverged_reason=sim.diverged_reason, **base)
    x1, z1 = sim.body_xz()
    drift = math.hypot(x1 - x0, z1 - z0)
    base.update(settle_drift_m=round(drift, 4), peak_kinetic_j=round(peak, 4))
    if peak > SANE_ENERGY_J:
        return fail("stability", "energy", "Kinetic energy passed its bound while settling.", **base)
    if drift > SANE_DRIFT_M:
        return fail("stability", "drift", "The robot slid while it should hold still on the glass.", **base)
    return {"ok": True, "stage": "passed", "code": "ok", "plain": "ok", **base}


def trial(scene_path, seed, out):
    text = Path(scene_path).read_bytes()
    X.install(text)
    import run_trial
    run_trial.run(X.base_world(), int(seed), out)
    path = Path(out) / "result.json"
    result = json.loads(path.read_text())
    result["scene_sha256"] = hashlib.sha256(text).hexdigest()
    path.write_text(json.dumps(result, indent=1) + "\n")
    (Path(out) / "scene.xml").write_bytes(text)


def replay(run_dir):
    run = Path(run_dir)
    text = (run / "scene.xml").read_bytes()
    stored = json.loads((run / "result.json").read_text())
    X.install(text)
    import replay as replay_module
    report = replay_module.replay(run)
    report["scene_match"] = hashlib.sha256(text).hexdigest() == stored["scene_sha256"]
    report["match"] = bool(report["match"] and report["scene_match"])
    (run / "replay.json").write_text(json.dumps(report, indent=1) + "\n")


def probe(path):
    try:
        Path(path).read_bytes()
        return "read"
    except OSError:
        return "denied"


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "check":
        Path("report.json").write_text(json.dumps(check(sys.argv[2])))
    elif cmd == "trial":
        trial(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "replay":
        replay(sys.argv[2])
    elif cmd == "probe":
        Path("report.json").write_text(json.dumps({"probe": probe(sys.argv[2])}))
