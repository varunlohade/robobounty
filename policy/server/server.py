"""CrashLab run server. DEMO SHORTCUT: a local HTTP server that an embedded runtime can replace. It is not a hosted service.

policy/.venv/bin/python policy/server/server.py [--port 5198] [--recorded DIR]

Binds to 127.0.0.1 only, and accepts only the app's own origin and host, on every route. A request with no Origin header is refused too.
Chat text is untrusted. It goes to the LLM layer on stdin, and only validated values come back. It never reaches a shell, an argv or a path.
Jobs start from fixed argv lists. At most MAX_PROCS sim or LLM processes run at once, across all sessions.
Every child runs under a named deadline in DEADLINES. A worker thread that stops beating is cut loose by the watchdog. Use policy/server/supervise.py to run this server: it restarts a frozen or crashed one, and each session's world and events survive on disk.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine
import ledger as ledger_module
import look as look_module
from stored_fix import STORED_FIX, ab_rows, recorded_fix

POLICY = HERE.parent
HIGHRISE = POLICY / "highrise"
CRASHLAB = POLICY / "crashlab"
RUNS = POLICY / "runs" / "server"
PYTHON = str(POLICY / ".venv" / "bin" / "python")
HOST = "127.0.0.1"
APP_ORIGINS = {"http://localhost:5199", "http://127.0.0.1:5199"}
MAX_PROCS = 4
MAX_BODY_BYTES = 8192
MAX_SESSIONS = 32
MAX_BRIEF_CHARS = 1800
QUICK_WORLDS = 12
HELD_BACK_SHARE = 5  # one world in this many, from each group of 3 or more
LLM_CAP_USD = "0.50"
MAX_LLM_PER_SESSION = 60  # Every chat message is one AI call, and a physics change is a second. 60 is 30 to 60 messages in one chat.
MAX_LLM_PER_HOUR = 200  # across all sessions
MAX_SUBMIT_BODY_BYTES = 64 * 1024  # the gate applies its own lower limit to the world file
GATE = POLICY / "bounty" / "gate.py"
CONTROLLER = HIGHRISE / "controller.py"
# Local test addresses for the ledger's separate roles. They have no key and no wallet.
COMPANY, RESOLVER, ARBITER = ("0x" + c * 40 for c in "abc")
_FINGERPRINT = re.compile(r"^0x[0-9a-f]{64}$")
TRIAL_FILES = {"manifest.json", "model.xml", "qpos.json", "result.json", "world.json", "controller.py.txt", "trace.json", "wind.json", "dirt.bin", "look.json"}
_ID = re.compile(r"^[a-z0-9-]{1,40}$")
_SID = re.compile(r"^[0-9a-f]{32}$")
# A page opens its event stream on <session id>.localhost, so open streams from other tabs never use up the browser's 6 connections per host that fetches need.
_STREAM_HOST = re.compile(r"^[0-9a-f]{32}\.localhost:\d+$")
YES = {"yes", "y", "yep", "ok", "okay", "looks right", "looks good", "it looks right", "correct"}
APPROVE = {"approve", "approved", "approve campaign", "go", "run it"}
CHAPTERS = ("brief", "worlds", "test", "find", "fix", "bounty")
STAGES = ("queued", "running", "reproducing", "diagnosing", "fixing", "validating", "report")

# Asked only when the plan leaves all of a question's fields unset. Each answer is a fixed set of ranges that the plan validator checks.
QUESTIONS = (
    {"id": "wind", "fields": ("steady_wind_ms", "gust_speed_ms"), "text": "How windy is the site on a working day?", "options": (
        ("Calm: up to 1 m/s, gusts to 3", {"steady_wind_ms": (0.0, 1.0), "gust_speed_ms": (0.0, 3.0)}),
        ("Windy: 6-10 m/s, gusts to 13", {"steady_wind_ms": (6.0, 10.0), "gust_speed_ms": (8.0, 13.0)}),
        ("Very windy: 10-15 m/s, gusts to 25", {"steady_wind_ms": (10.0, 15.0), "gust_speed_ms": (15.0, 25.0)}),
        ("Use the default", {}))},
    {"id": "glass", "fields": ("wetness", "dust_gm2"), "text": "What state is the glass in when the robot starts?", "options": (
        ("Dry and clean", {"wetness": (0.0, 0.05), "dust_gm2": (0.0, 1.0)}),
        ("Damp", {"wetness": (0.3, 0.6), "dust_gm2": (0.0, 1.0)}),
        ("Heavy dust", {"wetness": (0.0, 0.05), "dust_gm2": (15.0, 30.0)}),
        ("Use the default", {}))},
)
# How a follow-up names a changed value.
FIELD_WORDS = {
    "steady_wind_ms": ("Wind", " m/s"), "gust_speed_ms": ("Gusts", " m/s"), "gust_start_s": ("First gust at", " s"), "gust_duration_s": ("Gust length", " s"),
    "gust_count": ("Number of gusts", ""), "gust_period_s": ("Time between gusts", " s"), "wind_dir_deg": ("Wind direction", " degrees"), "wetness": ("Wetness", ""),
    "mullion_depth_m": ("Joint depth", " m"), "mullion_spacing_m": ("Joint spacing", " m"), "mullion_offset_m": ("Joint offset", " m"), "joint_gap_m": ("Joint gap", " m"),
    "edge_margin_m": ("Edge margin", " m"), "area_width_m": ("Work area width", " m"), "area_height_m": ("Work area height", " m"), "drop_below_roof_m": ("Drop below the roof", " m"),
    "suction_pa": ("Suction", " Pa"), "seal_leak_mm2": ("Seal leak", " mm2"), "battery_start_frac": ("Battery at the start", ""), "pad_force_n": ("Pad force", " N"),
    "dirt_level": ("Dirt", ""), "ledge_depth_m": ("Ledge depth", " m"), "ledge_below_top_m": ("Ledge below the top", " m"), "ledge_x_m": ("Ledge position", " m"),
    "ledge_width_m": ("Ledge width", " m"), "temperature_c": ("Temperature", " C"), "humidity_pct": ("Humidity", " %"), "dust_gm2": ("Dust", " g/m2"), "sun_level": ("Sun", ""),
}
REJECTION_WORDS = {
    "brief_too_long": "That is too long for one brief. Keep it under 300 words.",
    "brief_has_control_characters": "That message has control characters, so I did not read it.",
    "brief_empty": "That message is empty.",
    "planner_not_a_scene_request": "That does not describe a robot job I can build.",
    "planner_nothing_buildable": "I found nothing I can build in that. I treated it as text and did not act on it.",
    "planner_unsafe_request": "I will not build that.",
    "plan_failed_validation": "The plan came back with values the validator refused, so nothing changed.",
}


@dataclass(frozen=True)
class Deadline:
    """When a child counts as hung. A child that shows progress is never killed."""
    words: str  # The chat's name for this stage.
    quiet_s: float | None  # No CPU use and no output growth for this long. None when the child only waits on the network, so low CPU says nothing.
    silent_s: float  # No output growth for this long, even with CPU use. An AI call has no output until it ends, so this is its whole limit.
    ai: bool = False  # A retry is one more AI call, and counts against the limits.


# Times measured on this Mac on 2026-11-06. AI limits sit above llm.py's own timeouts, so its plain "timeout" answer comes first.
DEADLINES = {
    "route": Deadline("The AI call", None, 120, ai=True),  # llm.py gives a route call 90 s.
    "plan": Deadline("The planner", None, 300, ai=True),  # llm.py gives a plan call 240 s.
    "scenarios": Deadline("The scenario agent", None, 600, ai=True),  # 240 s for the AI, then one build for each world.
    "build": Deadline("The build", 60, 180),  # Measured about 1 s.
    "requirements": Deadline("The requirements check", 30, 120),  # Measured 0.1 s.
    "run": Deadline("The test run", 60, 180),  # Measured 2.8 to 28 s over 91 runs. A heartbeat from each step counts as output, so a long run that steps has no limit.
    "export": Deadline("The replay export", 60, 300),  # Measured 2.8 s for 6730 frames.
    "campaign": Deadline("The campaign", 180, 1200),  # Each finished world grows results.jsonl. One world took at most 28 s.
    "trace": Deadline("The code trace", 180, 1800),  # Not timed here: wide on purpose.
    "diagnose": Deadline("The diagnosis", 180, 1800),  # Not timed here: wide on purpose.
    "fix": Deadline("The fix test", None, 3600, ai=True),  # fix.py gives its AI call 400 s, then tests 24 or more worlds.
    "gate": Deadline("The bounty gate", 180, 1500),  # gate.py gives each run 300 s.
    "bounty": Deadline("The bounty step", 30, 120),  # A small file step.
}
POLL_S = 1.0
CPU_SIGN_S = 0.05  # Group CPU change that counts as alive. A sleeping process adds nothing.
WORKER_QUIET_S = 120  # A worker thread beats at least once a second, except for file reads that take far under this.
WATCHDOG_POLL_S = 5
PING_S = 5  # The page calls its stream dead after 3 missed pings.
PORT = None
RESTART_CAUSE = None
RECOVERY_LOCK = threading.Lock()
BROWSER_FIXES = {
    "stream_lost": ("the page lost its event stream", "reconnected from the last event"),
    "webgl_lost": ("the browser lost the WebGL context", "rebuilt the view at the same frame"),
    "webgl_gave_up": ("the WebGL context kept getting lost", "stopped rebuilding and asked for a reload"),
    "playback_stalled": ("the replay stopped advancing while set to play", "restarted it from the same frame"),
    "playback_gave_up": ("the replay kept stopping", "stopped restarting and asked for a reload"),
    "reply_late": ("the server did not answer a request by its deadline", "told the user to send it again"),
    "trial_retry": ("a replay file did not load by its deadline", "fetched the replay again"),
    "trial_failed": ("a replay file did not load after retries", "told the user"),
}
_tls = threading.local()


class Abandoned(BaseException):
    """Ends a worker thread the watchdog already cut loose, the next time it wakes. It is not an Exception, so no job handler catches it."""


class StageHung(Exception):
    def __init__(self, name, why):
        super().__init__(name)
        self.name, self.why = name, why


def beat():
    w = getattr(_tls, "worker", None)
    if w:
        if w.abandoned:
            raise Abandoned
        w.at = time.monotonic()


def recovery_log(session, cause, action):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} session={session.id if session else '-'} cause={cause} action={action}\n"
    with RECOVERY_LOCK:
        with open(RUNS / f"recovery-{PORT}.log", "a") as f:
            f.write(line)


class Slots:
    """A counting gate that takes several slots at once, so a campaign cannot starve behind single jobs forever or exceed the limit. It knows each thread's slots, so the watchdog can take them back."""

    def __init__(self, n):
        self.free, self.cond, self.held = n, threading.Condition(), Counter()

    def take(self, n):
        with self.cond:
            while self.free < n:
                self.cond.wait(POLL_S)
                beat()
            self.free -= n
            self.held[threading.current_thread()] += n

    def give(self, n):
        with self.cond:
            me = threading.current_thread()
            back = min(n, self.held[me])  # Zero for a thread the watchdog cut loose.
            self.held[me] -= back
            if not self.held[me]:
                del self.held[me]
            self.free += back
            self.cond.notify_all()

    def drop(self, thread):
        with self.cond:
            self.free += self.held.pop(thread, 0)
            self.cond.notify_all()


SLOTS = Slots(MAX_PROCS)
LIVE = set()
LIVE_LOCK = threading.Lock()
RECORDED = None


class LlmLimit:
    """Counts every LLM call before it starts: per session and, over the last hour, across all sessions."""

    def __init__(self):
        self.session_cap, self.hour_cap = MAX_LLM_PER_SESSION, MAX_LLM_PER_HOUR
        self.lock, self.times = threading.Lock(), []

    def take(self, session):
        with self.lock:
            now = time.time()
            self.times = [t for t in self.times if now - t < 3600]
            if session.llm_used >= self.session_cap:
                return "session"
            if len(self.times) >= self.hour_cap:
                return "global"
            session.llm_used += 1
            self.times.append(now)
        session.emit(type="llm_count", used=session.llm_used, cap=self.session_cap)
        return None


LLM_LIMIT = LlmLimit()


def spawn(argv, **kw):
    # Own process group, so shutdown can stop a campaign and its pool. Low priority, so the Mac stays usable.
    env = {**os.environ, "CRASHLAB_RECORDED_REPLIES": RECORDED} if RECORDED else None
    p = subprocess.Popen(["nice", "-n", "5", *argv], start_new_session=True, env=env, **kw)
    p.owner = threading.current_thread()
    with LIVE_LOCK:
        LIVE.add(p)
        write_live()
    return p


def finish(p):
    with LIVE_LOCK:
        LIVE.discard(p)
        write_live()


def write_live():
    """The live child groups, so a server that starts after a kill -9 can stop what the dead one left."""
    if PORT:
        (RUNS / f"live-{PORT}.txt").write_text("".join(f"{p.pid}\n" for p in LIVE))


def kill_leftovers():
    path = RUNS / f"live-{PORT}.txt"
    if not path.exists():
        return
    for pid in path.read_text().split():
        command = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
        if str(POLICY) in command:  # A reused pid belongs to something else, and stays alive.
            kill_group(int(pid))
            recovery_log(None, f"child group {pid} outlived the last server", "killed it")
    path.unlink()


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def group_cpu(pgid):
    """CPU seconds of one process group. None when ps gives no answer, which proves nothing either way."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pgid=,time="], capture_output=True, text=True, timeout=5).stdout
    except subprocess.TimeoutExpired:
        return None
    total = 0.0
    for line in out.splitlines():
        group, spent = line.split()
        if int(group) == pgid:
            total += sum(float(part) * 60 ** i for i, part in enumerate(reversed(spent.split(":"))))
    return total


def marks(paths):
    seen = []
    for path in paths:
        try:
            st = os.stat(path)
            seen.append((st.st_size, st.st_mtime_ns))
        except FileNotFoundError:
            seen.append(None)
    return seen


def watch(p, rule, stdin, paths, tick):
    """Waits for a child. Returns (stdout, None) when it ended, or (None, why) when it missed its deadline."""
    signal_at = output_at = time.monotonic()
    seen, cpu, polls = marks(paths), group_cpu(p.pid) if rule.quiet_s is not None else None, 0
    send = stdin
    while True:
        beat()
        try:
            if p.stdout or p.stdin:
                return p.communicate(send, timeout=POLL_S)[0], None
            p.wait(POLL_S)
            return None, None
        except subprocess.TimeoutExpired:
            send = None
        if tick:
            tick()
        now, polls = time.monotonic(), polls + 1
        mark = marks(paths)
        if mark != seen:
            seen, signal_at, output_at = mark, now, now
        if rule.quiet_s is not None and polls % 2 == 0:
            used = group_cpu(p.pid)
            if used is not None and (cpu is None or abs(used - cpu) >= CPU_SIGN_S):
                cpu, signal_at = used, now
            if now - signal_at > rule.quiet_s:
                return None, f"no CPU use and no output for {now - signal_at:.0f} s"
        if now - output_at > rule.silent_s:
            return None, f"no output for {now - output_at:.0f} s"


def watched(name, argv, stdin=None, paths=(), tick=None, before_retry=None, **kw):
    """Runs a child under its deadline. On a miss it kills the process group and retries once. Returns (exit code, stdout).
    A child that ends, whatever its exit code, is a result and is not retried. Raises StageHung on the second miss."""
    rule, session = DEADLINES[name], getattr(getattr(_tls, "worker", None), "session", None)
    for attempt in (1, 2):
        p = spawn(argv, **({"stdin": subprocess.PIPE} if stdin is not None else {}), **kw)
        try:
            out, why = watch(p, rule, stdin, paths, tick)
        except BaseException:
            kill_group(p.pid)
            raise
        finally:
            finish(p)
        if why is None:
            return p.returncode, out
        kill_group(p.pid)
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            recovery_log(session, f"{name} pid {p.pid} survived SIGKILL for 5 s", "left it and went on")
        if attempt == 2:
            recovery_log(session, f"{name} froze again: {why}", "killed its process group, gave up")
            raise StageHung(name, why)
        recovery_log(session, f"{name} froze: {why}", "killed its process group, retried once")
        if session:
            session.say(f"{rule.words} froze, so I restarted it.")
            if rule.ai and not session.llm_allowed():
                raise StageHung(name, why)
        if before_retry:
            before_retry()


def job(script, request, command):
    """Runs plan_job.py in one slot. Returns its JSON reply, or None if it died. Raises StageHung if it froze twice."""
    SLOTS.take(1)
    try:
        partial = Path(request["out"]) if request.get("out") else None
        code, out = watched(command, [PYTHON, str(script), command], stdin=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            before_retry=(lambda: shutil.rmtree(partial, ignore_errors=True)) if partial else None)
        return json.loads(out) if code == 0 else None
    finally:
        SLOTS.give(1)


def run_one(name, argv, stdout_file, paths=()):
    SLOTS.take(1)
    try:
        with open(stdout_file, "wb") as log:
            return watched(name, argv, paths=(stdout_file, *paths), stdout=log, stderr=subprocess.STDOUT)[0]
    finally:
        SLOTS.give(1)


def llm_label():
    if not RECORDED:
        return "claude headless"
    stored = [n for n in ("brief", "followup", "scenarios") if (Path(RECORDED) / f"{n}.json").exists()]
    return f"stored {' and '.join(stored)} reply, check only"


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sim_hash():
    return hashlib.sha256((HIGHRISE / "sim.py").read_bytes()).hexdigest()


def plain_number(v):
    return f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}".removesuffix(".0") if abs(v) >= 1 else f"{v:.3g}"


def changed_words(old, new, fields):
    """The values a follow-up moved, such as Wind 2.1 \u2192 14.8 m/s. A wrong guess by the planner shows here as plain numbers."""
    words = []
    for k in sorted(fields):
        if k == "elements":
            before, after = len(old.get(k, [])), len(new.get(k, []))
            if old.get(k) != new.get(k):
                words.append(f"Scene elements {before} to {after}")
        elif old[k] != new[k]:
            words.append(f"{FIELD_WORDS[k][0]} {plain_number(old[k])} \u2192 {plain_number(new[k])}{FIELD_WORDS[k][1]}")
    return words


def controller_number(name):
    """A limit the run's controller used, read from its source, so the chat cannot drift from the code."""
    for node in ast.parse(CONTROLLER.read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise KeyError(name)


def held_words(result, wind):
    """Why a run ended held on, in plain words. The numbers come from result.json and the run's recorded wind, and the limits from the controller."""
    time_s, hold_s = result["time_s"], result["hold_s"]
    share = "all" if hold_s >= 0.995 * time_s else "most" if hold_s >= 0.5 * time_s else "part"
    pause = f"The robot paused for {share} of the run"
    if result["outcome"] == "wind_hold":
        limit, resume, peak = controller_number("WIND_PAUSE_MS"), controller_number("WIND_RESUME_MS"), max(wind, default=0.0)
        if peak > limit:
            return f"{pause}, because wind of {peak:.1f} m/s is above its {limit:.0f} m/s limit. It waits for wind under {resume:.0f} m/s, and wind during the pause averaged {result['hold_mean_wind_ms']:.1f} m/s."
        return f"{pause}. Wind stayed at or under {peak:.1f} m/s, below its {limit:.0f} m/s limit, and averaged {result['hold_mean_wind_ms']:.1f} m/s during the pause."
    if result["outcome"] == "battery_stop":
        return f"{pause}, because its battery voltage ran low. It ended with {result['end_battery'] * 100:.0f}% of its charge."
    return f"It stopped and held on: {result['outcome']}."


def thumb_and_end(run):
    sys.path.insert(0, str(POLICY))
    import app_export
    return app_export.thumb_and_end(run)


class Worker:
    def __init__(self, session, kind):
        self.session, self.kind, self.phase_before = session, kind, session.phase
        self.at, self.abandoned = time.monotonic(), False


class Session:
    # The values that define where a chat stands. A checkpoint copies them, a freeze puts them back, and session.json keeps them across a restart.
    KEPT = ("world", "normal", "plan", "brief", "phase", "before_weather", "answers", "questions", "answered", "requirements", "shown")

    def __init__(self, sid=None):
        self.id = sid or uuid.uuid4().hex
        self.dir = RUNS / self.id
        self.dir.mkdir(parents=True, exist_ok=bool(sid))
        self.events, self.cond = [], threading.Condition()
        self.events_path = self.dir / "events.jsonl"
        self.stream_at = 0  # The page stream that is live. A newer one closes it.
        self.workers = {}
        self.shown = None
        self.lock = threading.Lock()
        self.busy = False
        self.routing = False  # One AI reading of a message at a time.
        self.before_weather = {}  # World values a weather replaced, so the next weather or "no rain" can put them back.
        self.look = {}  # Scenery for the viewer. It feeds nothing to physics and stays out of world.json.
        self.working_now = None
        self.phase = "brief"
        self.brief = ""
        self.plan, self.answers, self.mapped_fields, self.questions = {}, {}, set(), []
        self.world, self.normal, self.proposal, self.requirements = None, None, None, None
        self.results, self.batches, self.excluded, self.diverged, self.types = {}, 0, {}, [], []
        self.held, self.round = set(), 0
        self.world_seed, self.run_seed, self.answered = 1, 1001, set()  # the same world and the same run conditions for every follow-up
        self.exports = {}
        self.llm_used = 0
        self.last_campaign, self.fix_try, self.fix_summary, self.fix_decision = None, None, None, None
        self.ledger, self.bounty_salt, self.spec_path, self.gate_info, self.verdicts = None, None, None, None, []
        self.last_seconds, self.last_recorded = None, None
        self.tester = "0x" + hashlib.sha256(self.id.encode()).hexdigest()[:40]
        self.good, self.good_events = self.snapshot(), 0

    def snapshot(self):
        values = {k: getattr(self, k) for k in self.KEPT}
        values["answered"] = sorted(self.answered)
        return json.loads(json.dumps(values))

    def checkpoint(self):
        """The chat stands somewhere sound, so a later freeze comes back here."""
        if self.phase not in ("building", "asking"):  # A half answered brief is not a place to come back to: its question cards are gone.
            self.good, self.good_events = self.snapshot(), len(self.events)
        self.save()

    def save(self):
        kept = {"good": self.good, "good_events": self.good_events, "look": self.look, "exports": {k: str(v) for k, v in self.exports.items()}, "llm_used": self.llm_used, "round": self.round}
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(kept))
        tmp.replace(self.dir / "session.json")

    def rewind(self, show=True):
        """Back to the last good world, and the view with it. Returns whether a world is there."""
        for k, v in json.loads(json.dumps(self.good)).items():
            setattr(self, k, set(v) if k == "answered" else v)
        self.results, self.excluded, self.diverged, self.types, self.held, self.proposal = {}, {}, [], [], set(), None
        if self.phase not in ("brief", "asking", "review_scene"):  # Campaign state does not come back.
            self.phase = "review_scene" if self.world else "brief"
        if show and self.world:
            self.emit(type="world", world=self.world["world"], hash=self.world["hash"], xml=self.world["xml"], area=self.world["area"], moved=self.world["moved"], facts=self.world["facts"])
            if self.shown and self.shown in self.exports:
                self.emit(type="trial", tid=self.shown, label="Normal run", passed=self.normal["passed"], open=True)
        elif show:
            self.emit(type="no_world")
        return self.world is not None

    @classmethod
    def load(cls, sid):
        """A chat after a restart. Its events keep their ids, so the page goes on from the last one it saw."""
        s = cls(sid)
        kept = json.loads((s.dir / "session.json").read_text())
        if s.events_path.exists():
            for line in s.events_path.read_text().splitlines():
                try:
                    s.events.append(json.loads(line))
                except ValueError:  # A kill can cut only the last line. That event never reached a page.
                    recovery_log(s, "events.jsonl has a cut line", "skipped it")
        s.good, s.good_events = kept["good"], kept["good_events"]
        s.look, s.llm_used, s.round = kept["look"], kept["llm_used"], kept["round"]
        s.exports = {k: Path(v) for k, v in kept["exports"].items()}
        after = s.events[s.good_events:]
        cut_off = any(e["type"] == "user" or (e["type"] == "working" and e.get("text")) for e in after) and after[-1]["type"] != "idle"
        changed = any(e["type"] == "world" for e in after)
        has_world = s.rewind(show=changed)
        opening = {"froze": "The run server froze, so I restarted it.", "crashed": "The run server crashed, so I restarted it."}.get(RESTART_CAUSE, "The run server restarted.")
        s.emit(type="text", fail=False, restart=True, text=f"{opening} Your {'world' if has_world else 'chat'} is still here.{' Send your last message again.' if cut_off else ''}")
        recovery_log(s, f"server restart, cause {RESTART_CAUSE or 'unknown'}, job cut off: {cut_off}", "restored the session from disk")
        s.working()
        s.emit(type="idle")
        return s

    def launch(self, kind, target, args):
        """Runs target on a worker thread the watchdog can see. A "job" holds the busy flag. A "side" thread does not."""
        worker = Worker(self, kind)

        def body():
            _tls.worker = worker
            try:
                target(*args)
            except StageHung as e:
                self.gave_up(e, worker)
            except Abandoned:
                pass
            except Exception as e:
                traceback.print_exc()
                recovery_log(self, f"job raised {type(e).__name__}", "told the user")
                self.say(f"Job failed: {type(e).__name__}. See the run server log.", fail=True)
            finally:
                if not worker.abandoned:
                    with self.lock:
                        self.workers.pop(thread, None)
                    if kind == "job":
                        self.end_job()
        thread = threading.Thread(target=body, daemon=True)
        with self.lock:
            self.workers[thread] = worker
        thread.start()

    def end_job(self):
        self.working()
        self.checkpoint()
        with self.lock:
            self.busy = False
        self.emit(type="idle")

    def gave_up(self, e, worker):
        """A stage froze twice. The last good world comes back unless the world had not changed."""
        words = DEADLINES[e.name].words
        if worker.kind != "job":
            self.say(f"{words} froze again, so I stopped it. Try again.", fail=True)
            return
        if self.phase == "building" or self.world != self.good["world"]:
            has_world = self.rewind()
            self.say(f"{words} froze again, so I stopped it and {'put back the last good world' if has_world else 'went back to the start'}. Send your message again.", fail=True)
        else:
            self.phase = worker.phase_before
            self.say(f"{words} froze again, so I stopped it. Nothing changed. Send your message again.", fail=True)

    def check_workers(self):
        """The watchdog's look at this session: a worker past its deadline is cut loose, with its children and slots."""
        now = time.monotonic()
        with self.lock:
            stuck = [(t, w) for t, w in self.workers.items() if now - w.at > WORKER_QUIET_S]
            for t, _ in stuck:
                del self.workers[t]
        for thread, worker in stuck:
            worker.abandoned = True
            quiet = now - worker.at
            with LIVE_LOCK:
                mine = [p for p in LIVE if p.owner is thread]
                for p in mine:
                    LIVE.discard(p)
                write_live()
            for p in mine:
                kill_group(p.pid)
            SLOTS.drop(thread)
            self.routing = False
            recovery_log(self, f"{worker.kind} worker silent for {quiet:.0f} s", f"cut it loose, killed {len(mine)} children, cleared the session")
            if worker.kind == "job":
                has_world = self.rewind() if self.phase == "building" or self.world != self.good["world"] else self.world is not None
                self.say(f"A step stopped answering, so I cleared it{' and kept the last good world' if has_world else ''}. Send your message again.", fail=True)
                self.end_job()
            else:
                self.say("A step stopped answering, so I cleared it. Send your message again.", fail=True)

    def llm_allowed(self):
        hit = LLM_LIMIT.take(self)
        if hit:
            words = f"This chat used its {LLM_LIMIT.session_cap} AI calls." if hit == "session" else f"The run server reached its limit of {LLM_LIMIT.hour_cap} AI calls an hour."
            self.tool("llm_limit", "refused", [json.dumps({"limit": hit})])
            self.say(f"{words} Nothing was sent to the AI.", fail=True)
        return not hit

    def emit(self, **event):
        beat()
        with self.cond:
            self.events.append(event)
            with open(self.events_path, "a") as f:
                f.write(json.dumps(event) + "\n")
            self.cond.notify_all()

    def say(self, text, fail=False):
        self.emit(type="text", text=text, fail=fail)

    def tool(self, title, meta, lines, tool_id=None):
        self.emit(type="tool", id=tool_id, title=title, meta=meta, lines=lines)

    def working(self, text=None):
        self.working_now = text
        self.emit(type="working", text=text)

    def chapter(self, name, note=None):
        self.emit(type="chapter", current=name, index=CHAPTERS.index(name), note=note)

    # Requests. Each returns an HTTP status and a small reply.
    def start(self, target, *args):
        with self.lock:
            if self.busy:
                return 409, {"error": "busy"}
            self.busy = True
        self.launch("job", target, args)
        return 202, {"ok": True}

    def message(self, text):
        said = " ".join(text.lower().strip(" .!").split())
        with self.lock:
            if self.routing:
                return 409, {"error": "busy"}
            self.routing = True
            busy = self.busy
        if busy:
            # A running job does not stop a look change. The physics part of the message waits.
            self.emit(type="user", text=text)
            self.launch("side", self.take_brief, (text, True))
            return 202, {"ok": True}
        self.emit(type="user", text=text)
        if self.phase == "review_scene" and said in YES:
            self.routing = False
            return self.start(self.scene_ok)
        if self.phase == "review_campaign" and said in APPROVE:
            self.routing = False
            return self.start(self.approve, None)
        reply = self.start(self.take_brief, text)
        if reply[0] != 202:
            self.routing = False
        return reply

    def action(self, name, value):
        if name == "answer" and self.phase == "asking" and type(value) is int:
            return self.start(self.answer, value)
        if name == "scene_ok" and self.phase == "review_scene":
            return self.start(self.scene_ok)
        if name == "approve" and self.phase in ("review_campaign", "done") and (value is None or value == QUICK_WORLDS):
            return self.start(self.approve, value)
        if name == "replay" and type(value) is int and value in self.results:
            self.launch("side", self.replay, (value,))
            return 202, {"ok": True}
        if name == "fix_recorded" and self.proposal:
            return self.start(self.fix_recorded)
        if name == "fix_live" and self.last_campaign:
            return self.start(self.fix_live)
        if name in ("fix_accept", "fix_reject") and self.fix_try and not self.fix_decision:
            return self.start(self.decide_fix, name == "fix_accept")
        if name == "bounty" and self.proposal:
            return self.start(self.bounty_draft)
        if name == "fund" and self.gate_info and self.ledger is None and isinstance(value, dict):
            return self.start(self.fund, value)
        if name in ("ledger_reject", "ledger_finalize", "ledger_claim") and self.ledger and isinstance(value, str) and _FINGERPRINT.match(value):
            return self.ledger_step(name, value)
        return 409, {"error": "not_now"}

    # Every message goes to the AI first. It chooses engine functions and code checks them. The simple parser stands in only when the AI call fails.
    def route(self, text):
        """(look patch, words for the planner, words nothing can do, whether the AI answered, whether a planner call may follow)."""
        if not self.llm_allowed():
            patch, _ = look_module.parse(text)
            return patch, "", [], True, False
        previous = self.working_now
        self.working("reading your message")
        try:
            reply = job(HERE / "plan_job.py", {"text": text, "look": self.look, "has_world": self.world is not None}, "route")
        except StageHung:
            reply = {"ok": False, "rejection": "froze_twice"}
        self.working(previous)
        if reply is None or not reply["ok"]:
            self.tool("read_message", "failed", [str((reply or {}).get("rejection", "process_died"))])
            self.say("AI did not answer, so I used the simple parser.")
            patch, leftover = look_module.parse(text)
            return patch, leftover, [], False, True
        routed = engine.check_reply(reply["reply"], text)
        self.tool("read_message", f"ok, {reply['seconds']} s", [json.dumps({"tools": routed.tools, "refused": routed.refused})])
        return routed.look, routed.planner_words, routed.uncovered, True, True

    def weather_ranges(self, patch):
        """The world fields one weather message moves, as exact ranges. A value the weather replaced is kept, so the next weather or "no rain" puts it back. Empty for a look that is only scenery."""
        if not any(k in patch for k in look_module.WEATHER_FIELDS):
            return {}
        target = {}
        for kind in look_module.WEATHER_FIELDS:
            if patch.get(kind, self.look.get(kind)):
                for field, value in look_module.WEATHER_PHYSICS[kind].items():
                    target[field] = max(target.get(field, value), value)
        current = self.world["world"] if self.world else json.loads((HIGHRISE / "worlds" / "nominal.json").read_text())
        for field in target:
            self.before_weather.setdefault(field, current[field])
        for field in [f for f in self.before_weather if f not in target]:
            target[field] = self.before_weather.pop(field)
        return {f: {"min": v, "max": v} for f, v in target.items() if not self.world or current[f] != v}

    def apply_look(self, patch):
        before = self.look
        self.look = look_module.merged(before, patch)
        self.write_look()
        self.save()
        self.emit(type="look", look=self.look, sent=time.time() * 1000)
        for line in look_module.words(patch, before, self.world is not None):
            self.say(line)

    def write_look(self):
        for folder in list(self.exports.values()):
            (folder / "look.json").write_text(json.dumps(self.look))

    def take_brief(self, text, job_running=False):
        try:
            patch, words, uncovered, _, planner_ok = self.route(text)
        except Exception as e:
            traceback.print_exc()
            self.say(f"Job failed: {type(e).__name__}. See the run server log.", fail=True)
            return
        finally:
            if not _tls.worker.abandoned:
                self.routing = False
        patch = look_module.one_weather(patch)
        weather = {} if job_running else self.weather_ranges(patch)
        if patch:
            self.apply_look(patch)
        if uncovered:
            self.say(f"I cannot do that yet: {' '.join(uncovered)}.")
        elif not patch and not words and planner_ok:
            self.say("I cannot do that yet.")
        if job_running and (words and planner_ok or any(patch.get(k) for k in look_module.WEATHER_FIELDS)):
            self.say("I am still working on the last step. Send the rest again when it finishes.")
            return
        if not weather and (not words or not planner_ok):
            return
        if words and planner_ok:
            self.plan_words(words, patch, weather)
        elif self.world:
            self.change_weather(weather)
        else:
            self.plan.update(weather)

    def change_weather(self, weather):
        """The physics half of a weather word. No planner call: code sets the values, and they pass the same build checks as any plan."""
        self.emit(type="retire")
        old = self.plan
        self.plan = {**old, **weather}
        self.build(change=(old, set(weather)))

    # Steps 1 to 4: quick questions, build, look, requirements, one normal run.
    def plan_words(self, text, patch, weather=None):
        self.emit(type="retire")
        joined = f"{self.brief} {text}".strip()
        if len(joined) > MAX_BRIEF_CHARS:
            self.say(REJECTION_WORDS["brief_too_long"], fail=True)
            return
        self.chapter("brief")
        if not self.llm_allowed():
            return
        follow_up = self.world is not None
        self.working("reading your change" if follow_up else "reading the brief")
        reply = job(HERE / "plan_job.py", {"text": text, "current": self.world["world"]} if follow_up else {"text": joined}, "plan")
        if reply is None:
            self.say("The planner process died, so nothing changed.", fail=True)
            return
        if not reply["ok"]:
            code = reply["rejection"]
            self.tool("plan_world", "rejected", [json.dumps({"rejection": code, "llm_s": reply.get("seconds")})])
            self.say(REJECTION_WORDS.get(code, f"The planner could not answer ({code}). Nothing changed."), fail=True)
            return
        old, new = self.plan, {**{k: dict(v) for k, v in reply["plan"].items()}, **(weather or {})}
        self.brief, self.plan = joined, {**old, **new}
        if "elements" in old and "elements" in new:
            self.plan["elements"] = {**old["elements"], **new["elements"]}
        self.tool("plan_world", f"ok, {reply['seconds']} s", [json.dumps({k: sorted(v) if k == "elements" else [v["min"], v["max"]] for k, v in new.items()}) if new
                                                               else "The brief sets no value, so defaults stand for now."])
        for item in reply["could_not_build"]:
            # A word the look already used is done, so the chat does not also call it not built.
            if set(look_module.parse(item["words"])[0]) & set(patch):
                continue
            self.tool("could_not_build", item["reason"], [item["words"], item["why"]])
        if reply["not_accounted_for"]:
            self.tool("not_used", "words", [" ".join(reply["not_accounted_for"])])
        if follow_up:
            if new:
                self.build(change=(old, set(new)))
            else:
                self.say("I cannot do that yet. The world stays as it was.")
            return
        self.questions = [q for q in QUESTIONS if q["id"] not in self.answered and not set(q["fields"]) & set(self.plan)][:2]
        self.answers = {}
        if self.questions:
            self.phase = "asking"
            self.say(f"{len(self.questions)} quick question{'s' if len(self.questions) > 1 else ''} before I build this.")
            self.ask()
            return
        self.build()

    def ask(self):
        q = self.questions[0]
        self.emit(type="card", title=q["text"], body="The brief did not say.",
                  actions=[{"label": o[0], "action": "answer", "value": i} for i, o in enumerate(q["options"])])

    def answer(self, value):
        q = self.questions[0]
        if not 0 <= value < len(q["options"]):
            return
        self.emit(type="retire")
        label, ranges = q["options"][value]
        self.emit(type="user", text=label)
        for name, (low, high) in ranges.items():
            self.plan[name] = {"min": low, "max": high}
        self.answered.add(q["id"])
        self.questions.pop(0)
        if self.questions:
            self.phase = "asking"
            self.ask()
            return
        self.build()

    def build(self, change=None):
        """change is a follow-up: the plan before it, and the fields it set. It keeps every other value of the current world."""
        self.phase = "building"
        self.chapter("worlds")
        self.results, self.excluded, self.diverged, self.types, self.held, self.proposal = {}, {}, [], [], set(), None
        self.emit(type="reset_campaign")
        self.working("building the world")
        self.round += 1
        folder = self.dir / f"world_{self.round}"
        base = self.world["world"] if change else None
        reply = job(HERE / "plan_job.py", {"plan": self.plan, "seed": self.world_seed, "out": str(folder), "base": base, "changed": sorted(change[1]) if change else None}, "build")
        if not reply or not reply["ok"]:
            code = (reply or {}).get("rejection", "build_process_died")
            if change:
                self.plan = change[0]
            self.tool("build_world", "failed", [code])
            self.say(REJECTION_WORDS.get(code, "That world did not build, so nothing changed."), fail=True)
            self.phase = "brief"
            return
        self.world = reply
        short = {k: reply["world"][k] for k in reply["moved"]}
        if change:
            words = changed_words(base, reply["world"], change[1])
            self.tool("change_world", f"ok, {reply['seconds']} s", words or ["No value moved."])
            self.say(f"{'. '.join(words)}." if words else "The values you named did not move.")
        else:
            self.tool("build_world", f"ok, {reply['seconds']} s", [json.dumps(short or {"moved": "nothing, all defaults"}), f"world {reply['hash'][:12]}"])
        self.emit(type="world", world=reply["world"], hash=reply["hash"], xml=reply["xml"], area=reply["area"], moved=reply["moved"], facts=reply["facts"])
        self.tool("inspect_world", "code check", [json.dumps(reply["facts"])])
        self.requirements_step()
        self.normal_run()

    def requirements_step(self):
        folder = self.dir / "requirements"
        code = run_one("requirements", [PYTHON, str(CRASHLAB / "requirements.py"), str(folder)], self.dir / "requirements.log")
        if code != 0:
            self.requirements = None
            self.say("The requirements table no longer matches the judge, so its list is unknown here.", fail=True)
            return
        self.requirements = json.loads((folder / "requirements.json").read_text())
        self.emit(type="requirements", rows=self.requirements["requirements"], note=self.requirements.get("safe_hold", ""), limits=self.requirements.get("limits", ""))

    def rule_id(self, rule):
        for row in (self.requirements or {}).get("requirements", []):
            if row["rule"] == rule:
                return row["id"], row["severity"]
        return None, "unknown"

    def normal_run(self):
        self.chapter("test")
        self.working("one normal run")
        run = self.dir / f"normal_{self.round}"
        heartbeat = self.dir / f"normal_{self.round}.beat"
        code = run_one("run", [PYTHON, str(HERE / "run_beat.py"), str(heartbeat), self.world["path"], "--seed", str(self.run_seed), "--out", str(run)], self.dir / "normal.log", paths=(heartbeat,))
        if code != 0:
            self.tool("run_trial", "failed", [f"exit {code}"])
            self.say(f"The test run crashed with exit code {code}. This is a failed run, and I did not retry it. Log: normal.log in the session folder.", fail=True)
            self.phase = "brief"
            return
        result = json.loads((run / "result.json").read_text())
        self.normal = result
        self.tool("run_trial", f"{result['wall_s']} s", [json.dumps({"passed": result["passed"], "outcome": result["outcome"], "failure": result["failure"],
                                                                     "coverage": result["coverage"], "min_pressure_pa": result["min_pressure_pa"], "time_s": result["time_s"]})])
        self.emit(type="sim", sha=result["code_sha256"]["sim.py"], now=sim_hash())
        diverged = result["failure"] == "sim_diverged"
        if diverged:  # A result, not a hang. It is said before the export, so a refused replay cannot hide it.
            self.say(f"The physics could not finish this run ({str(result['diverged_reason']).replace('_', ' ')}), so it counts as a failed run. I did not retry it.", fail=True)
        self.working("exporting the replay")
        tid = f"normal-{self.round}"
        if not self.export(run, tid, "Normal run"):
            self.phase = "brief"
            return
        self.working()  # The export is done. The page may take a while to fetch the replay, and that is not this step.
        self.shown = tid
        self.emit(type="trial", tid=tid, label="Normal run", passed=result["passed"], open=True)
        self.phase = "review_scene"
        cleaned = f"It cleaned {result['coverage'] * 100:.1f}%."
        word = cleaned if diverged else f"It passed. {cleaned}" if result["passed"] else f"It failed: {result['failure']}. {cleaned}" if result["failure"] else f"{held_words(result, json.loads((self.exports[tid] / 'wind.json').read_text()))} {cleaned}"
        self.emit(type="card", title="Does the scene look right?", body=f"{word} Watch the run on the right. Say what to change, or confirm.", result=word,
                  actions=[{"label": "Looks right", "action": "scene_ok", "primary": True}])

    def export(self, run, tid, label):
        out = self.dir / "exports" / tid
        code = run_one("export", [PYTHON, str(POLICY / "app_export.py"), "trial", str(run), tid, label, "--out", str(out)], self.dir / "export.log")
        if code != 0:
            self.say("The replay export refused this run. The sim may have changed since it was recorded. Run it again.", fail=True)
            return False
        self.exports[tid] = out
        (out / "look.json").write_text(json.dumps(self.look))
        return True

    def replay(self, index):
        r = self.results[index]
        tid = f"world-{index}"
        self.working(f"exporting {r['name']}")
        t0 = time.time()
        try:
            if tid in self.exports or self.export(Path(r["run"]), tid, f"{r['group']}, {r['name']}"):
                self.tool("export_replay", f"{time.time() - t0:.1f} s", [json.dumps({"world": r["name"], "failure": r["failure"]})])
                self.emit(type="trial", tid=tid, label=r["name"], passed=r["passed"], open=True)
                if not r["passed"] and self.types:
                    self.chapter("find")
        finally:
            self.working()

    # Step 5: scenario agent and the campaign review.
    def scene_ok(self):
        self.emit(type="retire")
        if not self.llm_allowed():
            self.phase = "review_scene"
            return
        self.working("working out what could go wrong")
        folder = self.dir / f"scenarios_{self.round}"
        t0 = time.time()
        reply = job(HERE / "plan_job.py", {"text": self.brief, "seed": self.round, "out": str(folder)}, "scenarios")
        if reply is None or reply["verdict"] != "build" or not reply["worlds"]:
            code = (reply or {}).get("rejection", "process_died")
            self.tool("scenario_agent", "rejected", [str(code)])
            self.say("The scenario agent gave nothing I could use. Tell me more about the job, or try again.", fail=True)
            return
        self.tool("scenario_agent", f"ok, {time.time() - t0:.1f} s", [json.dumps({"worlds": reply["total_worlds"], "groups": len(reply["groups"]), "capped": reply["capped"]}), reply["count_reason"]])
        self.proposal = {"folder": folder, **reply}
        counts = Counter()
        sizes = Counter(w["group"] for w in reply["worlds"])
        for i, w in enumerate(reply["worlds"]):
            counts[w["group"]] += 1
            n = sizes[w["group"]]
            if n >= 3 and counts[w["group"]] > n - max(1, n // HELD_BACK_SHARE):
                self.held.add(i)
        worlds = [{"index": i, "name": Path(w["file"]).stem, "group": w["group"], "reason": w["reason"], "held": i in self.held} for i, w in enumerate(reply["worlds"])]
        self.emit(type="plan", total=reply["total_worlds"], groups=[{"name": g["name"], "reason": g["reason"]} for g in reply["groups"]],
                  worlds=worlds, not_tested=reply["not_tested"], count_reason=reply["count_reason"], held=len(self.held))
        self.review()

    def review(self):
        reply = self.proposal
        to_run = reply["total_worlds"] - len(self.held)
        variations = []
        for g in reply["groups"]:
            ranges = ", ".join([f"{k} {v['min']}-{v['max']}" for k, v in g["ranges"].items()] + [f"scene element {k}" for k in g.get("elements") or {}])
            variations.append(f"{g['name']} ({g['worlds_built']}): {ranges}")
        wall = self.normal["wall_s"] if self.normal else None
        estimate = f"about {wall * to_run / MAX_PROCS:.0f} s on this Mac, on {MAX_PROCS} processes. One normal run is the only sample behind this." if wall else "unknown"
        self.phase = "review_campaign"
        actions = [{"label": f"Approve: test on {to_run} worlds", "action": "approve", "primary": True}]
        if to_run > QUICK_WORLDS:
            actions.append({"label": f"Approve first {QUICK_WORLDS} only", "action": "approve", "value": QUICK_WORLDS})
        reqs = [f"{r['id']} {r['text']}" for r in (self.requirements or {}).get("requirements", [])] or ["unknown"]
        self.emit(type="review", title=f"Test this on {reply['total_worlds']} worlds", sections=[
            {"head": "Objective", "lines": ["The robot cleans its glass, stays on, and reports the truth, in each world below."]},
            {"head": "Pass or fail, the same for every world", "lines": reqs},
            {"head": "Allowed variations", "lines": variations},
            {"head": "World count", "lines": [f"{reply['total_worlds']} worlds: {to_run} to run, {len(self.held)} held back to check a fix.", reply["count_reason"]] + ([reply["elements_note"]] if reply.get("worlds_with_elements") and reply.get("elements_note") else [])},
            {"head": "Expected compute", "lines": [estimate, "Cloud spend: none, it runs here.", f"LLM spend: unknown, capped at {LLM_CAP_USD} USD a call by llm.py."]},
            {"head": "Included in this model", "lines": [", ".join(sorted({k for g in reply["groups"] for k in g["ranges"]}))]},
            {"head": "Outside this model", "lines": [", ".join(t["factor"] for t in reply["not_tested"]) or "none listed"]},
        ], actions=actions)

    # Steps 6, 7 and 10: the pipeline, failure groups, excluded runs and the report.
    def pipeline(self, now, **notes):
        at = STAGES.index(now)
        off = {} if now == "fixing" or notes.get("fixing") else {"fixing": "not tried", "validating": "not run"}
        self.emit(type="pipeline", stages=[{"name": s, "state": "off" if s in off and i <= at else "done" if i < at else "now" if i == at else "todo",
                                            "note": notes.get(s) or off.get(s)} for i, s in enumerate(STAGES)])

    def approve(self, limit):
        self.emit(type="retire")
        worlds = self.proposal["worlds"]
        waiting = [i for i in range(len(worlds)) if i not in self.held and i not in self.results]
        if not waiting:
            self.say("Every world that is not held back has already run.")
            return
        chosen = self.spread(waiting, limit) if limit else waiting
        self.phase = "running"
        self.pipeline("queued")
        self.batches += 1
        batch = self.proposal["folder"] / f"batch_{self.batches}"
        batch.mkdir()
        plan = {"worlds": [{"file": str(Path("..") / worlds[i]["file"]), "group": worlds[i]["group"]} for i in chosen], "llm_reply": self.proposal.get("llm_reply")}
        (batch / "scenarios.json").write_text(json.dumps(plan))
        out = batch / "campaign"
        self.working(f"waiting for {MAX_PROCS} free processes")
        SLOTS.take(MAX_PROCS)
        started = time.time()
        rows = []
        try:
            self.pipeline("running")
            self.working(f"running {len(chosen)} worlds")
            with open(self.dir / "campaign.log", "ab") as log:
                argv = [PYTHON, str(HIGHRISE / "campaign.py"), "--scenarios", str(batch), "--seed", str(30 + self.batches), "--controls", "2",
                        "--out", str(out), "--procs", str(MAX_PROCS)]
                seen = [0]

                def tick():
                    seen[0] = self.read_results(out, chosen, seen[0], rows, started)
                # A retry resumes: campaign.py skips the trials already in results.jsonl.
                code = watched("campaign", argv, paths=(out / "results.jsonl",), tick=tick, stdout=log, stderr=subprocess.STDOUT)[0]
                tick()
        finally:
            SLOTS.give(MAX_PROCS)
        if code != 0:
            self.say("The campaign stopped with an error. Its log is campaign.log in the session folder. Results above are real but incomplete.", fail=True)
            self.phase = "review_campaign"
            return
        recorded = next((r["sim_sha"] for r in rows if r.get("sim_sha")), None)
        self.emit(type="sim", sha=recorded, now=sim_hash())
        self.pipeline("reproducing", diagnosing="same step")
        self.working("repeating failures and tracing them to code")
        diagnosis = self.diagnose(out)
        self.pipeline("report", diagnosing=None if diagnosis else "failed, see log")
        self.group_failures(diagnosis, chosen)
        self.emit(type="sim", sha=recorded, now=sim_hash())
        self.last_campaign, self.last_seconds, self.last_recorded = out, time.time() - started, recorded
        self.report()
        self.phase = "done"
        self.chapter("find", None if self.types else "No failure type found")
        if self.types:
            self.emit(type="card", title="Try a fix", body="fix.py edits a copy of controller.py in a sandbox, then tests it on the same worlds and on held-back worlds the AI never saw.",
                      actions=[{"label": "Show the recorded result", "action": "fix_recorded"}, {"label": "Try a fix live (1 AI call)", "action": "fix_live"}])
        waiting = [i for i in range(len(worlds)) if i not in self.held and i not in self.results]
        if waiting:
            self.emit(type="card", title=f"{len(waiting)} worlds not run yet", body="You approved part of the campaign.",
                      actions=[{"label": f"Run the other {len(waiting)}", "action": "approve"}])
        if self.proposal["not_tested"]:
            self.emit(type="card", title="Not tested", body="No physics for these here, so they get no pass.", items=[t["factor"] for t in self.proposal["not_tested"]],
                      actions=[{"label": "Send to a bounty", "action": "bounty", "keep": True}])

    def spread(self, waiting, limit):
        """Takes worlds from each group in turn, so a short run still covers every risk."""
        groups = {}
        for i in waiting:
            groups.setdefault(self.proposal["worlds"][i]["group"], []).append(i)
        chosen = []
        while len(chosen) < min(limit, len(waiting)):
            for g in groups.values():
                if g and len(chosen) < limit:
                    chosen.append(g.pop(0))
        return sorted(chosen)

    def read_results(self, out, chosen, seen, rows, started):
        path = out / "results.jsonl"
        if not path.exists():
            return seen
        text = path.read_text()
        lines = text.splitlines()
        complete = lines if text.endswith("\n") else lines[:-1]
        for line in complete[seen:]:
            row = json.loads(line)
            rows.append(row)
            if row["kind"] == "control":
                continue
            index = chosen[int(row["trial"][1:])]
            run = out / row["trial"]
            drawn = thumb_and_end(run)
            result = {k: row[k] for k in ("passed", "failure", "fired", "coverage", "time_s", "min_pressure_pa", "seed", "wall_s", "outcome", "group", "slip_m", "peak_tether_n")}
            full = json.loads((run / "result.json").read_text())
            result.update(index=index, name=Path(self.proposal["worlds"][index]["file"]).stem, thumb=drawn["thumb"], end=drawn["end"], run=str(run), fired=full["fired"], kind=row["kind"], world=row["world"])
            self.results[index] = result
            rows[-1]["sim_sha"] = full["code_sha256"]["sim.py"]
            self.emit(type="result", **{k: v for k, v in result.items() if k != "run"})
            done = [r for r in self.results.values() if r["index"] in chosen]
            self.tool("run_trials", f"{time.time() - started:.0f} s", [json.dumps({"n": len(chosen), "done": len(done), "failed": sum(self.counts_as_failed(r) for r in done if r["kind"] == "varied")})], tool_id=f"trials-{self.batches}")
        return len(complete)

    @staticmethod
    def counts_as_failed(r):
        return not r["passed"] and r["failure"] is not None and r["failure"] != "sim_diverged"

    def diagnose(self, out):
        """linetrace.py logs the deciding code line, then diagnose.py repeats each failure and writes the types. Returns its report, or None."""
        t0 = time.time()
        SLOTS.take(MAX_PROCS)
        try:
            for stage, argv in (("trace", [str(HIGHRISE / "linetrace.py"), str(out)]), ("diagnose", [str(CRASHLAB / "diagnose.py"), str(out), "--reproduce"])):
                with open(self.dir / "diagnose.log", "ab") as log:
                    try:
                        code = watched(stage, [PYTHON, *argv, "--procs", str(MAX_PROCS)], paths=(self.dir / "diagnose.log",), stdout=log, stderr=subprocess.STDOUT)[0]
                    except StageHung as e:
                        self.say(f"{DEADLINES[e.name].words} froze again, so I stopped it. Failure types stay unknown.", fail=True)
                        code = "frozen"
                if code != 0:
                    self.tool("diagnose", "failed", [f"{Path(argv[0]).name} exit {code}. Failure types and code lines stay unknown."])
                    return None
        finally:
            SLOTS.give(MAX_PROCS)
        report = json.loads((out / "diagnosis.json").read_text())
        self.tool("diagnose", f"{time.time() - t0:.1f} s", [json.dumps({"failure_types": sum(f["is_failure"] for f in report["failure_types"]), "reproduced": report["reproduce"]["reproduced"],
                                                                        "flaky_excluded": report["reproduce"]["flaky_excluded"], "code_matches_campaign": report["code_matches_campaign"]})])
        return report

    def group_failures(self, diagnosis, chosen):
        at = lambda trial: chosen[int(trial[1:])]
        self.types, self.excluded, other, routes = [], {}, [], []
        if diagnosis:
            for f in diagnosis["reproduce"]["flaky"]:
                self.excluded[at(f["trial"])] = f"Failed once, then came back in {f['same_failure_runs']} of {f['of']} repeats."
            for f in diagnosis["failure_types"]:
                worlds = [at(t) for t in f["trials"] if t.startswith("t")]
                if not f["is_failure"]:
                    other.append({"type": f["type"], "count": f["count"]})
                    continue
                worst = f["worst_world"]
                self.types.append({"id": f"F{len(self.types) + 1}", "rule": f["type"], "requirement": f["requirement"], "severity": f["severity"], "count": f["count"], "worlds": worlds,
                                   "worst": at(worst["trial"]), "worst_name": self.results[at(worst["trial"])]["name"], "worst_measure": worst["measure"], "worst_value": worst["value"],
                                   "code_line": f["code_line"], "code": f.get("code")})
            routes = [{"failure_type": x["failure_type"], "count": len(x["trials"]), "why": x["why"], "needs": x["needs"], "caveat": x.get("caveat", "")} for x in diagnosis["follow_ups"]]
        self.diverged = [i for i in chosen if self.results[i]["failure"] == "sim_diverged"]
        self.emit(type="failures", types=self.types, other=other, routes=routes, known=bool(diagnosis),
                  excluded=[{"index": i, "name": self.results[i]["name"], "why": why} for i, why in self.excluded.items()],
                  diverged=[{"index": i, "name": self.results[i]["name"]} for i in self.diverged], limits="Code lines hold in this simulation only. Not checked against real hardware.")
        if routes:
            self.emit(type="card", title="Code cannot fix these", body="The robot was already at its limit when they began. They need a person or a bounty.",
                      items=[f"{r['failure_type']} in {r['count']} worlds: {r['needs']}" for r in routes],
                      actions=[{"label": "Send to a bounty", "action": "bounty", "keep": True}])

    def report(self):
        run = sum(r["kind"] == "varied" for r in self.results.values())
        apart = len(self.results) - run
        real = sum(t["count"] for t in self.types)
        holds = sum(not r["passed"] and r["failure"] is None and r["kind"] == "varied" for r in self.results.values())
        numbers = [{"n": run, "label": "worlds run"}, {"n": len(self.types), "label": "failure types"}, {"n": real, "label": "worlds failed"},
                   {"n": len(self.excluded), "label": "flaky, excluded"}, {"n": len(self.held), "label": "held back"},
                   {"n": len(self.proposal["not_tested"]), "label": "not tested"}]
        if apart:
            numbers.append({"n": apart, "label": "with scene elements, not counted"})
        self.emit(type="report", numbers=numbers, seconds=round(self.last_seconds, 1), safe_holds=holds, diverged=len(self.diverged),
                  fixes=self.fix_summary or "No fix tried yet. Before and after: none yet.", sim_recorded=self.last_recorded)

    # Step 8: fix.py, live or its stored report. Nothing here writes policy/highrise/controller.py.
    @staticmethod
    def diff_lines(path):
        lines = []
        for line in Path(path).read_text().splitlines()[:200]:
            if line.startswith(("---", "+++", "diff ", "index ")):
                continue
            kind = "add" if line.startswith("+") else "del" if line.startswith("-") else "same"
            lines.append({"kind": kind, "text": line[1:] if kind != "same" or line.startswith(" ") else line})
        return lines

    def offer_fix(self, try_dir, recorded, payload, decided_note):
        self.fix_try = Path(try_dir)
        self.fix_decision = None
        self.chapter("fix", "Recorded result" if recorded else None)
        lines = self.diff_lines(self.fix_try / "patch.diff")
        added = sum(l["kind"] == "add" for l in lines)
        self.emit(type="fix", recorded=recorded, **payload)
        self.emit(type="diff", file="policy/highrise/controller.py", meta=f"+{added} -{sum(l['kind'] == 'del' for l in lines)}", lines=lines, live=True,
                  note=decided_note)

    def fix_recorded(self):
        self.working("reading the stored fix report")
        payload, self.fix_summary, log_line = recorded_fix(sim_hash())
        self.tool("fix_report", "Recorded result", [log_line])
        self.offer_fix(STORED_FIX / "try_2", True, payload, "Recorded result. Accept writes a copy for this session only. controller.py does not change.")
        self.report()

    def fix_live(self):
        out = self.last_campaign
        stored = RECORDED is not None
        if not stored and not self.llm_allowed():
            return
        self.emit(type="retire")
        self.pipeline("fixing", diagnosing=None, fixing="AI call" if not stored else "stored patch, no AI call", validating="next")
        self.working("fix.py: editing a copy, then testing it in the sandbox")
        t0 = time.time()
        argv = [PYTHON, str(CRASHLAB / "fix.py"), "run", str(out), "--tries", "1", "--fresh", str(max(QUICK_WORLDS, 12)), "--fresh-seed", str(777 + self.batches), "--procs", str(MAX_PROCS)]
        if stored:
            argv += ["--patch", str(STORED_FIX / "try_2" / "controller.py"), "--patch-note", "Check run: stored patch, no AI call."]
        SLOTS.take(MAX_PROCS)
        try:
            with open(self.dir / "fix.log", "ab") as log:
                try:
                    code = watched("fix", argv, paths=(self.dir / "fix.log",), stdout=log, stderr=subprocess.STDOUT)[0]
                except StageHung:
                    self.say("The fix test froze again, so I stopped it.", fail=True)
                    code = "frozen"
        finally:
            SLOTS.give(MAX_PROCS)
        if code != 0:
            self.tool("fix", "failed", [f"fix.py exit {code}. No result. Log: fix.log in the session folder."])
            self.fix_summary = "fix.py stopped with an error, so no fix was tested."
            self.report()
            self.offer_recorded()
            return
        overall = json.loads((out / "fix" / "report.json").read_text())
        attempt = overall["tries"][-1]
        try_dir = out / "fix" / f"try_{attempt['try']}"
        self.pipeline("report", diagnosing=None, fixing="done", validating=attempt["status"])
        helped = attempt["status"] == "awaiting_human"
        ab = attempt.get("ab")
        reasons = (attempt.get("verdict") or {}).get("reasons") or []
        conclusion = "helped on the counts. The low-pressure guard check did not run on this patch, so whether the guard still works is unknown." if helped else "did not help" if ab else "The patch did not pass validation, so it was not tested."
        self.tool("fix", f"{time.time() - t0:.0f} s", [json.dumps({"status": attempt["status"], "validation": attempt["validation"], "reasons": reasons})])
        self.fix_summary = f"Fix test on this campaign: {conclusion}"
        if not (try_dir / "patch.diff").exists() or not ab:
            self.say(f"No fix to review: {conclusion}", fail=True)
            self.report()
            self.offer_recorded()
            return
        self.offer_fix(try_dir, False, {
            "title": "Check run, stored patch" if stored else "Live result", "source": "This campaign. fix.py ran now." if not stored else "This campaign. fix.py ran now on a stored patch, with no AI call.",
            "tables": [{"head": "Paired test", "rows": ab_rows(ab, (("seen", "Seen worlds"), ("fresh", "Held-back worlds"), ("controls", "Controls")))}],
            "conclusion": conclusion, "first_verdict": reasons, "first_status": attempt["status"], "caveats": ["Small sample: this used the 12-world campaign and 12 held-back worlds drawn by fix.py, not the worlds marked held back on the grid."],
            "sandbox": {"validation": attempt["validation"] or ["AST check passed"], "limits_hit": ab["fresh"]["limits_hit_B"], "replay_mismatch": ab["fresh"]["replay_mismatch_B"], "held_back_shown_to_ai": overall["held_back_worlds_shown_to_llm"], "note": overall["limits"][1]},
            "changed": [], "limits": overall["limits"][0], "sim_recorded": (self.last_recorded or "unknown")[:8], "sim_now": sim_hash()[:8],
        }, "Accept writes a copy for this session only. controller.py does not change.")
        self.report()

    def offer_recorded(self):
        self.emit(type="card", title="See a recorded fix instead", body="This shows a stored result from an earlier campaign. No AI runs.", actions=[{"label": "Show the recorded result", "action": "fix_recorded"}])
        self.emit(type="card", title="Send it on", body="No fix is ready for review.", actions=[{"label": "Send to a bounty", "action": "bounty", "keep": True}])

    def decide_fix(self, accepted):
        before = sha_file(CONTROLLER)
        self.fix_decision = "accepted" if accepted else "rejected"
        if accepted:
            copy = self.dir / "controller_session_copy.py"
            shutil.copyfile(self.fix_try / "controller.py", copy)
            after = sha_file(CONTROLLER)
            self.tool("fix_accept", "session copy only", [json.dumps({"session_copy_sha256": sha_file(copy)[:12], "real_controller_sha256": after[:12], "real_controller_changed": before != after})])
            self.emit(type="fix_decision", accepted=True, text="Accepted for this session only. policy/highrise/controller.py did not change, and runs here still use it.",
                      code=copy.read_text(), real_sha=after[:12], copy_sha=sha_file(copy)[:12])
        else:
            self.tool("fix_reject", "ok", [json.dumps({"real_controller_sha256": before[:12]})])
            self.emit(type="fix_decision", accepted=False, text="Rejected. Nothing changed.", real_sha=before[:12])
        self.fix_summary = f"{self.fix_summary.rstrip('.')}. You {self.fix_decision} it. policy/highrise/controller.py did not change."
        self.report()

    # Step 9: the bounty. A local ledger with the contract's states. No chain, wallet or key.
    def bounty_job(self, command, request):
        SLOTS.take(1)
        try:
            code, out = watched("bounty", [PYTHON, str(HERE / "bounty_job.py"), command], stdin=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            return json.loads(out) if code == 0 else None
        finally:
            SLOTS.give(1)

    def bounty_draft(self):
        self.chapter("bounty", "Local ledger")
        self.working("reading the gate's rules")
        self.gate_info = self.bounty_job("constants", {})
        preview = self.bounty_job("spec", {"groups": self.proposal["groups"], "salt": "00" * 32, "preview": True})
        if not self.gate_info or not preview:
            self.gate_info = None
            self.say("The gate would not load, so I cannot draft the bounty. It may be mid-edit. Try again.", fail=True)
            return
        unresolved = [{"id": t["id"], "rule": t["rule"], "severity": t["severity"], "count": t["count"]} for t in self.types]
        self.emit(type="bounty_draft", not_tested=self.proposal["not_tested"], unresolved=unresolved, limits=preview["limits"], narrowed=preview["narrowed"], gate=self.gate_info,
                  label=ledger_module.LABEL, min_window=ledger_module.MIN_DISPUTE_WINDOW, defaults={"cap": 1000, "per_failure": 100, "window": ledger_module.MIN_DISPUTE_WINDOW}, tester=self.tester,
                  fix=self.fix_summary)
        self.tool("bounty_draft", ledger_module.LABEL, [json.dumps({"not_tested": len(self.proposal["not_tested"]), "unresolved_failure_types": len(unresolved), "gate_needs": f"{self.gate_info['repeat_need']} of {self.gate_info['reruns']}"})])

    def ledger_event(self):
        self.emit(type="ledger", bounty=self.ledger.bounty, failures=self.ledger.failures, now=time.time(), label=ledger_module.LABEL)

    def fund(self, value):
        amounts = [value.get(k) for k in ("cap", "per_failure", "window")]
        if not all(type(v) is int and 0 < v < 10**12 for v in amounts):
            self.say("The amounts must be whole positive numbers.", fail=True)
            return
        folder = self.dir / "bounty"
        folder.mkdir(exist_ok=True)
        self.bounty_salt = secrets.token_hex(32)
        (folder / "salt.hex").write_text(self.bounty_salt)
        self.spec_path = folder / "spec.json"
        spec = self.bounty_job("spec", {"groups": self.proposal["groups"], "salt": self.bounty_salt, "out": str(self.spec_path)})
        if not spec:
            self.say("The spec did not build.", fail=True)
            return
        ledger = ledger_module.Ledger(folder / "ledger.json")
        try:
            ledger.fund(spec["spec_hash"], amounts[0], amounts[1], amounts[2], COMPANY, RESOLVER, ARBITER)
        except ledger_module.LedgerError as e:
            self.say(f"The ledger refused that: {e}. The contract has the same rule.", fail=True)
            return
        self.ledger = ledger
        self.ledger_event()
        self.tool("fund_bounty", ledger_module.LABEL, [json.dumps({"cap": amounts[0], "per_failure": amounts[1], "dispute_window_s": amounts[2], "spec_hash": spec["spec_hash"][:18]})])

    def submit(self, text, seed):
        """The pasted text goes into a file with a fixed name, and only the gate reads it. It never reaches an argv or a reply."""
        n = len(self.verdicts) + 1
        folder = self.dir / "bounty" / f"submission_{n}"
        folder.mkdir(parents=True)
        (folder / "world.json").write_bytes(text.encode("utf-8", "replace"))
        paid = folder / "paid.json"
        paid.write_text(json.dumps(self.ledger.paid_list()))
        self.emit(type="gate_running", n=n)
        self.working(f"gate.py: up to {self.gate_info['reruns'] + 2} runs")
        t0 = time.time()
        SLOTS.take(2)
        try:
            with open(self.dir / "gate.log", "ab") as log:
                try:
                    code = watched("gate", [PYTHON, str(GATE), "--world", str(folder / "world.json"), "--spec", str(self.spec_path), "--paid", str(paid), "--salt-file", str(self.dir / "bounty" / "salt.hex"),
                                            "--submitter", self.tester, "--seed", seed, "--out", str(folder)], paths=(self.dir / "gate.log",), stdout=log, stderr=subprocess.STDOUT)[0]
                except StageHung:
                    code = "frozen"
        finally:
            SLOTS.give(2)
        found = sorted(folder.glob("*/verdict.json"))
        if code not in (0, 1) or not found:
            self.tool("gate", "failed", [f"gate.py exit {code}. No verdict."])
            self.emit(type="verdict", n=n, accepted=False, code="gate_crashed", reason="The gate stopped with an error, so there is no verdict.", repeat=None, wall=round(time.time() - t0, 1))
            return
        v = json.loads(found[-1].read_text())
        self.verdicts.append(v)
        keep = {k: v.get(k) for k in ("accepted", "code", "reason", "stage", "repeat", "fingerprint", "result_hash", "reference_check", "hardware_check", "not_checked", "human_cap")}
        self.emit(type="verdict", n=n, wall=round(time.time() - t0, 1), runs=len(v.get("runs") or []), **keep)
        self.tool("gate", f"{time.time() - t0:.1f} s", [json.dumps({"accepted": v["accepted"], "code": v["code"], "runs": len(v.get("runs") or [])})])
        if v["accepted"]:
            try:
                self.ledger.propose(self.tester, v["fingerprint"], v["result_hash"])
            except ledger_module.LedgerError as e:
                self.say(f"The local ledger refused the proposal: {e}.", fail=True)
            self.ledger_event()

    def ledger_step(self, name, fingerprint):
        try:
            if name == "ledger_reject":
                self.ledger.reject(fingerprint)
            elif name == "ledger_finalize":
                self.ledger.finalize(fingerprint)
            else:
                self.ledger.claim(fingerprint, self.tester)
        except ledger_module.LedgerError as e:
            self.ledger_event()
            return 409, {"error": str(e)}
        self.ledger_event()
        self.tool(name, ledger_module.LABEL, [json.dumps({"fingerprint": fingerprint[:18], "status": self.ledger.failures[fingerprint]["status"]})])
        return 200, {"ok": True}


SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "crashlab"
    sys_version = ""
    open_streams = 0

    def log_message(self, *_):
        return

    def allowed(self):
        origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
        port = self.server.server_address[1]
        if origin not in APP_ORIGINS:
            return False
        if _STREAM_HOST.match(host) and host.endswith(f".localhost:{port}"):
            return urlsplit(self.path).path.endswith("/events")
        return host in {f"{HOST}:{port}", f"localhost:{port}"}

    def head(self, status, ctype, length=None, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if self.allowed():
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()

    def reply(self, status, obj, extra=()):
        body = json.dumps(obj).encode()
        self.head(status, "application/json", len(body), extra)
        self.wfile.write(body)

    def refuse(self):
        self.close_connection = True
        self.reply(403, {"error": "origin_refused"})

    def session(self, sid):
        if not _SID.match(sid):
            return None
        with SESSIONS_LOCK:
            s = SESSIONS.get(sid)
            if s is None and len(SESSIONS) < MAX_SESSIONS and (RUNS / sid / "session.json").exists():
                try:
                    s = SESSIONS[sid] = Session.load(sid)
                except (ValueError, KeyError, OSError) as e:
                    recovery_log(None, f"session {sid} did not load: {type(e).__name__}", "the page starts a new chat")
            return s

    def do_OPTIONS(self):
        if not self.allowed():
            return self.refuse()
        self.head(204, "text/plain", 0, (("Access-Control-Allow-Methods", "GET, POST"), ("Access-Control-Allow-Headers", "Content-Type"), ("Access-Control-Max-Age", "60")))

    def do_GET(self):
        if not self.allowed():
            return self.refuse()
        parts = urlsplit(self.path).path.strip("/").split("/")
        if parts == ["api", "health"]:
            return self.reply(200, {"ok": True, "sim_sha": sim_hash(), "llm": llm_label(), "max_procs": MAX_PROCS, "llm_session_cap": LLM_LIMIT.session_cap, "pid": os.getpid(), "stream_host": True, "streams": Handler.open_streams})
        if len(parts) >= 4 and parts[:2] == ["api", "sessions"]:
            s = self.session(parts[2])
            if s is None:
                return self.reply(404, {"error": "no_session"})
            if parts[3] == "state" and len(parts) == 4:
                return self.reply(200, {"phase": s.phase, "busy": s.busy})
            if parts[3] == "events" and len(parts) == 4:
                return self.stream(s)
            if parts[3] == "trials" and len(parts) == 6 and _ID.match(parts[4]) and parts[5] in TRIAL_FILES and parts[4] in s.exports:
                data = (s.exports[parts[4]] / parts[5]).read_bytes()
                self.head(200, "application/octet-stream", len(data))
                return self.wfile.write(data)
        self.reply(404, {"error": "not_found"})

    def stream(self, s):
        self.close_connection = True
        self.head(200, "text/event-stream")
        query = parse_qs(urlsplit(self.path).query)
        last = self.headers.get("Last-Event-ID") or query.get("after", [""])[0]
        at = int(last) + 1 if last.isdigit() else 0
        page = "page" in query
        with s.cond:
            at = min(at, len(s.events))
            if page:  # A page has one live stream for its chat. A reload or a copied tab closes the older one, which would hold a connection for nothing.
                s.stream_at += 1
                s.cond.notify_all()
            mine = s.stream_at
            Handler.open_streams += page
        try:
            while True:
                with s.cond:
                    s.cond.wait_for(lambda: len(s.events) > at or (page and s.stream_at != mine), timeout=PING_S)
                    fresh = s.events[at:]
                    replaced = page and s.stream_at != mine
                if replaced:
                    self.wfile.write(b"event: replaced\ndata: 0\n\n")
                    self.wfile.flush()
                    return
                if not fresh:
                    self.wfile.write(b"event: ping\ndata: 0\n\n")
                for event in fresh:
                    self.wfile.write(f"id: {at}\ndata: {json.dumps(event)}\n\n".encode())
                    at += 1
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            with s.cond:
                Handler.open_streams -= page

    def do_POST(self):
        if not self.allowed():
            return self.refuse()
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "json_only"})
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        limit = MAX_SUBMIT_BODY_BYTES if self.path.endswith("/submit") else MAX_BODY_BYTES
        if not 0 <= length <= limit:
            self.close_connection = True
            return self.reply(413, {"error": "too_large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.reply(400, {"error": "not_json"})
        if not isinstance(body, dict):
            return self.reply(400, {"error": "not_an_object"})
        parts = urlsplit(self.path).path.strip("/").split("/")
        if parts == ["api", "sessions"]:
            with SESSIONS_LOCK:
                if len(SESSIONS) >= MAX_SESSIONS:
                    return self.reply(429, {"error": "too_many_sessions"})
                s = Session()
                s.save()
                SESSIONS[s.id] = s
            return self.reply(201, {"id": s.id})
        if len(parts) == 4 and parts[:2] == ["api", "sessions"]:
            s = self.session(parts[2])
            if s is None:
                return self.reply(404, {"error": "no_session"})
            if parts[3] == "message" and isinstance(body.get("text"), str) and body["text"].strip():
                status, out = s.message(body["text"][:MAX_BRIEF_CHARS + 1])
                return self.reply(status, out)
            if parts[3] == "submit" and isinstance(body.get("world"), str) and isinstance(body.get("seed"), str):
                if s.ledger is None:
                    return self.reply(409, {"error": "no_bounty"})
                if not re.fullmatch(r"[0-9]{1,10}", body["seed"]):
                    return self.reply(400, {"error": "bad_seed"})
                status, out = s.start(s.submit, body["world"], body["seed"])
                return self.reply(status, out)
            if parts[3] == "fixed" and body.get("code") in BROWSER_FIXES:
                recovery_log(s, *BROWSER_FIXES[body["code"]])
                return self.reply(200, {"ok": True})
            if parts[3] == "action" and isinstance(body.get("action"), str):
                status, out = s.action(body["action"], body.get("value"))
                return self.reply(status, out)
        self.reply(404, {"error": "not_found"})


def watchdog():
    while True:
        time.sleep(WATCHDOG_POLL_S)
        for s in list(SESSIONS.values()):
            try:
                s.check_workers()
            except Exception as e:
                traceback.print_exc()
                recovery_log(s, f"watchdog raised {type(e).__name__}", "kept watching")


def main():
    global RECORDED, PORT, RESTART_CAUSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--recorded", help="folder of stored LLM replies. For offline checks only, and the status line says so.")
    ap.add_argument("--live-route", action="store_true", help="with --recorded: the AI reads each message live, and the planner still uses stored replies. For timing checks.")
    ap.add_argument("--llm-session-cap", type=int, default=MAX_LLM_PER_SESSION)
    ap.add_argument("--llm-hour-cap", type=int, default=MAX_LLM_PER_HOUR)
    ap.add_argument("--restart-cause", choices=("froze", "crashed"), help="supervise.py sets this, so the chat can say why the server restarted.")
    a = ap.parse_args()
    RESTART_CAUSE = a.restart_cause
    LLM_LIMIT.session_cap, LLM_LIMIT.hour_cap = a.llm_session_cap, a.llm_hour_cap
    RECORDED = str(Path(a.recorded).resolve()) if a.recorded else None
    if a.live_route:
        os.environ["CRASHLAB_LIVE_ROUTE"] = "1"
    RUNS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, a.port), Handler)  # A port in use stops here, before anything below can touch another server's children.
    server.daemon_threads = True
    PORT = a.port
    kill_leftovers()
    threading.Thread(target=watchdog, daemon=True).start()

    def stop(*_):
        with LIVE_LOCK:
            for p in LIVE:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"CrashLab run server (demo shortcut) on http://{HOST}:{a.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
