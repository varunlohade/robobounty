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
        if name == "bounty" and self.proposal:
            self.chapter("bounty", "Stub: nothing was sent")
            self.say("Bounty stub. Nothing was sent and no contract ran. This button is not connected yet.")
            return 200, {"ok": True}
        return 409, {"error": "not_now"}

    # Steps 1 to 4: quick questions, build, look, requirements, one normal run.
    def take_brief(self, text):
        self.emit(type="retire")
        joined = f"{self.brief} {text}".strip()
        if len(joined) > MAX_BRIEF_CHARS:
            self.say(REJECTION_WORDS["brief_too_long"], fail=True)
            return
        self.chapter("brief")
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
            ranges = ", ".join(f"{k} {v['min']}-{v['max']}" for k, v in g["ranges"].items())
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
            {"head": "World count", "lines": [f"{reply['total_worlds']} worlds: {to_run} to run, {len(self.held)} held back to check a fix.", reply["count_reason"]]},
            {"head": "Expected compute", "lines": [estimate, "Cloud spend: none, it runs here.", f"LLM spend: unknown, capped at {LLM_CAP_USD} USD a call by llm.py."]},
            {"head": "Included in this model", "lines": [", ".join(sorted({k for g in reply["groups"] for k in g["ranges"]}))]},
            {"head": "Outside this model", "lines": [", ".join(t["factor"] for t in reply["not_tested"]) or "none listed"]},
        ], actions=actions)

    # Steps 6, 7 and 10: the pipeline, failure groups, excluded runs and the report.
    def pipeline(self, now, **notes):
        at = STAGES.index(now)
        off = {"fixing": "not connected", "validating": "not run"}
        self.emit(type="pipeline", stages=[{"name": s, "state": "off" if s in off and (i <= at or now == s) else "done" if i < at else "now" if i == at else "todo",
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
        plan = {"worlds": [{"file": str(Path("..") / worlds[i]["file"]), "group": worlds[i]["group"]} for i in chosen]}
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
        self.report(time.time() - started, recorded)
        self.phase = "done"
        self.chapter("find", None if self.types else "No failure type found")
        waiting = [i for i in range(len(worlds)) if i not in self.held and i not in self.results]
        if waiting:
            self.emit(type="card", title=f"{len(waiting)} worlds not run yet", body="You approved part of the campaign.",
                      actions=[{"label": f"Run the other {len(waiting)}", "action": "approve"}])
        if self.proposal["not_tested"]:
            self.emit(type="card", title="Not tested", body="No physics for these here, so they get no pass.", items=[t["factor"] for t in self.proposal["not_tested"]],
                      actions=[{"label": "Send to a bounty", "action": "bounty", "keep": True}], note="Stub, not connected yet")

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
            if row["kind"] != "varied":
                continue
            index = chosen[int(row["trial"][1:])]
            run = out / row["trial"]
            drawn = thumb_and_end(run)
            result = {k: row[k] for k in ("passed", "failure", "fired", "coverage", "time_s", "min_pressure_pa", "seed", "wall_s", "outcome", "group", "slip_m", "peak_tether_n")}
            result.update(index=index, name=Path(self.proposal["worlds"][index]["file"]).stem, thumb=drawn["thumb"], end=drawn["end"], run=str(run))
            self.results[index] = result
            if not rows[-1].get("sim_sha"):
                rows[-1]["sim_sha"] = json.loads((run / "result.json").read_text())["code_sha256"]["sim.py"]
            self.emit(type="result", **{k: v for k, v in result.items() if k != "run"})
            done = [r for r in self.results.values() if r["index"] in chosen]
            self.tool("run_trials", f"{time.time() - started:.0f} s", [json.dumps({"n": len(chosen), "done": len(done), "failed": sum(self.counts_as_failed(r) for r in done)})], tool_id=f"trials-{self.batches}")
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
                      actions=[{"label": "Send to a bounty", "action": "bounty", "keep": True}], note="Stub, not connected yet")

    def report(self, seconds, recorded):
        run = len(self.results)
        real = sum(t["count"] for t in self.types)
        holds = sum(not r["passed"] and r["failure"] is None for r in self.results.values())
        numbers = [{"n": run, "label": "worlds run"}, {"n": len(self.types), "label": "failure types"}, {"n": real, "label": "worlds failed"},
                   {"n": len(self.excluded), "label": "flaky, excluded"}, {"n": len(self.held), "label": "held back"},
                   {"n": len(self.proposal["not_tested"]), "label": "not tested"}, {"n": 0, "label": "fixes validated (not connected)"}]
        self.emit(type="report", numbers=numbers, seconds=round(seconds, 1), safe_holds=holds, diverged=len(self.diverged),
                  fixes="Fix and validation are not connected in this build, so no fix ran and no held-back world ran. Before and after: none yet.", sim_recorded=recorded)


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
            return self.reply(200, {"ok": True, "sim_sha": sim_hash(), "llm": "recorded replies, check only" if RECORDED else "claude headless", "max_procs": MAX_PROCS})
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
        if not 0 <= length <= MAX_BODY_BYTES:
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
            if parts[3] == "action" and isinstance(body.get("action"), str):
                status, out = s.action(body["action"], body.get("value"))
                return self.reply(status, out)
        self.reply(404, {"error": "not_found"})


def main():
    global RECORDED
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5198)
    ap.add_argument("--recorded", help="folder of stored LLM replies. For offline checks only, and the status line says so.")
    a = ap.parse_args()
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
