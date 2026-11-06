"""One pack step in its own process, under that pack's own Python: <python> -m packs.<pack>.job <command>, with a JSON request on stdin and a JSON reply on stdout.

Commands: catalog, start, call, describe, validate, replay_calls, run, judge, film. The server imports only this file's table and ask(). A pack's job.py calls serve() with its hooks.
A pack may need a Python the server does not have, so nothing here imports a pack. Worlds and calls are data, and each pack checks them itself.
run writes progress.json about once a second while the sim steps: t, x, y, status. It is also the run's heartbeat, and it stops when the sim stops. Results are simulated.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

POLICY = Path(__file__).resolve().parent.parent
# max_procs comes from measure_packs.py on this Mac, 2026-11-06, with vite taking about 4 cores: the count before a normal-priority probe slows past about 1.5x at p95.
PACKS = {
    "window": {"python": POLICY / ".venv" / "bin" / "python", "label": "Window cleaning robot", "viewer": "trial", "max_procs": 8},
    "inspection": {"python": POLICY / ".venv-newton" / "bin" / "python", "label": "Inspection robot", "viewer": "poses", "max_procs": 6},
}
PROGRESS_EVERY_S = 1.0
LOG_EVERY_SIM_S = 10.0
FRAME_EVERY_S = 0.5  # Newest frame, by the wall clock.
FILM_FRAMES = 24  # Frames of the loop a square plays after its run, evenly through the run.
FILM_COLS = 6
FRAME_QUALITY = 60
NO_FRAMES_ENV = "CRASHLAB_NO_FRAMES"  # For the cost measurement.


def argv(pack, command):
    return [str(PACKS[pack]["python"]), "-m", f"packs.{pack}.job", command]


def ask(pack, command, request, timeout=None):
    """For code outside the server. The server runs the same argv under its deadlines."""
    done = subprocess.run(argv(pack, command), input=json.dumps(request).encode(), capture_output=True, cwd=POLICY, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{pack} {command} exit {done.returncode}: {done.stderr[-400:].decode(errors='replace')}")
    return json.loads(done.stdout)


def frames_on(progress):
    return progress.path is not None and not os.environ.get(NO_FRAMES_ENV)


class FrameClock:
    """Writes latest.jpg about twice a second from a shooter that returns a PIL image. A frame that fails to draw stops the frames and leaves the run alone: a picture never changes a result."""

    def __init__(self, out, shoot):
        self.path, self.shoot = Path(out) / "latest.jpg", shoot
        self.last, self.count, self.broken = 0.0, 0, False

    def tick(self, *state):
        now = time.monotonic()
        if self.broken or now - self.last < FRAME_EVERY_S:
            return
        self.last = now
        try:
            tmp = self.path.with_suffix(".tmp")
            self.shoot(*state).save(tmp, format="JPEG", quality=FRAME_QUALITY)
            tmp.replace(self.path)
            self.count += 1
        except Exception as e:
            self.broken = True
            print(f"frames stopped: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def write_film(out, images):
    """One JPEG holding the run's frames in rows, so a square loads one file and draws by rectangle. None if no frame could be drawn. A film that fails leaves the result alone."""
    from PIL import Image
    try:
        frames = list(images)
        if not frames:
            return None
        w, h = frames[0].size
        sheet = Image.new("RGB", (w * min(FILM_COLS, len(frames)), h * (1 + (len(frames) - 1) // FILM_COLS)))
        for i, frame in enumerate(frames):
            sheet.paste(frame, ((i % FILM_COLS) * w, (i // FILM_COLS) * h))
        sheet.save(Path(out) / "film.jpg", format="JPEG", quality=FRAME_QUALITY)
        return {"count": len(frames), "cols": FILM_COLS, "w": w, "h": h}
    except Exception as e:
        print(f"film stopped: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


class Progress:
    """Written from inside the sim loop, so a frozen sim writes nothing."""

    def __init__(self, path, t_limit):
        self.path, self.t_limit = Path(path) if path else None, t_limit
        self.last, self.logged, self.at = 0.0, -LOG_EVERY_SIM_S, (None, None, None)
        self.frames = 0
        self.write(None, None, None, "starting")

    def write(self, t, x, y, status):
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": t, "x": x, "y": y, "status": status, "t_limit": self.t_limit, "frames": self.frames}))
        tmp.replace(self.path)

    def update(self, t, x, y):
        now = time.monotonic()
        self.at = (round(t, 2), round(x, 3), round(y, 3))
        if now - self.last >= PROGRESS_EVERY_S:
            self.last = now
            self.write(*self.at, "running")
        if t - self.logged >= LOG_EVERY_SIM_S:
            self.logged = t
            print(f"t {t:.0f} s, x {x:.2f}, y {y:.2f}", file=sys.stderr, flush=True)


def replay_calls(hooks, req):
    """Each scenario's calls, in order, on a copy of the world. The first refusal ends that scenario."""
    base = req["world"]
    start_hash = hooks.physics_hash(base)
    worlds = []
    for scenario in req["scenarios"]:
        world, refused, lines = base, None, []
        for c in scenario["calls"]:
            out = hooks.call(world, c.get("fn"), c.get("args"))
            if str(out["result"]).startswith("cannot_build:"):
                refused = {"fn": str(c.get("fn"))[:40], "code": out["result"].split(":", 1)[1]}
                break
            world = out["world"]
            lines.append(hooks.call_line(c["fn"], c.get("args") or {}))
        if refused:
            worlds.append({"ok": False, "refused": refused})
        else:
            key = hooks.physics_hash(world)
            worlds.append({"ok": True, "world": world, "hash": key, "physics_changed": key != start_hash, "lines": lines, "outline": hooks.outline(world), "t_limit": hooks.t_limit(world), "marks": hooks.marks(base, world)})
    return {"worlds": worlds}


def run(hooks, req):
    out = Path(req["out"])
    out.mkdir(parents=True, exist_ok=True)
    world = req["world"]
    progress = Progress(req.get("progress"), hooks.t_limit(world))
    print(f"run seed {req['seed']}", file=sys.stderr, flush=True)
    t0 = time.perf_counter()
    result = hooks.run(world, req["seed"], out, progress)
    result.update(seed=req["seed"], wall_s=round(time.perf_counter() - t0, 2))
    print(f"verdict {result['verdict']}: {result['reason']}", file=sys.stderr, flush=True)
    result.update(end_t=progress.at[0], end_x=progress.at[1], end_y=progress.at[2])
    (out / "job_result.json").write_text(json.dumps(result, indent=1, allow_nan=False) + "\n")
    progress.write(*progress.at, "done")
    return result


def split_judged(judged):
    """A pack's judge gives verdict, passed, reason and numbers in one dict."""
    numbers = {k: v for k, v in judged.items() if k not in ("verdict", "passed", "reason") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    return {"verdict": judged["verdict"], "passed": bool(judged["passed"]), "reason": judged["reason"], "numbers": numbers}


def serve(hooks):
    """The reply goes on the real stdout. A library print from the sim goes to stderr."""
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    command = sys.argv[1]
    req = json.load(sys.stdin)
    table = {
        "catalog": lambda: {"name": hooks.NAME, "robot": hooks.ROBOT, "backend": hooks.BACKEND, "note": hooks.NOTE, "catalog": hooks.catalog(), "notes": hooks.NOTES, "not_modelled": hooks.NOT_MODELLED, "controller_files": hooks.controller_files()},
        "start": lambda: {"world": (w := hooks.start()), "hash": hooks.physics_hash(w), "scene": hooks.scene(w)},
        "call": lambda: (lambda o: {"result": o["result"], "rerun": o["rerun"], "world": o["world"], "hash": hooks.physics_hash(o["world"]), "scene": hooks.scene(o["world"])})(hooks.call(req["world"], req["fn"], req.get("args"))),
        "replay_calls": lambda: replay_calls(hooks, req),
        "describe": lambda: {"hash": hooks.physics_hash(req["world"]), "scene": hooks.scene(req["world"])},
        "validate": lambda: (lambda w: {"world": w, "hash": hooks.physics_hash(w), "outline": hooks.outline(w), "t_limit": hooks.t_limit(w)})(hooks.validate(req["world"])),
        "run": lambda: run(hooks, req),
        "judge": lambda: hooks.judge_again(Path(req["out"])),
        "film": lambda: hooks.film(req["world"], Path(req["out"])),
    }
    reply = table[command]()
    os.write(real_stdout, json.dumps(reply, allow_nan=False).encode())
