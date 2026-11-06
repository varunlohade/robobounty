"""Keeps one run server alive. Use this to run the server from now on: policy/.venv/bin/python policy/server/supervise.py [--port 5198] [--recorded DIR]

It polls /api/health. After repeated failures it kills the server, which works on a stopped process too, and starts it again with a capped backoff. It restarts a crashed server the same way.
Each session's world and events are on disk, so the page reconnects and the chat goes on. It refuses a port that is already in use, so it never takes over a server it did not start.
"""
import argparse
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs" / "server"
ORIGIN = "http://localhost:5199"
HEALTH_EVERY_S = 2
HEALTH_TIMEOUT_S = 3
FAILS_BEFORE_RESTART = 3
START_GRACE_S = 30  # Measured start: under 2 s.
BACKOFF_FIRST_S = 1
BACKOFF_CAP_S = 30
STABLE_S = 60  # A server up this long resets the backoff.
STOP_WAIT_S = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--script", default=str(HERE / "server.py"), help="the server to keep alive. Checks pass a fault server here.")
    a, rest = ap.parse_known_args()
    log_path = RUNS / f"recovery-{a.port}.log"
    RUNS.mkdir(parents=True, exist_ok=True)

    def log(cause, action):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} supervisor cause={cause} action={action}"
        print(line, flush=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")

    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", a.port)) == 0:
            sys.exit(f"Port {a.port} is in use. Stop that server first, or pass --port.")

    def healthy():
        request = urllib.request.Request(f"http://127.0.0.1:{a.port}/api/health", headers={"Origin": ORIGIN})
        try:
            with urllib.request.urlopen(request, timeout=HEALTH_TIMEOUT_S) as reply:
                return reply.status == 200
        except (urllib.error.URLError, OSError):
            return False

    child = None

    def stop(*_):
        if child and child.poll() is None:
            child.send_signal(signal.SIGCONT)
            child.terminate()
            try:
                child.wait(STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                child.kill()
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    cause, backoff = None, BACKOFF_FIRST_S
    while True:
        child = subprocess.Popen([sys.executable, a.script, "--port", str(a.port), *rest, *(["--restart-cause", cause] if cause else [])])
        started, fails, was_up = time.monotonic(), 0, False
        log("start" if not cause else f"server {cause}", f"started pid {child.pid}")
        while True:
            time.sleep(HEALTH_EVERY_S)
            code = child.poll()
            if code == 0:
                log("the server stopped itself with exit 0", "stopped too")
                return
            if code is not None:
                cause = "crashed"
                log(f"server pid {child.pid} exited with code {code}", f"restart in {backoff} s")
                break
            if healthy():
                was_up, fails = True, 0
            elif was_up or time.monotonic() - started > START_GRACE_S:
                fails += 1
                if fails >= FAILS_BEFORE_RESTART:
                    cause = "froze"
                    log(f"server pid {child.pid} failed {fails} health checks", f"killed it, restart in {backoff} s")
                    child.kill()
                    child.wait()
                    break
        if time.monotonic() - started >= STABLE_S:
            backoff = BACKOFF_FIRST_S
        time.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_CAP_S)


if __name__ == "__main__":
    main()
