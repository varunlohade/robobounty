"""The real run server with faults a check switches on: fault_server.py --faults FILE [--quiet S] [--silent S] [--worker-quiet S] <server.py arguments>. For checks only.

FILE holds JSON such as {"run": ["sleep", "sleep"], "thread": 1, "cut_streams": 1, "stall_trial": 1, "stall_post": 1}. Each child spawn takes the next action of its stage. Children stay real processes, and only their argv changes.
Every spawn adds one line to FILE.spawns, so a check can count retries.
"""
import argparse
import dataclasses
import json
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server

ap = argparse.ArgumentParser()
ap.add_argument("--faults", required=True)
ap.add_argument("--quiet", type=float, default=4)
ap.add_argument("--silent", type=float, default=20)
ap.add_argument("--worker-quiet", type=float, default=5)
a, rest = ap.parse_known_args()
sys.argv = [sys.argv[0], *rest]
FAULTS = Path(a.faults)
LOCK = threading.Lock()
server.DEADLINES = {k: dataclasses.replace(v, quiet_s=None if v.quiet_s is None else a.quiet, silent_s=a.silent) for k, v in server.DEADLINES.items()}
server.WORKER_QUIET_S = a.worker_quiet
server.WATCHDOG_POLL_S = 1


def take(key):
    """The next action for key, or None. It leaves the file, so it fires once."""
    with LOCK:
        faults = json.loads(FAULTS.read_text()) if FAULTS.exists() else {}
        value = faults.get(key)
        if isinstance(value, list):
            action = value.pop(0) if value else None
            if not value:
                faults.pop(key, None)
        else:
            action = faults.pop(key, None)
        if action is not None:
            FAULTS.write_text(json.dumps(faults))
    return action


def stage_of(argv):
    script = Path(argv[1]).name
    return {"plan_job.py": argv[2] if len(argv) > 2 else "", "run_beat.py": "run", "app_export.py": "export", "requirements.py": "requirements"}.get(script, script)


real_spawn = server.spawn


def spawn(argv, **kw):
    stage = stage_of(argv)
    action = take(stage)
    with open(f"{FAULTS}.spawns", "a") as f:
        f.write(f"{stage} {action or 'real'}\n")
    if action:
        argv = [argv[0], str(HERE / "fault_child.py"), action, *argv[2:]]
    return real_spawn(argv, **kw)


server.spawn = spawn
real_normal_run = server.Session.normal_run


def normal_run(self):
    if take("thread"):
        threading.Event().wait()  # A worker thread stuck for good, with no child to blame.
    real_normal_run(self)


server.Session.normal_run = normal_run
OPEN_STREAMS = set()
real_stream = server.Handler.stream


def stream(self, s):
    OPEN_STREAMS.add(self.connection)
    try:
        real_stream(self, s)
    except OSError:
        pass  # The cut below ends the stream this way.
    finally:
        OPEN_STREAMS.discard(self.connection)


server.Handler.stream = stream
real_get = server.Handler.do_GET


def do_get(self):
    if "/trials/" in self.path and self.path.endswith("manifest.json") and take("stall_trial"):
        time.sleep(40)  # Past the page's 20 s fetch deadline.
    real_get(self)


server.Handler.do_GET = do_get
real_post = server.Handler.do_POST


def do_post(self):
    if self.path.endswith("/message") and take("stall_post"):
        time.sleep(40)  # Past the page's 15 s reply deadline.
    real_post(self)


server.Handler.do_POST = do_post


def cutter():
    while True:
        time.sleep(0.25)
        if take("cut_streams"):
            for connection in list(OPEN_STREAMS):
                connection.shutdown(socket.SHUT_RDWR)


threading.Thread(target=cutter, daemon=True).start()
server.main()
