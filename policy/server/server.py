"""CrashLab run server. DEMO SHORTCUT: a local HTTP server that an embedded runtime can replace. It is not a hosted service.

policy/.venv/bin/python policy/server/server.py [--port 5198] [--recorded DIR]

Binds to 127.0.0.1 only, and accepts only the app's own origin and host, on every route. A request with no Origin header is refused too.
Chat text is untrusted. It goes to the LLM layer on stdin, and only validated values come back. It never reaches a shell, an argv or a path.
Jobs start from fixed argv lists. At most MAX_PROCS sim or LLM processes run at once, across all sessions.
"""
import argparse
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger as ledger_module

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
MAX_LLM_PER_SESSION = 10
MAX_LLM_PER_HOUR = 40  # across all sessions
MAX_SUBMIT_BODY_BYTES = 64 * 1024  # the gate applies its own lower limit to the world file
STORED_FIX = POLICY / "runs" / "highrise" / "campaign_dubai_v4" / "fix"
GATE = POLICY / "bounty" / "gate.py"
CONTROLLER = HIGHRISE / "controller.py"
# Local test addresses for the ledger's separate roles. They have no key and no wallet.
COMPANY, RESOLVER, ARBITER = ("0x" + c * 40 for c in "abc")
_FINGERPRINT = re.compile(r"^0x[0-9a-f]{64}$")
TRIAL_FILES = {"manifest.json", "model.xml", "qpos.json", "result.json", "world.json", "controller.py.txt", "trace.json", "wind.json", "dirt.bin"}
_ID = re.compile(r"^[a-z0-9-]{1,40}$")
_SID = re.compile(r"^[0-9a-f]{32}$")
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
REJECTION_WORDS = {
    "brief_too_long": "That is too long for one brief. Keep it under 300 words.",
    "brief_has_control_characters": "That message has control characters, so I did not read it.",
    "brief_empty": "That message is empty.",
    "planner_not_a_scene_request": "That does not describe a robot job I can build.",
    "planner_nothing_buildable": "I found nothing I can build in that. I treated it as text and did not act on it.",
    "planner_unsafe_request": "I will not build that.",
    "plan_failed_validation": "The plan came back with values the validator refused, so nothing changed.",
}


class Slots:
    """A counting gate that takes several slots at once, so a campaign cannot starve behind single jobs forever or exceed the limit."""

    def __init__(self, n):
        self.free, self.cond = n, threading.Condition()

    def take(self, n):
        with self.cond:
            self.cond.wait_for(lambda: self.free >= n)
            self.free -= n

    def give(self, n):
        with self.cond:
            self.free += n
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
    with LIVE_LOCK:
        LIVE.add(p)
    return p


def finish(p):
    with LIVE_LOCK:
        LIVE.discard(p)


def job(script, request, command):
    """Runs plan_job.py in one slot. Returns its JSON reply, or None if it died."""
    SLOTS.take(1)
    try:
        p = spawn([PYTHON, str(script), command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out, _ = p.communicate(json.dumps(request).encode())
        finish(p)
        return json.loads(out) if p.returncode == 0 else None
    finally:
        SLOTS.give(1)


def run_one(argv, stdout_file):
    SLOTS.take(1)
    try:
        with open(stdout_file, "wb") as log:
            p = spawn(argv, stdout=log, stderr=subprocess.STDOUT)
            code = p.wait()
            finish(p)
        return code
    finally:
        SLOTS.give(1)


def llm_label():
    if not RECORDED:
        return "claude headless"
    stored = [n for n in ("brief", "scenarios") if (Path(RECORDED) / f"{n}.json").exists()]
    return f"stored {' and '.join(stored)} reply, check only"


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ab_rows(ab, names):
    """One table row per world set, from fix.py's own counts."""
    rows = []
    for key, label in names:
        b = ab.get(key)
        if b:
            rows.append({"set": label, "n": b["n"], "pass_a": b["A"]["pass"], "pass_b": b["B"]["pass"], "fail_a": b["A"]["fail"], "fail_b": b["B"]["fail"], "better": b["better"], "worse": b["worse"],
                         "same": b["same"], "p": b["sign_test_p_one_sided"], "limits_hit": b["limits_hit_B"], "replay_mismatch": b["replay_mismatch_B"]})
    return rows


def retest_conclusion(r):
    """The three conclusions fixed in retest_2026-11-06/PLAN.md, before the run."""
    required = r["sign_test_pass"] and r["controls_all_pass"] and not r["detach_or_slip_rose"]
    floor = r["blind_point"]["floor"]
    if not required:
        return "did not help"
    if floor["lowest_estimate_pa"] >= floor["guard_pa"]:
        return "helped on the counts but removed the low-pressure guard in the clean phase. Not recommended as it stands."
    return "helped on the counts and kept the guard"


def sim_hash():
    return hashlib.sha256((HIGHRISE / "sim.py").read_bytes()).hexdigest()


def thumb_and_end(run):
    sys.path.insert(0, str(POLICY))
    import app_export
    return app_export.thumb_and_end(run)


class Session:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.dir = RUNS / self.id
        self.dir.mkdir(parents=True)
        self.events, self.cond = [], threading.Condition()
        self.lock = threading.Lock()
        self.busy = False
        self.phase = "brief"
        self.brief = ""
        self.plan, self.answers, self.mapped_fields, self.questions = {}, {}, set(), []
        self.world, self.normal, self.proposal, self.requirements = None, None, None, None
        self.results, self.batches, self.excluded, self.diverged, self.types = {}, 0, {}, [], []
        self.held, self.round = set(), 0
        self.exports = {}
        self.llm_used = 0
        self.last_campaign, self.fix_try, self.fix_summary, self.fix_decision = None, None, None, None
        self.ledger, self.bounty_salt, self.spec_path, self.gate_info, self.verdicts = None, None, None, None, []
        self.last_seconds, self.last_recorded = None, None
        self.tester = "0x" + hashlib.sha256(self.id.encode()).hexdigest()[:40]

    def llm_allowed(self):
        hit = LLM_LIMIT.take(self)
        if hit:
            words = f"This chat used its {LLM_LIMIT.session_cap} AI calls." if hit == "session" else f"The run server reached its limit of {LLM_LIMIT.hour_cap} AI calls an hour."
            self.tool("llm_limit", "refused", [json.dumps({"limit": hit})])
            self.say(f"{words} Nothing was sent to the AI.", fail=True)
        return not hit

    def emit(self, **event):
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def say(self, text, fail=False):
        self.emit(type="text", text=text, fail=fail)

    def tool(self, title, meta, lines, tool_id=None):
        self.emit(type="tool", id=tool_id, title=title, meta=meta, lines=lines)

    def working(self, text=None):
        self.emit(type="working", text=text)

    def chapter(self, name, note=None):
        self.emit(type="chapter", current=name, index=CHAPTERS.index(name), note=note)

    # Requests. Each returns an HTTP status and a small reply.
    def start(self, target, *args):
        with self.lock:
            if self.busy:
                return 409, {"error": "busy"}
            self.busy = True

        def body():
            try:
                target(*args)
            except Exception as e:
                traceback.print_exc()
                self.say(f"Job failed: {type(e).__name__}. See the run server log.", fail=True)
            finally:
                self.working()
                with self.lock:
                    self.busy = False
                self.emit(type="idle")
        threading.Thread(target=body, daemon=True).start()
        return 202, {"ok": True}

    def message(self, text):
        if self.busy:
            return 409, {"error": "busy"}
        self.emit(type="user", text=text)
        said = " ".join(text.lower().strip(" .!").split())
        if self.phase == "review_scene" and said in YES:
            return self.start(self.scene_ok)
        if self.phase == "review_campaign" and said in APPROVE:
            return self.start(self.approve, None)
        return self.start(self.take_brief, text)

    def action(self, name, value):
        if name == "answer" and self.phase == "asking" and type(value) is int:
            return self.start(self.answer, value)
        if name == "scene_ok" and self.phase == "review_scene":
            return self.start(self.scene_ok)
        if name == "approve" and self.phase in ("review_campaign", "done") and (value is None or value == QUICK_WORLDS):
            return self.start(self.approve, value)
        if name == "replay" and type(value) is int and value in self.results:
            threading.Thread(target=self.replay, args=(value,), daemon=True).start()
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

    # Steps 1 to 4: quick questions, build, look, requirements, one normal run.
    def take_brief(self, text):
        self.emit(type="retire")
        joined = f"{self.brief} {text}".strip()
        if len(joined) > MAX_BRIEF_CHARS:
            self.say(REJECTION_WORDS["brief_too_long"], fail=True)
            return
        self.chapter("brief")
        if not self.llm_allowed():
            return
        self.working("reading the brief")
        reply = job(HERE / "plan_job.py", {"text": joined}, "plan")
        if reply is None:
            self.say("The planner process died, so nothing changed.", fail=True)
            return
        if not reply["ok"]:
            code = reply["rejection"]
            self.tool("plan_world", "rejected", [json.dumps({"rejection": code, "llm_s": reply.get("seconds")})])
            self.say(REJECTION_WORDS.get(code, f"The planner could not answer ({code}). Nothing changed."), fail=True)
            return
        self.brief, self.plan = joined, {k: dict(v) for k, v in reply["plan"].items()}
        self.tool("plan_world", f"ok, {reply['seconds']} s", [json.dumps({k: [v["min"], v["max"]] for k, v in self.plan.items()}) if self.plan
                                                               else "The brief sets no value, so defaults stand for now."])
        for item in reply["could_not_build"]:
            self.tool("could_not_build", item["reason"], [item["words"], item["why"]])
        if reply["not_accounted_for"]:
            self.tool("not_used", "words", [" ".join(reply["not_accounted_for"])])
        self.questions = [q for q in QUESTIONS if not set(q["fields"]) & set(self.plan)][:2]
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
        self.questions.pop(0)
        if self.questions:
            self.phase = "asking"
            self.ask()
            return
        self.build()

    def build(self):
        self.phase = "building"
        self.chapter("worlds")
        self.results, self.excluded, self.diverged, self.types, self.held, self.proposal = {}, {}, [], [], set(), None
        self.emit(type="reset_campaign")
        self.working("building the world")
        self.round += 1
        folder = self.dir / f"world_{self.round}"
        reply = job(HERE / "plan_job.py", {"plan": self.plan, "seed": self.round, "out": str(folder)}, "build")
        if not reply or not reply["ok"]:
            code = (reply or {}).get("rejection", "build_process_died")
            self.tool("build_world", "failed", [code])
            self.say(REJECTION_WORDS.get(code, "That world did not build, so nothing changed."), fail=True)
            self.phase = "brief"
            return
        self.world = reply
        short = {k: reply["world"][k] for k in reply["moved"]}
        self.tool("build_world", f"ok, {reply['seconds']} s", [json.dumps(short or {"moved": "nothing, all defaults"}), f"world {reply['hash'][:12]}"])
        self.emit(type="world", world=reply["world"], hash=reply["hash"], xml=reply["xml"], area=reply["area"], moved=reply["moved"], facts=reply["facts"])
        self.tool("inspect_world", "code check", [json.dumps(reply["facts"])])
        self.requirements_step()
        self.normal_run()

    def requirements_step(self):
        folder = self.dir / "requirements"
        code = run_one([PYTHON, str(CRASHLAB / "requirements.py"), str(folder)], self.dir / "requirements.log")
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
        code = run_one([PYTHON, str(HIGHRISE / "run_trial.py"), self.world["path"], "--seed", str(1000 + self.round), "--out", str(run)], self.dir / "normal.log")
        if code != 0:
            self.tool("run_trial", "failed", [f"exit {code}"])
            self.say("The normal run crashed, so I stopped here. Log: normal.log in the session folder.", fail=True)
            self.phase = "brief"
            return
        result = json.loads((run / "result.json").read_text())
        self.normal = result
        self.tool("run_trial", f"{result['wall_s']} s", [json.dumps({"passed": result["passed"], "outcome": result["outcome"], "failure": result["failure"],
                                                                     "coverage": result["coverage"], "min_pressure_pa": result["min_pressure_pa"], "time_s": result["time_s"]})])
        self.emit(type="sim", sha=result["code_sha256"]["sim.py"], now=sim_hash())
        self.working("exporting the replay")
        tid = f"normal-{self.round}"
        if not self.export(run, tid, "Normal run"):
            return
        self.emit(type="trial", tid=tid, label="Normal run", passed=result["passed"], open=True)
        self.phase = "review_scene"
        cleaned = f"It cleaned {result['coverage'] * 100:.1f}%."
        word = f"It passed. {cleaned}" if result["passed"] else f"It failed: {result['failure']}. {cleaned}" if result["failure"] else f"It stopped and held on: {result['outcome']}. {cleaned}"
        self.emit(type="card", title="Does the scene look right?", body=f"{word} Watch the run on the right. Say what to change, or confirm.",
                  actions=[{"label": "Looks right", "action": "scene_ok", "primary": True}])

    def export(self, run, tid, label):
        out = self.dir / "exports" / tid
        code = run_one([PYTHON, str(POLICY / "app_export.py"), "trial", str(run), tid, label, "--out", str(out)], self.dir / "export.log")
        if code != 0:
            self.say("The replay export refused this run. The sim may have changed since it was recorded. Run it again.", fail=True)
            return False
        self.exports[tid] = out
        return True

    def replay(self, index):
        r = self.results[index]
        tid = f"world-{index}"
        self.working(f"exporting {r['name']}")
        t0 = time.time()
        if tid in self.exports or self.export(Path(r["run"]), tid, f"{r['group']}, {r['name']}"):
            self.tool("export_replay", f"{time.time() - t0:.1f} s", [json.dumps({"world": r["name"], "failure": r["failure"]})])
            self.emit(type="trial", tid=tid, label=r["name"], passed=r["passed"], open=True)
            if not r["passed"] and self.types:
                self.chapter("find")
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
                p = spawn(argv, stdout=log, stderr=subprocess.STDOUT)
                seen = 0
                while True:
                    code = p.poll()
                    seen = self.read_results(out, chosen, seen, rows, started)
                    if code is not None:
                        break
                    time.sleep(0.25)
                finish(p)
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
            for argv in ([str(HIGHRISE / "linetrace.py"), str(out)], [str(CRASHLAB / "diagnose.py"), str(out), "--reproduce"]):
                with open(self.dir / "diagnose.log", "ab") as log:
                    p = spawn([PYTHON, *argv, "--procs", str(MAX_PROCS)], stdout=log, stderr=subprocess.STDOUT)
                    code = p.wait()
                    finish(p)
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
        retest = json.loads((STORED_FIX / "retest_2026-11-06" / "report.json").read_text())
        overall = json.loads((STORED_FIX / "report.json").read_text())
        attempt = json.loads((STORED_FIX / "try_2" / "report.json").read_text())
        conclusion = retest_conclusion(retest)
        floor = retest["blind_point"]["floor"]
        changed = [{"world": w["trial"], "before": w["A_failure"] or w["A"], "after": w["B_failure"] or w["B"]} for w in retest["per_world"] if (w["A_failure"] or w["A"]) != (w["B_failure"] or w["B"])]
        fresh = retest["fresh"]
        self.fix_summary = (f"Recorded result: {fresh['better']} better, {fresh['worse']} worse on {retest['fresh_worlds']} held-back worlds. Conclusion: {conclusion}")
        self.tool("fix_report", "Recorded result", [json.dumps({"better": fresh["better"], "worse": fresh["worse"], "p": fresh["sign_test_p_one_sided"], "controls": f"{retest['controls']['B']['pass']}/{retest['controls']['n']}"})])
        self.offer_fix(STORED_FIX / "try_2", True, {
            "title": "Recorded result", "source": "campaign_dubai_v4, try 2, then the larger test written down in retest_2026-11-06/PLAN.md before it ran. No AI call was made now.",
            "tables": [{"head": "Larger test, new held-back worlds", "rows": ab_rows(retest, (("fresh", "Held-back worlds"), ("controls", "Controls")))},
                       {"head": "First test of the same patch", "rows": ab_rows(attempt["ab"], (("seen", "Seen worlds"), ("fresh", "Held-back worlds"), ("controls", "Controls")))}],
            "failing_base": retest["baseline_failing_worlds"], "conclusion": conclusion,
            "first_verdict": attempt["verdict"]["reasons"], "first_status": overall["status"],
            "caveats": [f"The patch raises clean-phase suction to {floor['suction_clean']}. At that speed the lowest pressure estimate is {floor['lowest_estimate_pa']} Pa, and the guard fires only under {floor['guard_pa']} Pa. So the low-pressure guard can no longer fire in the clean phase.",
                        *overall["notes"]],
            "sandbox": {"validation": attempt["validation"] or ["AST check passed"], "limits_hit": fresh["limits_hit_B"], "replay_mismatch": fresh["replay_mismatch_B"], "held_back_shown_to_ai": overall["held_back_worlds_shown_to_llm"],
                        "note": overall["limits"][1]},
            "changed": changed, "limits": overall["limits"][0], "sim_recorded": "0e36d3bf", "sim_now": sim_hash()[:8],
        }, "Recorded result. Accept writes a copy for this session only. controller.py does not change.")
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
                p = spawn(argv, stdout=log, stderr=subprocess.STDOUT)
                code = p.wait()
                finish(p)
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
        self.fix_summary = f"{self.fix_summary} You {self.fix_decision} it. policy/highrise/controller.py did not change."
        self.report()

    # Step 9: the bounty. A local ledger with the contract's states. No chain, wallet or key.
    def bounty_job(self, command, request):
        SLOTS.take(1)
        try:
            p = spawn([PYTHON, str(HERE / "bounty_job.py"), command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            out, _ = p.communicate(json.dumps(request).encode())
            finish(p)
            return json.loads(out) if p.returncode == 0 else None
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
                p = spawn([PYTHON, str(GATE), "--world", str(folder / "world.json"), "--spec", str(self.spec_path), "--paid", str(paid), "--salt-file", str(self.dir / "bounty" / "salt.hex"),
                           "--submitter", self.tester, "--seed", seed, "--out", str(folder)], stdout=log, stderr=subprocess.STDOUT)
                code = p.wait()
                finish(p)
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

    def log_message(self, *_):
        return

    def allowed(self):
        origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
        port = self.server.server_address[1]
        return origin in APP_ORIGINS and host in {f"{HOST}:{port}", f"localhost:{port}"}

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
        return SESSIONS.get(sid) if _SID.match(sid) else None

    def do_OPTIONS(self):
        if not self.allowed():
            return self.refuse()
        self.head(204, "text/plain", 0, (("Access-Control-Allow-Methods", "GET, POST"), ("Access-Control-Allow-Headers", "Content-Type"), ("Access-Control-Max-Age", "60")))

    def do_GET(self):
        if not self.allowed():
            return self.refuse()
        parts = urlsplit(self.path).path.strip("/").split("/")
        if parts == ["api", "health"]:
            return self.reply(200, {"ok": True, "sim_sha": sim_hash(), "llm": llm_label(), "max_procs": MAX_PROCS, "llm_session_cap": LLM_LIMIT.session_cap})
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
        last = self.headers.get("Last-Event-ID", "")
        at = int(last) + 1 if last.isdigit() else 0
        try:
            while True:
                with s.cond:
                    s.cond.wait_for(lambda: len(s.events) > at, timeout=15)
                    fresh = s.events[at:]
                if not fresh:
                    self.wfile.write(b": keep-alive\n\n")
                for event in fresh:
                    self.wfile.write(f"id: {at}\ndata: {json.dumps(event)}\n\n".encode())
                    at += 1
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

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
            if parts[3] == "action" and isinstance(body.get("action"), str):
                status, out = s.action(body["action"], body.get("value"))
                return self.reply(status, out)
        self.reply(404, {"error": "not_found"})


def main():
    global RECORDED
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--recorded", help="folder of stored LLM replies. For offline checks only, and the status line says so.")
    ap.add_argument("--llm-session-cap", type=int, default=MAX_LLM_PER_SESSION)
    ap.add_argument("--llm-hour-cap", type=int, default=MAX_LLM_PER_HOUR)
    a = ap.parse_args()
    LLM_LIMIT.session_cap, LLM_LIMIT.hour_cap = a.llm_session_cap, a.llm_hour_cap
    RECORDED = str(Path(a.recorded).resolve()) if a.recorded else None
    RUNS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, a.port), Handler)
    server.daemon_threads = True

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
