"""Injects real hangs and proves recovery: policy/.venv/bin/python policy/server/check_hang.py
It starts its own servers on free ports and uses stored AI replies. It never touches another server. The browser half is src/lab/tools/check_hang.mjs.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
sys.path.insert(0, str(HERE))
import server as srv

PY = str(POLICY / ".venv" / "bin" / "python")
FIXTURES = str(HERE / "fixtures_lab")
BRIEF, CHANGE = "Window robot for towers in Dubai. High floor.", "Make the wind stronger and wet the glass."
ORIGIN = "http://localhost:5199"
failed = 0


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


# 1. The deadline code on its own, with real child processes.
def units(tmp):
    srv.PORT = free_port()
    srv.RUNS.mkdir(parents=True, exist_ok=True)
    spawned = []
    real = srv.spawn

    def counting(argv, **kw):
        p = real(argv, **kw)
        spawned.append(p.pid)
        return p
    srv.spawn = counting
    srv.DEADLINES["t_sleep"] = srv.Deadline("Test", 2, 30)
    srv.DEADLINES["t_silent"] = srv.Deadline("Test", 2, 3)
    srv.DEADLINES["t_live"] = srv.Deadline("Test", 2, 3)
    srv.DEADLINES["t_cpu"] = srv.Deadline("Test", 2, 30)

    t0 = time.time()
    try:
        srv.watched("t_sleep", [PY, "-c", "import time; time.sleep(1e6)"], stdout=subprocess.DEVNULL)
        check("a child that sleeps forever is killed", False)
    except srv.StageHung as e:
        check("a child that sleeps forever is killed, then retried once, then gives up", len(spawned) == 2, f"{time.time() - t0:.1f} s, {e.why}")
    check("its process groups are gone", not any(alive(p) for p in spawned))

    spawned.clear()
    mark = tmp / "mark"
    once = f"import os,time,pathlib; m=pathlib.Path({str(mark)!r}); (m.exists() and os._exit(0)); m.write_text('x'); time.sleep(1e6)"
    t0 = time.time()
    code, _ = srv.watched("t_sleep", [PY, "-c", once], stdout=subprocess.DEVNULL)
    check("a child that hangs once succeeds on its retry", code == 0 and len(spawned) == 2, f"{time.time() - t0:.1f} s")

    spawned.clear()
    t0 = time.time()
    try:
        srv.watched("t_silent", [PY, "-c", "while True: pass"], stdout=subprocess.DEVNULL)
        check("a child that spins with no output is killed", False)
    except srv.StageHung as e:
        check("a child that spins with no output is killed", len(spawned) == 2, f"{time.time() - t0:.1f} s, {e.why}")

    spawned.clear()
    out = tmp / "growing"
    grow = f"import time\nfor i in range(10):\n    open({str(out)!r},'a').write('x'); time.sleep(1)"
    t0 = time.time()
    code, _ = srv.watched("t_live", [PY, "-c", grow], paths=(out,), stdout=subprocess.DEVNULL)
    check("a slow child with growing output is left alone, 3 times past its limit", code == 0 and len(spawned) == 1 and time.time() - t0 >= 9, f"{time.time() - t0:.1f} s against a 3 s limit")

    spawned.clear()
    burn = "import time\nt=time.time()\nwhile time.time()-t<8: pass"
    t0 = time.time()
    code, _ = srv.watched("t_cpu", [PY, "-c", burn], stdout=subprocess.DEVNULL)
    check("a busy child with no output is left alone past its quiet limit", code == 0 and len(spawned) == 1, f"{time.time() - t0:.1f} s against a 2 s limit")

    spawned.clear()
    code, _ = srv.watched("t_sleep", [PY, "-c", "import sys; sys.exit(3)"], stdout=subprocess.DEVNULL)
    check("a crash is a result: its code comes back with no retry", code == 3 and len(spawned) == 1, code)
    srv.spawn = real
    for name in ("t_sleep", "t_silent", "t_live", "t_cpu"):
        del srv.DEADLINES[name]
    (srv.RUNS / f"recovery-{srv.PORT}.log").unlink(missing_ok=True)
    (srv.RUNS / f"live-{srv.PORT}.txt").unlink(missing_ok=True)


class Chat:
    def __init__(self, port, sid=None):
        self.port = port
        self.sid = sid or self.call("POST", "/api/sessions", {})[1]["id"]

    def call(self, method, path, body=None, timeout=10):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, {}

    def events(self):
        path = srv.RUNS / self.sid / "events.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def idle(self):
        return sum(e["type"] == "idle" for e in self.events())

    def lines(self, since=0):
        return [e["text"] for e in self.events()[since:] if e["type"] == "text"]

    def wait_idle(self, before, seconds):
        t0 = time.time()
        while time.time() - t0 < seconds:
            if self.idle() > before:
                return time.time() - t0
            time.sleep(0.2)
        raise TimeoutError(f"no idle in {seconds} s. Said: {self.lines()[-4:]}")

    def state(self):
        return {k: v for k, v in self.call("GET", f"/api/sessions/{self.sid}/state")[1].items() if k in ("phase", "busy")}  # /state also names the engine and pack, which these checks do not compare.

    def say(self, text, seconds=120):
        """Sends a message, answers any quick question, and returns the seconds until the chat is idle."""
        t0, n = time.time(), self.idle()
        status, _ = self.call("POST", f"/api/sessions/{self.sid}/message", {"text": text})
        if status != 202:
            raise RuntimeError(f"message refused: {status}")
        self.wait_idle(n, seconds)
        while self.state()["phase"] == "asking":
            n = self.idle()
            self.call("POST", f"/api/sessions/{self.sid}/action", {"action": "answer", "value": 0})
            self.wait_idle(n, seconds)
        return time.time() - t0

    def last_world(self):
        return [e for e in self.events() if e["type"] == "world"][-1]


def start_fault(tmp, name, port=None):
    port = port or free_port()
    faults = tmp / f"{name}.json"
    faults.write_text("{}")
    p = subprocess.Popen([PY, str(HERE / "fault_server.py"), "--faults", str(faults), "--port", str(port), "--recorded", FIXTURES], stdout=subprocess.DEVNULL)
    wait_up(port)
    return p, port, faults


def wait_up(port, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            if Chat.call(type("X", (), {"port": port}), "GET", "/api/health", timeout=2)[0] == 200:
                return time.time() - t0
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"port {port} not up")


def set_faults(path, **faults):
    path.write_text(json.dumps(faults))


def spawns(path, stage):
    log = Path(f"{path}.spawns")
    return [l.split()[1] for l in log.read_text().splitlines() if l.split()[0] == stage] if log.exists() else []


# 2 and 5. The whole server, with real children swapped for failing ones.
def server_faults(tmp):
    p, port, faults = start_fault(tmp, "server")
    log = srv.RUNS / f"recovery-{port}.log"
    try:
        # A first brief whose build hangs twice has no world to go back to.
        chat = Chat(port)
        set_faults(faults, build=["sleep", "sleep"])
        seconds = chat.say(BRIEF)
        said = chat.lines()
        check("a build that hangs twice stops, and the chat says so", any("The build froze, so I restarted it." == l for l in said) and any("The build froze again" in l and "went back to the start" in l for l in said), f"{seconds:.1f} s")
        check("the session is not busy after it", chat.state() == {"phase": "brief", "busy": False}, chat.state())

        # The same chat works, and a run that hangs once gives the run it would have given.
        set_faults(faults, run=["sleep"])
        seconds = chat.say(BRIEF)
        said = chat.lines()
        check("a run that hangs once is killed and retried, and the chat says it in one line", said.count("The test run froze, so I restarted it.") == 1 and spawns(faults, "run") == ["sleep", "real"], f"{seconds:.1f} s")
        trial = [e for e in chat.events() if e["type"] == "trial"]
        check("that chat ends with a run to watch", trial and trial[-1]["tid"] == "normal-2", chat.state())
        run_dir = srv.RUNS / chat.sid / "normal_2"
        direct = tmp / "direct"
        subprocess.run([PY, str(POLICY / "highrise" / "run_trial.py"), str(run_dir / "world.json"), "--seed", "1001", "--out", str(direct)], stdout=subprocess.DEVNULL, check=True)
        got, want = json.loads((run_dir / "result.json").read_text()), json.loads((direct / "result.json").read_text())
        check("the retried run has the same final state as a direct run, so the outcome did not change", got["final_state_sha256"] == want["final_state_sha256"] and got["outcome"] == want["outcome"], got["final_state_sha256"][:12])

        # A follow-up whose run hangs twice puts the last good world back.
        good = chat.last_world()["hash"]
        set_faults(faults, run=["sleep", "sleep"])
        at = len(chat.events())
        seconds = chat.say(CHANGE)
        said = chat.lines(at)
        check("a follow-up whose run hangs twice puts back the last good world", any("put back the last good world" in l for l in said) and chat.last_world()["hash"] == good, f"{seconds:.1f} s, {said[-1]}")
        check("the page is told to show the last good run again", [e["tid"] for e in chat.events()[at:] if e["type"] == "trial"] == ["normal-2"])
        check("the chat stands where it stood", chat.state() == {"phase": "review_scene", "busy": False}, chat.state())
        check("the log names cause and action", "cause=run froze again: no CPU use and no output" in log.read_text() and "action=killed its process group, gave up" in log.read_text())

        # An AI call and an export that hang.
        set_faults(faults, route=["sleep"], export=["sleep"])
        at = len(chat.events())
        seconds = chat.say(CHANGE)
        said = chat.lines(at)
        check("a hung AI call and a hung export are each killed and retried", "The AI call froze, so I restarted it." in said and "The replay export froze, so I restarted it." in said, f"{seconds:.1f} s")
        check("the run still plays after them", any(e["type"] == "trial" for e in chat.events()[at:]))

        # A slow but live run is left alone.
        set_faults(faults, run=["slow"])
        at = len(chat.events())
        seconds = chat.say(CHANGE)
        check("a slow run with a heartbeat is left alone past its 20 s limit", seconds >= 30 and not any("froze" in l for l in chat.lines(at)) and spawns(faults, "run")[-1] == "slow", f"{seconds:.1f} s")

        # A worker thread that hangs. No child is to blame, so only the watchdog can see it.
        good = chat.last_world()["hash"]
        set_faults(faults, thread=1)
        at, n, t0 = len(chat.events()), chat.idle(), time.time()
        chat.call("POST", f"/api/sessions/{chat.sid}/message", {"text": CHANGE})
        seconds = chat.wait_idle(n, 40)
        said = chat.lines(at)
        check("the watchdog clears a hung worker thread, and says so", any("A step stopped answering" in l for l in said) and not chat.state()["busy"], f"{seconds:.1f} s")
        check("the last good world comes back after it", chat.last_world()["hash"] == good)
        check("the watchdog wrote its log line", "job worker silent" in log.read_text())
        seconds = chat.say(CHANGE)
        check("the next message works, so no slot leaked", any(e["type"] == "trial" for e in chat.events()[at:]) and not chat.state()["busy"], f"{seconds:.1f} s")

        # A crash and a divergence are results. They get no retry and no nicer outcome.
        set_faults(faults, run=["crash"])
        at, before = len(chat.events()), len(spawns(faults, "run"))
        seconds = chat.say(CHANGE)
        said = chat.lines(at)
        check("a crashed run is reported as a failed run, with no retry", len(spawns(faults, "run")) == before + 1 and any("crashed with exit code 3" in l and "did not retry" in l for l in said) and not any("froze" in l for l in said), said[-1])
        check("the chat is free after a crash", not chat.state()["busy"])
        chat.say("make it snow")  # Back to a sound run before the next fault.
        set_faults(faults, run=["diverge"])
        at, before = len(chat.events()), len(spawns(faults, "run"))
        seconds = chat.say(CHANGE)
        said = chat.lines(at)
        check("a run that diverges is reported as a failed run, with no retry", len(spawns(faults, "run")) == before + 1 and any("physics could not finish this run" in l and "failed run" in l for l in said) and not any("froze" in l for l in said), [l for l in said if "physics" in l])
        check("the chat is free after a divergence", not chat.state()["busy"])
    finally:
        p.terminate()
        p.wait()


# 3. The supervisor, with a real stop and a real kill.
def supervisor(tmp):
    port = free_port()
    faults = tmp / "super.json"
    faults.write_text("{}")
    log = srv.RUNS / f"recovery-{port}.log"
    sup = subprocess.Popen([PY, str(HERE / "supervise.py"), "--port", str(port), "--script", str(HERE / "fault_server.py"), "--faults", str(faults), "--recorded", FIXTURES], stdout=subprocess.DEVNULL)
    try:
        wait_up(port)
        chat = Chat(port)
        chat.say(BRIEF)
        world = chat.last_world()["hash"]
        pid = chat.call("GET", "/api/health")[1]["pid"]

        t0 = time.time()
        os.kill(pid, signal.SIGSTOP)
        time.sleep(3)
        wait_up(port, 60)
        new = chat.call("GET", "/api/health")[1]["pid"]
        check("a stopped server is killed and comes back", new != pid, f"{time.time() - t0:.1f} s")
        state = chat.state()
        check("the chat survives the restart", state == {"phase": "review_scene", "busy": False}, state)
        said = chat.lines()
        check("the chat says it in one line", said.count("The run server froze, so I restarted it. Your world is still here.") == 1, said[-1])
        at = len(chat.events())
        chat.say(CHANGE)
        changed = [e for e in chat.events()[at:] if e["type"] == "tool" and e["title"] == "change_world"]
        check("the next message changes the same world", bool(changed) and not chat.state()["busy"], changed[-1]["lines"] if changed else "")
        check("the world came through", world != "" and chat.last_world()["world"]["suction_pa"] is not None)

        pid = chat.call("GET", "/api/health")[1]["pid"]
        t0 = time.time()
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        wait_up(port, 60)
        check("a killed server comes back", chat.call("GET", "/api/health")[1]["pid"] != pid, f"{time.time() - t0:.1f} s")
        chat.state()  # A restarted server loads a chat when it is first asked for it, as a page does on reconnect.
        check("the chat says that too", "The run server crashed, so I restarted it. Your world is still here." in chat.lines(), chat.lines()[-1])
        check("the supervisor's log has both", "failed 3 health checks" in log.read_text() and "exited with code -9" in log.read_text())

        # A server killed mid run leaves a child in its own group. The next server stops it.
        set_faults(faults, run=["sleep"])
        chat.call("POST", f"/api/sessions/{chat.sid}/message", {"text": CHANGE})
        live = srv.RUNS / f"live-{port}.txt"
        t0 = time.time()
        while time.time() - t0 < 20 and not (live.exists() and live.read_text().strip()):
            time.sleep(0.1)
        left = int(live.read_text().split()[0])
        pid = chat.call("GET", "/api/health")[1]["pid"]
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        wait_up(port, 60)
        check("a child left by a killed server is stopped by the next one", not alive(left), left)
        state = chat.state()
        said = chat.lines()
        check("a job cut off by a restart says to send it again", state == {"phase": "review_scene", "busy": False} and "Send your last message again." in said[-1], said[-1])

        taken = subprocess.run([PY, str(HERE / "supervise.py"), "--port", str(port)], capture_output=True, text=True, timeout=20)
        check("the supervisor refuses a port in use, and leaves that server alone", taken.returncode != 0 and "in use" in taken.stderr and chat.call("GET", "/api/health")[0] == 200, taken.stderr.strip())
    finally:
        sup.terminate()
        sup.wait(10)
    time.sleep(0.5)
    with socket.socket() as probe:
        check("stopping the supervisor stops its server", probe.connect_ex(("127.0.0.1", port)) != 0)


def main():
    with tempfile.TemporaryDirectory(prefix="crashlab-hang-") as d:
        tmp = Path(d)
        units(tmp)
        server_faults(tmp)
        supervisor(tmp)
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
