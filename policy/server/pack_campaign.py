"""One campaign: a list of scenario worlds, each in its own child process, at most max_procs at once. Results are simulated.

Each child is a pack's job.py run. It writes progress.json, and this loop reads those files into one grid object about once a second.
Stuck: no progress for STUCK_S while the child is alive. It goes back to running if progress resumes.
A child also runs under the server's "run" deadline: past it, it is killed and stays stuck. A failed or frozen run is a result. Nothing here retries a run.
"""
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import pack_job

STUCK_S = 30.0
POLL_S = 0.25
GRID_EVERY_S = 1.0
STATUSES = ("queued", "running", "passed", "failed", "stuck", "held")
LOG_LINES = 30
LIBRARY_NOISE = re.compile(r"^(Module |Warp |   |Kernel cache|$)")  # Warp's start-up lines hide the run's own.
HELD_BACK_WORDS = "Held back. It stays out of this campaign, to test a fix on a world the fix never saw."


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def group_cpu_all():
    """CPU seconds by process group, from one ps call. None when ps gives no answer, which proves nothing either way."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pgid=,time="], capture_output=True, text=True, timeout=5).stdout
    except subprocess.TimeoutExpired:
        return None
    total = Counter()
    for line in out.splitlines():
        group, spent = line.split()
        total[int(group)] += sum(float(part) * 60 ** i for i, part in enumerate(reversed(spent.split(":"))))
    return total


def tail(path, n=LOG_LINES):
    try:
        return [line for line in Path(path).read_text(errors="replace").splitlines() if not LIBRARY_NOISE.match(line)][-n:]
    except OSError:
        return []


def initial_row(world):
    held = world["held_back"]
    return {"index": world["index"], "name": world["name"], "group": world["group"], "reason": world["reason"], "status": "held" if held else "queued", "held_back": held,
            "t": None, "t_limit": world["t_limit"], "x": None, "y": None, "outline": world["outline"], "verdict": None, "verdict_reason": HELD_BACK_WORDS if held else None}


class Child:
    def __init__(self, row, world, folder):
        self.row, self.world, self.folder = row, world, folder
        self.progress = folder / "progress.json"
        self.proc, self.files = None, []
        self.last_t, self.moved_at = None, time.monotonic()
        self.output_at, self.signal_at, self.mark, self.cpu = self.moved_at, self.moved_at, None, None


class Campaign:
    """spawn, finish and kill_group come from the server, so its live list, its shutdown and its leftover cleanup cover these children too."""

    def __init__(self, pack, cid, plan, folder, max_procs, rule, spawn, finish, kill_group, argv_for=None, on_grid=None, beat=None, stuck_s=STUCK_S):
        self.pack, self.cid, self.plan, self.folder, self.max_procs, self.rule = pack, cid, plan, Path(folder), max_procs, rule
        self.spawn, self.finish, self.kill_group = spawn, finish, kill_group
        self.argv_for = argv_for or (lambda world: pack_job.argv(pack, "run"))
        self.on_grid, self.beat, self.stuck_s = on_grid or (lambda g: None), beat or (lambda: None), stuck_s
        self.rows = [initial_row(w) for w in plan["worlds"]]
        self.started, self.running, self.wall = None, False, 0.0

    def grid(self):
        counts = Counter(r["status"] for r in self.rows)
        elapsed = self.wall if not self.running else time.monotonic() - self.started
        return {"type": "grid", "campaign": self.cid, "pack": self.pack, "running": self.running, "elapsed_s": round(elapsed, 1), "max_procs": self.max_procs, "counts": {s: counts.get(s, 0) for s in STATUSES},
                "rows": [dict(r) for r in self.rows]}

    def publish(self):
        grid = self.grid()
        tmp = self.folder / "grid.tmp"
        tmp.write_text(json.dumps(grid))
        tmp.replace(self.folder / "grid.json")
        self.on_grid(grid)

    def start(self, child):
        child.folder.mkdir(parents=True, exist_ok=True)
        w = child.world
        request = child.folder / "request.json"
        request.write_text(json.dumps({"world": w["world"], "seed": w["seed"], "out": str(child.folder), "progress": str(child.progress)}))
        stdin, stdout, stderr = open(request, "rb"), open(child.folder / "reply.json", "wb"), open(child.folder / "job.log", "ab")
        child.files = [stdin, stdout, stderr]
        child.proc = self.spawn(self.argv_for(w), stdin=stdin, stdout=stdout, stderr=stderr, cwd=pack_job.POLICY)
        child.moved_at = child.output_at = child.signal_at = time.monotonic()
        child.row["status"] = "running"

    def close(self, child):
        for f in child.files:
            f.close()
        child.files = []
        self.finish(child.proc)

    def ended(self, child, code):
        self.close(child)
        result = read_json(child.folder / "job_result.json")
        row = child.row
        if code != 0 or not isinstance(result, dict):
            row.update(status="failed", verdict="process_crashed", verdict_reason=f"The run's process ended with exit code {code} and gave no result. It was not retried.")
            return
        row["status"] = "passed" if result["passed"] else "held" if result.get("safe_hold") else "failed"
        row.update(verdict=result["verdict"], verdict_reason=result["reason"])
        if result.get("end_t") is not None:
            row.update(t=result["end_t"], x=result["end_x"], y=result["end_y"])

    def froze(self, child, why):
        self.kill_group(child.proc.pid)
        try:
            child.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        self.close(child)
        child.row.update(status="stuck", verdict="froze", verdict_reason=f"{why}, so I stopped this run. It was not retried.")

    def watch(self, child, cpu_now):
        now = time.monotonic()
        seen = read_json(child.progress) or {}
        row = child.row
        if seen.get("t") is not None:
            row.update(t=seen["t"], x=seen["x"], y=seen["y"])
        if seen.get("t") != child.last_t:
            child.last_t, child.moved_at = seen.get("t"), now
        try:
            stat = os.stat(child.progress)
            mark = (stat.st_size, stat.st_mtime_ns)
        except FileNotFoundError:
            mark = None
        if mark != child.mark:
            child.mark, child.output_at, child.signal_at = mark, now, now
        row["status"] = "stuck" if now - child.moved_at > self.stuck_s else "running"
        rule = self.rule
        if rule.quiet_s is not None and cpu_now is not None:
            used = cpu_now.get(child.proc.pid)
            if used is not None and (child.cpu is None or abs(used - child.cpu) >= 0.05):
                child.cpu, child.signal_at = used, now
            if now - child.signal_at > rule.quiet_s:
                return self.froze(child, f"No CPU use and no progress for {now - child.signal_at:.0f} s") or True
        if now - child.output_at > rule.silent_s:
            return self.froze(child, f"No progress for {now - child.output_at:.0f} s") or True
        return False

    def run(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        queue = [Child(r, w, self.folder / f"w{w['index']:03d}") for r, w in zip(self.rows, self.plan["worlds"]) if not w["held_back"]]
        live = []
        self.started, self.running = time.monotonic(), True
        self.publish()
        grid_at, cpu_at, cpu = time.monotonic(), 0.0, None
        try:
            while queue or live:
                self.beat()
                while queue and len(live) < self.max_procs:
                    child = queue.pop(0)
                    self.start(child)
                    live.append(child)
                now = time.monotonic()
                if now - cpu_at >= 2.0:
                    cpu_at, cpu = now, group_cpu_all()
                else:
                    cpu = None
                for child in list(live):
                    code = child.proc.poll()
                    if code is not None:
                        self.ended(child, code)
                        live.remove(child)
                    elif self.watch(child, cpu):
                        live.remove(child)
                if time.monotonic() - grid_at >= GRID_EVERY_S:
                    grid_at = time.monotonic()
                    self.wall = grid_at - self.started
                    self.publish()
                time.sleep(POLL_S)
        except BaseException:
            for child in live:
                self.kill_group(child.proc.pid)
                self.close(child)
            raise
        finally:
            self.wall = time.monotonic() - self.started
            self.running = False
            self.publish()
        return self.grid()


def world_detail(campaign_dir, index):
    """Everything a click on one square shows. From files, so it works during a run and after a restart. None for an unknown index."""
    folder = Path(campaign_dir)
    plan = read_json(folder / "scenarios.json")
    grid = read_json(folder / "grid.json")
    if not plan or not 0 <= index < len(plan["worlds"]):
        return None
    world = plan["worlds"][index]
    row = grid["rows"][index] if grid else initial_row(world)
    run = folder / f"w{index:03d}"
    result = read_json(run / "job_result.json") or {}
    return {"index": index, "name": world["name"], "group": world["group"], "reason": world["reason"], "status": row["status"], "held_back": world["held_back"], "verdict": row["verdict"], "verdict_reason": row["verdict_reason"],
            "numbers": result.get("numbers", {}), "events": result.get("events", []), "log": tail(run / "job.log"), "code": result.get("code"), "changes": world["changes"], "world": world["world"], "seed": world["seed"],
            "wall_s": result.get("wall_s"), "label": result.get("label"), "note": result.get("note") or plan["note"], "replay": bool(result)}
