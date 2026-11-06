"""Counts simulation speed on this Mac's CPU: 1, 4 and 16 parallel worlds in one process, native MuJoCo C, several processes.

Each count runs the full loop: policy inference and 4 physics steps per policy step, with no recording. Results are simulated.
"""
import argparse
import json
import subprocess
import sys
import time

import sim as S
import world as W

STEPS = 250


def one(worlds, *, mujoco_cpu=False, steps=STEPS):
    world = W.new_world()
    runner = S.Runner(world, worlds=worlds, seed=0, mujoco_cpu=mujoco_cpu, need_contacts=False)
    runner.policy_step()
    started = time.perf_counter()
    cpu_started = time.process_time()
    for _ in range(steps):
        runner.policy_step()
    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    base = runner.state_0.joint_q.numpy().reshape(worlds, runner.nq)
    sim_s = steps * S.POLICY_DT
    return {
        "worlds": worlds,
        "backend": "mujoco_c" if mujoco_cpu else "mujoco_warp",
        "wall_s": round(wall, 2),
        "cpu_s": round(cpu, 2),
        "physics_steps_per_s_all_worlds": round(steps * S.DECIMATION * worlds / wall),
        "rtf_per_world": round(sim_s / wall, 2),
        "rtf_total": round(sim_s * worlds / wall, 2),
        "walking": int((base[:, 2] > 0.25).sum()),
        "x_range_m": [round(float(base[:, 0].min()), 2), round(float(base[:, 0].max()), 2)],
    }


def processes(count):
    code = "import sys; sys.path.insert(0, %r); import json, many; print('RESULT' + json.dumps(many.one(1)))" % str(S.HERE)
    started = time.perf_counter()
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd="/tmp", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) for _ in range(count)]
    outs = [json.loads([ln for ln in p.communicate()[0].splitlines() if ln.startswith("RESULT")][0][6:]) for p in procs]
    wall = time.perf_counter() - started
    return {"processes": count, "wall_s_including_startup": round(wall, 1), "rtf_each": [o["rtf_per_world"] for o in outs],
            "rtf_total": round(sum(o["rtf_per_world"] for o in outs), 2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(S.HERE / "out" / "many.json"))
    args = parser.parse_args()
    results = {"label": S.code_label(), "note": "Simulated. CPU only. Other work may share this machine.", "one_process": [], "native_c": None, "processes": []}
    for worlds in (1, 1, 4, 16, 64, 256):
        results["one_process"].append(one(worlds))
        print(results["one_process"][-1], flush=True)
    results["native_c"] = one(1, mujoco_cpu=True)
    print(results["native_c"], flush=True)
    for count in (4, 12):
        results["processes"].append(processes(count))
        print(results["processes"][-1], flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
