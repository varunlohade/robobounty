"""Runs a folder of scenes with one loaded model per worker: batch.py <scenes dir> --out <dir> --workers N

Rerun the same command to resume. A run dir counts only once it holds result.json, because workers build each
run in .tmp and rename it into place. A kill leaves only .tmp behind, and the next start deletes it.
"""
import argparse
import fcntl
import gc
import json
import multiprocessing as mp
import multiprocessing.connection as mpc
import os
import resource
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene as scene_schema

MAX_WORKERS = 2  # the owner uses this Mac while the batch runs
MAX_ATTEMPTS = 2
MAX_WORKER_DEATHS = 6
HEALTH_CHECK_S = 30
NICE = 10
TORCH_THREADS = 4
WARN_PRESSURE = 2  # kern.memorystatus_vm_pressure_level: 1 normal, 2 warn, 4 critical


def log(out, text):
    line = f"{time.strftime('%H:%M:%S')} {text}"
    print(line, flush=True)
    with (out / "batch.log").open("a") as f:
        f.write(line + "\n")


def append_result(out, row):
    with (out / "results.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def machine_trouble():
    """Returns the reason to drop a worker, or None."""
    try:
        level = int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                                   capture_output=True, text=True, timeout=10).stdout)
        if level >= WARN_PRESSURE:
            return f"memory pressure level {level}"
        therm = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, timeout=10).stdout
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    for line in therm.splitlines():
        low = line.lower()
        if ("level" in low or "speed_limit" in low) and "no " not in low and "= 100" not in low:
            return f"thermal: {line.strip()}"
    return None


def worker_main(index, conn, out, device, parent_pid):
    os.nice(NICE)
    with open(out / f"worker_{index}.log", "ab", buffering=0) as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)

    def exit_with_parent():
        while os.getppid() == parent_pid:
            time.sleep(2)
        os._exit(1)

    threading.Thread(target=exit_with_parent, daemon=True).start()

    started = time.time()
    import sim  # sets the environment that lerobot and libero read at import
    import lerobot
    import torch
    import run_scene

    torch.set_num_threads(TORCH_THREADS)
    loaded = run_scene.load_policy(device, run_scene.env_config(0))
    conn.send({"type": "hello", "load_s": time.time() - started, "versions": {
        **sim.versions(), "lerobot": lerobot.__version__, "torch": torch.__version__,
        "python": sys.version.split()[0]}})

    while True:
        name = conn.recv()
        if name is None:
            return
        tmp = out / ".tmp" / name
        try:
            scene = scene_schema.load(tmp.with_suffix(".json"))
            result = run_scene.run_episode(scene, tmp, device, loaded)
            tmp.with_suffix(".json").unlink()
            tmp.rename(out / name)
            conn.send({"type": "done", "name": name, "rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30,
                       **{k: result.get(k) for k in ("status", "success", "steps", "reason", "wall_s")}})
        except Exception:
            print(traceback.format_exc(), flush=True)
            conn.send({"type": "error", "name": name, "error": traceback.format_exc(limit=-3)})
        gc.collect()
        torch.mps.empty_cache()


def record_without_run(out, name, scene, status, detail):
    """For a scene the batch refuses or gives up on. It counts as complete, so a resume does not retry it."""
    tmp = out / ".tmp" / f"{name}.record"
    tmp.mkdir(parents=True)
    result = {"status": status, "success": None, "steps": 0, "reason": status, "detail": detail}
    if scene is not None:
        (tmp / "scene.json").write_text(scene_schema.canonical(scene) + "\n")
        result["scene_sha256"] = scene_schema.scene_hash(scene)
    (tmp / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    tmp.rename(out / name)
    append_result(out, {"name": name, "status": status, "success": None, "steps": 0, "reason": status})


def read_scenes(scenes_dir, out):
    """Returns the scenes to run. Records the ones that must not run. Refuses a folder that changed under old results."""
    todo = []
    names = []
    for path in sorted(scenes_dir.glob("*.json")):
        name = path.stem
        names.append(name)
        try:
            scene = scene_schema.load(path)
        except (scene_schema.SceneError, OSError) as e:
            if not (out / name / "result.json").exists():
                record_without_run(out, name, None, "rejected", str(e))
            continue
        done = out / name / "result.json"
        if done.exists():
            stored = json.loads(done.read_text())
            if stored.get("scene_sha256") != scene_schema.scene_hash(scene):
                raise SystemExit(f"{path} no longer matches the stored run {out / name}")
            continue
        # A new colour makes "black bowl" false, so the task on that scene no longer has a right answer.
        if any(c["object"] == scene_schema.TARGET_OBJECT for c in scene["colours"]):
            record_without_run(out, name, scene, "excluded_target_recolour", "the scene recolours the target")
            continue
        todo.append((name, path))
    return names, todo


def backfill_log(out, names):
    """A kill can land after a run is renamed and before the parent logs it."""
    log_path = out / "results.jsonl"
    logged = {json.loads(line)["name"] for line in log_path.read_text().splitlines()} if log_path.exists() else set()
    for name in names:
        done = out / name / "result.json"
        if name not in logged and done.exists():
            r = json.loads(done.read_text())
            append_result(out, {"name": name, "backfilled": True,
                                **{k: r.get(k) for k in ("status", "success", "steps", "reason", "wall_s")}})


class Worker:
    def __init__(self, ctx, index, out, device):
        self.index = index
        self.conn, child = ctx.Pipe()
        self.process = ctx.Process(target=worker_main, args=(index, child, out, device, os.getpid()))
        self.process.start()
        child.close()
        self.ready = False
        self.current = None


def run_batch(scenes_dir, out, workers, device):
    (out / ".tmp").mkdir(parents=True, exist_ok=True)
    lock = (out / ".lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f"another batch holds {out}")
    shutil.rmtree(out / ".tmp")
    (out / ".tmp").mkdir()

    names, todo = read_scenes(scenes_dir, out)
    backfill_log(out, names)
    meta_path = out / "batch_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"scenes": names, "sessions": []}
    generator = scenes_dir / "GENERATOR"
    if generator.exists():
        meta["generator"] = json.loads(generator.read_text())
    if meta["scenes"] != names:
        raise SystemExit(f"{scenes_dir} holds different scene files from this batch")
    session = {"started": time.time(), "workers": workers, "to_run": len(todo), "scenes_dir": scenes_dir.name}
    meta["sessions"].append(session)
    meta_path.write_text(json.dumps(meta, indent=1) + "\n")
    log(out, f"session start: {len(names)} scenes, {len(names) - len(todo)} complete, {len(todo)} to run, {workers} workers")

    ctx = mp.get_context("spawn")
    paths = dict(todo)
    pending = deque(paths)
    attempts = {name: 0 for name in paths}
    limit = workers
    deaths = 0
    pool = {}
    next_health = 0.0

    def finish_attempt(name, detail):
        attempts[name] += 1
        shutil.rmtree(out / ".tmp" / name, ignore_errors=True)
        (out / ".tmp" / f"{name}.json").unlink(missing_ok=True)
        if attempts[name] >= MAX_ATTEMPTS:
            log(out, f"{name} gave up after {attempts[name]} attempts: {detail}")
            record_without_run(out, name, scene_schema.load(paths[name]), "runner_error", detail)
        else:
            log(out, f"{name} retry: {detail}")
            pending.appendleft(name)

    while pending or any(w.current for w in pool.values()):
        if time.time() >= next_health:
            next_health = time.time() + HEALTH_CHECK_S
            trouble = machine_trouble()
            if trouble and limit > 1:
                limit = 1
                session["dropped_to_one_worker"] = trouble
                meta_path.write_text(json.dumps(meta, indent=1) + "\n")
                log(out, f"dropping to 1 worker: {trouble}")

        wanted = min(limit, len(pending) + sum(1 for w in pool.values() if w.current))
        for index in range(wanted):
            if index not in pool:
                pool[index] = Worker(ctx, index, out, device)
        for index in [i for i, w in pool.items() if i >= limit and not w.current]:
            pool[index].conn.send(None)
            pool.pop(index).process.join(timeout=30)

        for w in pool.values():
            if w.ready and not w.current and pending:
                w.current = pending.popleft()
                shutil.copyfile(paths[w.current], out / ".tmp" / f"{w.current}.json")
                w.conn.send(w.current)

        conns = {w.conn: w for w in pool.values()}
        sentinels = {w.process.sentinel: w for w in pool.values()}
        for ready in mpc.wait([*conns, *sentinels], timeout=HEALTH_CHECK_S):
            w = conns.get(ready) or sentinels[ready]
            if w.index not in pool:
                continue
            try:
                if not w.conn.poll():  # read a final message before treating the worker as dead
                    raise EOFError
                msg = w.conn.recv()
            except (EOFError, OSError):
                w.process.join(timeout=5)
                pool.pop(w.index)
                deaths += 1
                log(out, f"worker {w.index} died with exit code {w.process.exitcode} on {w.current}")
                if w.current:
                    finish_attempt(w.current, f"worker died with exit code {w.process.exitcode}")
                if deaths >= MAX_WORKER_DEATHS:
                    raise SystemExit(f"{deaths} worker deaths, stopping. Rerun to resume.")
                continue
            if msg["type"] == "hello":
                w.ready = True
                meta["versions"] = msg["versions"]
                session.setdefault("load_s", []).append(msg["load_s"])
                meta_path.write_text(json.dumps(meta, indent=1) + "\n")
                log(out, f"worker {w.index} ready in {msg['load_s']:.0f} s")
            elif msg["type"] == "done":
                append_result(out, {k: v for k, v in msg.items() if k != "type"} | {"worker": w.index})
                log(out, f"{msg['name']} {msg['status']} {msg['reason']} steps={msg['steps']} "
                         f"wall={msg['wall_s']:.0f}s rss={msg['rss_gb']:.1f}GB worker={w.index}")
                w.current = None
            else:
                name, w.current = w.current, None
                finish_attempt(name, msg["error"])

    for w in pool.values():
        w.conn.send(None)
        w.process.join(timeout=30)
    session["finished"] = time.time()
    meta_path.write_text(json.dumps(meta, indent=1) + "\n")
    log(out, f"session done in {session['finished'] - session['started']:.0f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()
    if not 1 <= args.workers <= MAX_WORKERS:
        ap.error(f"--workers must be 1 to {MAX_WORKERS}")
    run_batch(Path(args.scenes), Path(args.out).resolve(), args.workers, args.device)


if __name__ == "__main__":
    main()
