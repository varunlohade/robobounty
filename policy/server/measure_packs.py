"""Measures parallel runs per pack, to set max_procs in pack_job.py: policy/.venv/bin/python policy/server/measure_packs.py <pack> <procs,procs,...> [--runs N]

Runs one world many times at each process count. A probe at normal priority times a fixed piece of work while they run. Its slowdown is how the rest of the Mac feels. Runs are niced, like the server's. Results are simulated.
"""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_job as J


def work():
    t0 = time.perf_counter()
    total = 0
    for i in range(400_000):
        total += i * i
    return time.perf_counter() - t0


def probe(stop, out):
    while not stop.is_set():
        out.append(work())
        time.sleep(0.2)


def one(pack, world, seed, folder):
    t0 = time.perf_counter()
    request = {"world": world, "seed": seed, "out": str(folder / str(seed)), "progress": str(folder / f"{seed}.progress.json")}
    done = subprocess.run(["nice", "-n", "5", *J.argv(pack, "run")], input=json.dumps(request).encode(), capture_output=True, cwd=J.POLICY)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-400:].decode(errors="replace"))
    reply = json.loads(done.stdout)
    return time.perf_counter() - t0, reply["verdict"], reply.get("final_state_sha256") or reply.get("record_sha256")


def rss_mb():
    out = subprocess.run(["ps", "-A", "-o", "rss=,command="], capture_output=True, text=True).stdout
    return sum(int(line.split()[0]) for line in out.splitlines() if "packs." in line and ".job run" in line) / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", choices=sorted(J.PACKS))
    ap.add_argument("procs")
    ap.add_argument("--runs", type=int, default=0, help="runs at each count. 0 means twice the count")
    a = ap.parse_args()
    world = J.ask(a.pack, "start", {})["world"]
    quiet = [work() for _ in range(10)]
    base = statistics.median(quiet)
    print(f"{a.pack}: probe alone {base * 1000:.0f} ms, load {subprocess.run(['uptime'], capture_output=True, text=True).stdout.split('load')[-1].strip()}", flush=True)
    for procs in (int(p) for p in a.procs.split(",")):
        runs = a.runs or procs * 2
        samples, stop, peak = [], threading.Event(), [0.0]
        thread = threading.Thread(target=probe, args=(stop, samples), daemon=True)
        thread.start()

        def memory():
            while not stop.is_set():
                peak[0] = max(peak[0], rss_mb())
                time.sleep(2)
        threading.Thread(target=memory, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(procs) as pool:
            t0 = time.perf_counter()
            rows = list(pool.map(lambda s: one(a.pack, world, s, Path(tmp)), range(runs)))
            wall = time.perf_counter() - t0
        stop.set()
        thread.join()
        walls = [r[0] for r in rows]
        print(f"procs {procs:2d}: {runs} runs in {wall:6.1f} s = {runs / wall * 60:5.1f} runs/min, run wall median {statistics.median(walls):5.1f} s max {max(walls):5.1f} s, probe slowdown median {statistics.median(samples) / base:.2f}x p95 {sorted(samples)[int(len(samples) * .95)] / base:.2f}x, peak RSS {peak[0]:.0f} MB, verdicts {sorted(set(r[1] for r in rows))}", flush=True)


if __name__ == "__main__":
    main()
