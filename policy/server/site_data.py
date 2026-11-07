#!/usr/bin/env python3
"""The website's small server, 127.0.0.1:5297, reached through vite at /site-api.

It reads run files and never changes them: docs/evidence, policy/runs/demo, policy/runs/server, policy/runs/board. Its only writes are accounts and sign-ins, in policy/runs/site.
Start it with: policy/.venv/bin/python policy/server/site_data.py
"""
import gzip
import json
import os
import re
import secrets
import shutil
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crashlab"))
import limits as LIMITS
import pack_job
import regressions as REGRESSIONS
import screener
import site_auth as auth
import site_world as world

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POLICY = REPO / "policy"
EVIDENCE = REPO / "docs" / "evidence"
DEMO = POLICY / "runs" / "demo"
SERVER_RUNS = POLICY / "runs" / "server"
BOARD = POLICY / "runs" / "board"
PORT = 5297
WEB_PORTS = {5199, int(os.environ.get("CRASHLAB_WEB_PORT", 5199))}  # scripts/demo.sh sets the port when vite runs on another one.
ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in WEB_PORTS}
HOSTS = {f"{host}:{port}" for host in ("localhost", "127.0.0.1") for port in WEB_PORTS | {PORT}}
if auth.PUBLIC_ORIGIN:  # Hosted: exactly the public origin, and no localhost name.
    ORIGINS, HOSTS = {auth.PUBLIC_ORIGIN}, {auth.PUBLIC_HOST}
CACHE_S = 30
MAX_BODY = 256 * 1024
MAX_AUTH_BODY = 4096
COOKIE = "crashlab_session"
ENGINEER_REFUSED = {"/site-api/data", "/site-api/recent", "/site-api/regressions"}
SECURE = "; Secure" if os.environ.get("CRASHLAB_HTTPS") == "1" else ""  # Set behind HTTPS. Plain http on localhost cannot carry a Secure cookie everywhere.
ROBOTS = {"window": "Window cleaning", "inspection": "Plant inspection"}
NOTES = {"window": "Hand-built physics, not checked against real hardware.", "inspection": "The policy is upstream's and unchecked against a real robot. Not calibrated."}
NAMES = {"slip_distance": "Slip distance", "detach": "Detach", "false_done": "False done", "time_limit": "Time limit", "stalled": "Stalled", "coverage": "Low coverage",
         "wind_hold": "Wind hold", "battery_stop": "Battery stop", "pass": "Passed", "passed": "Passed", "fell": "Fell", "timed_out": "Timed out", "stuck": "Stuck"}
HOLDS = {"wind_hold", "battery_stop"}
WORLD_DIR = re.compile(r"w[0-9]{3}")
DEMO_TRIAL = re.compile(r"/trials/demo-window-(w[0-9]{3})/([a-z.]+)")
TRIAL_FILES = {"manifest.json", "model.xml", "qpos.json", "result.json", "world.json", "controller.py.txt", "trace.json", "wind.json", "dirt.bin"}


def replay_link(url):
    return None if os.environ.get("CRASHLAB_HOSTED") == "1" else url  # A replay plays in lab.html, which runs on the Mac.


def demo_on():
    return os.environ.get("CRASHLAB_DEMO_ACCOUNTS") == "1"  # Only scripts/demo.sh --recorded sets this, with a throwaway store.


def load_env():
    """The repo's .env, if any. Real environment values win."""
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, eq, value = line.strip().partition("=")
        if eq and not key.startswith("#"):
            os.environ.setdefault(key.removeprefix("export ").strip(), value.strip().strip("\"'"))


def read_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def short(label):
    return label.split(" ")[-1] if label else None


def tally(rows):
    return {"total": len(rows), "passed": sum(r["outcome"] == "pass" for r in rows), "failed": sum(r["outcome"] == "fail" for r in rows), "holds": sum(r["outcome"] == "hold" for r in rows)}


def reading_of(numbers, kind):
    n = numbers or {}
    if kind == "detach" and "min_pressure_pa" in n:
        return f'{n["min_pressure_pa"]:.1f} Pa lowest pressure'
    if kind == "slip_distance" and "slip_m" in n:
        return f'{n["slip_m"]:.2f} m slide'
    if kind == "wind_hold" and "hold_mean_wind_ms" in n:
        return f'held at {n["hold_mean_wind_ms"]:.1f} m/s wind'
    if "coverage" in n:
        return f'{n["coverage"] * 100:.0f}% cleaned'
    if "waypoints_reached" in n:
        return f'{n["waypoints_reached"]} of {n["waypoints"]} waypoints'
    return ""


_starts = {}


def coverage_of(pack, plan, rows):
    """A campaign's coverage of its operating limits. A plan from before limits has no base world, so it reads the pack's start, once. None if that fails: the page leaves the table out."""
    try:
        if not plan.get("base_world") and pack not in _starts:
            _starts[pack] = pack_job.ask(pack, "start", {}, timeout=60)["world"]
        return LIMITS.coverage(pack, plan, rows, base=plan.get("base_world") or _starts[pack])
    except (RuntimeError, OSError, KeyError, ValueError, TypeError) as e:
        print(f"coverage: {pack}: {e}", file=sys.stderr, flush=True)
        return None


def suite_of(pack):
    """This machine's regression suite, or the one stored with the recorded batch, labelled recorded."""
    suite = REGRESSIONS.public(pack)
    if not suite["entries"]:
        stored = json_or(DEMO / pack / "suite.json")
        if stored:
            suite = {**stored, "recorded": True}
    return {"robot": ROBOTS[pack], **suite}


def demo_campaign(pack):
    folder = DEMO / pack
    if not (folder / "timeline.json.gz").exists():
        return None
    plan = read_gz(folder / "scenarios.json.gz")
    last = read_gz(folder / "timeline.json.gz")[-1]
    rows = []
    for w, row in zip(plan["worlds"], last["rows"]):
        if w.get("held_back"):
            continue
        name = f'w{w["index"]:03d}'
        job = json.loads((folder / name / "job_result.json").read_text()) if (folder / name / "job_result.json").exists() else {}
        kind = row.get("verdict") or row["status"]
        outcome = "pass" if row["status"] == "passed" else "hold" if job.get("safe_hold") or kind in HOLDS else "fail"
        code = job.get("code") or {}
        rows.append({"id": name, "group": w["group"], "name": w["name"], "kind": kind, "kind_name": NAMES.get(kind, kind.replace("_", " ").capitalize()), "outcome": outcome,
                     "at": next((e["t"] for e in job.get("events", []) if e.get("name") == kind), None), "reading": reading_of(job.get("numbers"), kind),
                     "line": f'{Path(code["file"]).name}:{code["line"]}' if code.get("file") and code.get("line") else "", "repeat": "not re-run", "flaky": False,
                     "reason": job.get("reason") or row.get("verdict_reason") or "", "changes": w.get("changes", []), "seed": w.get("seed"),
                     "film": f"/site-api/film/{pack}/{name}" if (folder / name / "film.jpg").exists() else None,
                     "replay": replay_link(f"lab.html?trial=demo-window-{name}" if pack == "window" and (folder / name / "export" / "manifest.json.gz").exists() else
                                            f"lab.html?poses=/site-api/replay/inspection/{name}" if pack == "inspection" and (folder / name / "replay.json.gz").exists() else None)})
    return {"id": f"demo-{pack}", "label": f"{ROBOTS[pack]} batch", "robot": ROBOTS[pack], "pack": pack, "sim": short(last.get("label")), "source": f"policy/runs/demo/{pack}", "kind": "rows",
            "note": NOTES[pack], "held_back": plan.get("held_back", 0), "recorded": True, "at": (folder / "timeline.json.gz").stat().st_mtime, "evidence": json_or(folder / "zg_evidence.json"), **tally(rows), "worlds": rows, "coverage": coverage_of(pack, plan, last["rows"])}


def evidence_campaigns():
    results = [json.loads(line) for line in (EVIDENCE / "results.jsonl").read_text().splitlines() if line.strip()]
    diag = json.loads((EVIDENCE / "diagnosis.json").read_text())
    sims = json.loads((EVIDENCE / "sim_of_each_run_set.json").read_text())
    repro = {p["trial"]: p for p in diag["reproduce"]["per_trial"]}
    flaky = {p["trial"] for p in diag["reproduce"]["flaky"]}
    lines = {t["type"]: Path(t["code_line"]).name for t in diag["failure_types"] if t.get("code_line")}
    trials = {}
    for folder in (REPO / "public" / "trials").glob("dubai-final-world-*"):
        trials[f't{int(folder.name.rsplit("-", 1)[1]):04d}'] = folder.name

    def row(r):
        kind = "pass" if r["passed"] else r["outcome"] if r["outcome"] in HOLDS else r["failure"] or r["outcome"]
        rep = repro.get(r["trial"])
        numbers = {k: r.get(k) for k in ("min_pressure_pa", "slip_m", "coverage", "hold_mean_wind_ms")}
        w = r["world"]
        return {"id": r["trial"], "group": r.get("group") or "Control", "name": r["trial"], "kind": kind, "kind_name": NAMES.get(kind, kind), "outcome": "pass" if r["passed"] else "hold" if kind in HOLDS else "fail",
                "at": r.get("first_t"), "reading": reading_of(numbers, kind), "line": lines.get(kind, ""), "repeat": f'{rep["same_failure_runs"]} of {rep["of"]}' if rep else "not re-run", "flaky": r["trial"] in flaky,
                "reason": "", "changes": [], "seed": r.get("seed"), "film": None, "replay": replay_link(f"lab.html?trial={trials[r['trial']]}") if r["trial"] in trials else None,
                "bounds": {"gust": w.get("gust_speed_ms"), "wet": w.get("wetness"), "wind": w.get("steady_wind_ms"), "edge": w.get("edge_margin_m")}}

    final = short(" " + sims["campaign_dubai_final"][0][:12])
    at = (EVIDENCE / "results.jsonl").stat().st_mtime
    out = []
    for kind, cid, label in (("varied", "campaign_dubai_final", "campaign_dubai_final"), ("control", "control_worlds", "Control worlds")):
        rows = [row(r) for r in results if r["kind"] == kind]
        out.append({"id": cid, "label": label, "robot": ROBOTS["window"], "pack": "window", "sim": final, "source": "docs/evidence/results.jsonl", "kind": "rows", "note": NOTES["window"], "held_back": 0, "recorded": True, "at": at, **tally(rows), "worlds": rows})
    fix = json.loads((EVIDENCE / "retest_report.json").read_text())["fresh"]
    sim = short(" " + sims["retest_2026-11-06"][0][:12])
    for side, cid, label in (("A", "retest_baseline", "Fix retest, baseline"), ("B", "retest_patched", "Fix retest, patched")):
        s = fix[side]
        holds = sum(s["holds"].values())
        out.append({"id": cid, "label": label, "robot": ROBOTS["window"], "pack": "window", "sim": sim, "source": "docs/evidence/retest_report.json", "kind": "totals", "note": NOTES["window"], "held_back": 0, "recorded": True, "at": at,
                    "total": s["pass"] + s["fail"] + holds, "passed": s["pass"], "failed": s["fail"], "holds": holds, "worlds": []})
    return out


def session_campaigns():
    """Campaigns this machine's lab server ran. Recorded playbacks and unfinished runs stay out."""
    out = []
    if not SERVER_RUNS.exists():
        return out
    for path in SERVER_RUNS.glob("*/campaigns/*/grid.json"):
        try:
            grid = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if grid.get("running") or grid.get("recorded") or grid.get("pack") not in ROBOTS:
            continue
        c = grid.get("counts", {})
        rows = [r for r in grid.get("rows", []) if not r.get("held_back")]
        ran = c.get("passed", 0) + c.get("failed", 0) + c.get("stuck", 0) + c.get("safe_hold", 0)
        if not ran:
            continue
        job = next(iter(sorted(path.parent.glob("w*/job_result.json"))), None)
        out.append({"id": f"{path.parts[-4][:8]}-{path.parts[-2]}", "label": f"Lab run {path.parts[-4][:8]}", "robot": ROBOTS[grid["pack"]], "pack": grid["pack"], "sim": short((json_or(job) or {}).get("label")) if job else None, "source": f"policy/runs/server/{path.parts[-4]}", "kind": "totals",
                    "note": NOTES[grid["pack"]], "held_back": c.get("held", 0), "recorded": False, "at": path.stat().st_mtime, "evidence": json_or(path.parent / "zg_evidence.json"), "total": ran, "passed": c.get("passed", 0), "failed": c.get("failed", 0) + c.get("stuck", 0), "holds": c.get("safe_hold", 0), "worlds": [],
                    "names": [r.get("name") for r in rows[:3]], "coverage": coverage_of(grid["pack"], json_or(path.parent / "scenarios.json", {}), grid.get("rows", [])) if (path.parent / "scenarios.json").exists() else None})
    out.sort(key=lambda c: c["at"], reverse=True)
    return out[:6]


_cache = {}


def cached(key, build):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    value = build()
    _cache[key] = (time.time(), value)
    return value


def build_data():
    demo = [c for c in (demo_campaign("window"), demo_campaign("inspection")) if c]
    return {"campaigns": demo + evidence_campaigns() + session_campaigns(), "note": "Nothing here is checked against real hardware."}


def types_of(campaign):
    counts = {}
    for row in campaign["worlds"]:
        if row["outcome"] != "pass":
            counts[row["kind_name"]] = counts.get(row["kind_name"], 0) + 1
    return sorted(({"name": k, "count": v} for k, v in counts.items()), key=lambda t: -t["count"])


def open_work():
    """Open decisions, each read from a stored file. An item with no file behind it does not appear."""
    work = []
    diag = json_or(EVIDENCE / "diagnosis.json", {}) or {}
    for t in diag.get("failure_types", []):
        if t.get("type") == "detach":
            full = t.get("stopped_at_full_suction") or [0, 0]
            work.append({"title": f'Decide on detach: {t["count"]} worlds', "body": f"The robot was already at full suction in {full[0]} of {full[1]}. Code line: {Path(t['code_line']).name}.", "tone": "bad", "icon": "alert", "href": "data.html?c=campaign_dubai_final&q=detach", "tag": t["severity"].capitalize()})
    fix = json_or(EVIDENCE / "retest_report.json", {}) or {}
    if fix.get("applied") is False and "fresh" in fix:
        a, b = fix["fresh"]["A"], fix["fresh"]["B"]
        work.append({"title": "Review the suction patch", "body": f'{a["pass"]} passed before, {b["pass"]} passed after, on {fix["fresh"]["n"]} new worlds. Not applied.', "tone": "hold", "icon": "doc", "href": "data.html?c=retest_patched", "tag": "Not applied"})
    people = board_people()
    if people["bounties"]:
        work.append({"title": f'{people["bounties"]} bounties on the board', "body": "", "tone": "quiet", "icon": "target", "href": "bounties.html", "tag": ""})
    path = DEMO / "window" / "scenarios.json.gz"
    if path.exists():
        missing = read_gz(path).get("not_tested") or []
        if missing:
            work.append({"title": f"{len(missing)} factors not tested", "body": "No world function can model them yet: " + ", ".join(m["factor"] for m in missing[:2]) + ".", "tone": "quiet", "icon": "eyeoff", "href": "simulation.html", "tag": ""})
    return work


def recent():
    keep = ("id", "label", "robot", "pack", "sim", "kind", "total", "passed", "failed", "holds", "held_back", "recorded", "at", "source", "note")
    campaigns = build_cached()["campaigns"]
    samples = {}
    for c in campaigns:
        if c["id"].startswith("demo-"):
            worst = next((w for w in c["worlds"] if w["kind"] in ("detach", "fell")), None) or next((w for w in c["worlds"] if w["outcome"] == "fail"), None)
            samples[c["pack"]] = worst
    return {"runs": [{**{k: c.get(k) for k in keep}, "types": types_of(c)[:7]} for c in campaigns], "samples": samples, "work": open_work()}


def build_cached():
    return cached("data", build_data)


def json_or(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def board_people():
    """Names from real board submissions. The check runs keep their own folders, so only the board's own bounties count."""
    testers, authors, bounties = {}, {}, 0
    if BOARD.exists():
        for folder in BOARD.iterdir():
            if not folder.name.isdigit():
                continue
            bounties += 1
            for files, into in ((folder.glob("submissions/*/submission.json"), testers), (folder.glob("submissions/*.json"), testers), (folder.glob("fixes/*/fix.json"), authors)):
                for path in files:
                    try:
                        row = json.loads(path.read_text())
                    except (OSError, ValueError):
                        continue
                    if row.get("tester"):
                        seen = into.setdefault(row["tester"], {"name": row["tester"], "submissions": 0, "states": set()})
                        seen["submissions"] += 1
                        seen["states"].add(row.get("state", "unknown"))
    def plain(people):
        return [{"name": p["name"], "submissions": p["submissions"], "states": sorted(p["states"])} for p in people.values()]
    return {"bounties": bounties, "testers": plain(testers), "authors": plain(authors)}


def providers():
    def by_label(path):
        return short((json_or(path, {}) or {}).get("label"))
    trial = json_or(REPO / "public" / "trials" / "dubai-final-world-016" / "manifest.json", {})
    pkg = json_or(REPO / "package.json", {})
    newton = json_or(POLICY / "newton_lab" / "out" / "results.json", {}) or {}
    demo = {c["pack"]: c for c in build_cached()["campaigns"] if c["id"].startswith("demo-")}
    model = os.environ.get("CRASHLAB_LLM_MODEL", "opus")
    entries = [
        {"id": "mujoco", "kind": "Simulation engines", "name": "MuJoCo", "by": "Open source", "does": "Physics for the window robot", "version": trial.get("python_mujoco"), "status": "In use", "tone": "ok",
         "detail": f"The window runs record in Python MuJoCo {trial.get('python_mujoco')}. The browser replays them with @mujoco/mujoco {pkg.get('dependencies', {}).get('@mujoco/mujoco')}.", "frame": "tower-rain.jpg"},
        {"id": "newton", "kind": "Simulation engines", "name": "Newton", "by": "Open source", "does": "Physics for the inspection robot", "version": short(newton.get("label")), "status": "In use", "tone": "ok",
         "detail": f"The inspection pack runs on Newton. The older walking comparison holds {len(newton.get('worlds', {}))} worlds. {newton.get('note', '')}", "frame": "plant-walk.jpg"},
        {"id": "blender", "kind": "Simulation engines", "name": "Blender", "by": "Open source, renderer", "does": "Re-renders recorded physics", "version": "render only", "status": "Render only", "tone": "quiet",
         "detail": "Blender draws stills and clips from recorded states. It computes no physics and decides no result.", "frame": None},
        {"id": "window", "kind": "Robots and controllers", "name": "High-rise window robot", "by": "Hand-built model", "does": "Scripted Python controller", "version": short(demo.get("window", {}).get("sim") and " " + demo["window"]["sim"]), "status": "In use", "tone": "ok",
         "detail": "A suction climber built in MuJoCo. A scripted Python controller drives it, in policy/highrise5/controller5.py. No AI runs in the robot. Not checked against real hardware.", "frame": "tower-wind.jpg"},
        {"id": "anymal", "kind": "Robots and controllers", "name": "ANYmal C", "by": "Upstream policy, our route follower", "does": "Trained walking policy", "version": short(demo.get("inspection", {}).get("sim") and " " + demo["inspection"]["sim"]), "status": "In use", "tone": "ok",
         "detail": "A trained walking policy from upstream, with our route follower in policy/packs/inspection/controller.py. Unchecked against a real robot. Not calibrated.", "frame": "plant-walk.jpg"},
        {"id": "claude", "kind": "AI models", "name": "Claude", "by": "Through Claude Code, headless", "does": "World edits, scenarios, fix tries", "version": model, "status": "In use", "tone": "ok",
         "detail": f"Headless calls, chosen by CRASHLAB_LLM_MODEL (now {model}). The scenario and route steps pin claude-opus-5-5. The model picks functions, and code checks each one. No model decides a verdict.", "frame": None},
    ]
    state = world.status()
    entries.append({"id": "world", "kind": "Identity", "name": "World ID", "by": "Verified device, not proof of a unique human" if state["credential"] == "device" else "Proof of one human", "does": "Signs people in to this site", "version": state["environment"] or "off", "status": "On, server check" if state["on"] else "Not set up", "tone": "ok" if state["on"] else "quiet",
                    "detail": "The server signs each request and checks each proof." if state["on"] else "This server has no World ID settings yet, so people enter as local guests, shown as not verified.", "frame": None})
    return {"entries": entries, **board_people()}


class Handler(BaseHTTPRequestHandler):
    server_version = "CrashLabSite"
    sys_version = ""

    def log_message(self, *_):
        pass

    def cookies(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return {}
        return {k: v.value for k, v in jar.items()}

    def reply(self, code, body, cookies=()):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value, age in cookies:
            self.send_header("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}{SECURE}")
        self.end_headers()
        self.wfile.write(data)

    def file(self, data, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=60")
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        return self.headers.get("Host", "") in HOSTS

    def do_GET(self):
        if not self.host_ok():
            return self.reply(403, {"error": "host_refused"})
        path = urlsplit(self.path).path
        if (path in ENGINEER_REFUSED or DEMO_TRIAL.fullmatch(path) or path.startswith(("/site-api/film/", "/site-api/replay/"))) and (self.session()[1] or {}).get("role") == "engineer":
            return self.reply(403, {"error": "role_refused", "words": "Engineers work from Bounties."})
        trial = DEMO_TRIAL.fullmatch(path)
        if trial:
            return self.demo_trial(trial[1], trial[2])
        if path == "/site-api/health":
            return self.reply(200, {"ok": True})
        if path == "/site-api/data":
            return self.reply(200, build_cached())
        if path == "/site-api/regressions":
            return self.reply(200, {pack: suite_of(pack) for pack in ROBOTS})
        if path == "/site-api/recent":
            return self.reply(200, recent())
        if path == "/site-api/providers":
            return self.reply(200, providers())
        if path == "/site-api/auth/me":
            return self.me()
        if path == "/site-api/auth/world":
            state = world.status()
            return self.reply(200, {"on": state["on"], "missing": (["hidden"] if state["missing"] else []) if auth.PUBLIC_ORIGIN else state["missing"], "credential": state["credential"], "demo": demo_on(), "password_min": auth.PASSWORD_MIN})
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[1] == "film" and parts[2] in ROBOTS and WORLD_DIR.fullmatch(parts[3]):
            film = DEMO / parts[2] / parts[3] / "film.jpg"
            return self.file(film.read_bytes(), "image/jpeg") if film.exists() else self.reply(404, {"error": "not_found"})
        if len(parts) == 4 and parts[1] == "replay" and parts[2] == "inspection" and WORLD_DIR.fullmatch(parts[3]):
            replay = DEMO / "inspection" / parts[3] / "replay.json.gz"
            return self.file(replay.read_bytes(), "application/octet-stream") if replay.exists() else self.reply(404, {"error": "not_found"})
        self.reply(404, {"error": "not_found"})

    def demo_trial(self, name, filename):
        source = DEMO / "window" / name / "export" / f"{filename}.gz"
        if filename not in TRIAL_FILES or not source.exists():
            return self.reply(404, {"error": "not_found"})
        with gzip.open(source, "rb") as f:
            self.file(f.read(), "application/octet-stream")

    def session(self):
        """The live session of this cookie. A World ID sign-in made in another mode, or with World ID off, counts as signed out, because it does not prove what this server asks for now."""
        token = self.cookies().get(COOKIE)
        s = auth.session_of(token)
        if s and s["verification"] == "demo" and not demo_on():
            return token, None
        if s and s["verification"].startswith("world_"):
            state = world.status()
            if not state["on"] or state["credential"] != s["credential"]:
                return token, None
        return token, s

    def me(self):
        token, s = self.session()
        if not s:
            return self.reply(200, {"signed_in": False, "role": None, "verified": False, "expired": bool(token)}, [(COOKIE, "", 0)] if token else ())
        return self.reply(200, {**auth.public(s), "csrf": auth.csrf_of(token), "verified": s["verification"].startswith("world_"), **({"human_id": s["world_id"], "credential": s["credential"]} if s["verification"].startswith("world_") else {})})

    def ip(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[-1].strip() if forwarded and os.environ.get("CRASHLAB_TRUST_PROXY") == "1" else self.client_address[0]

    def json_body(self, most=MAX_AUTH_BODY, empty_ok=False):
        length = self.headers.get("Content-Length") or "0"
        size = int(length) if length.isascii() and length.isdigit() else -1
        if size == 0 and empty_ok:
            return {}
        if not 0 < size <= most or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise auth.Refused(400, "bad_request", "That request has the wrong shape.")
        try:
            value = json.loads(self.rfile.read(size))
        except ValueError:
            raise auth.Refused(400, "bad_request", "That request has the wrong shape.") from None
        if not isinstance(value, dict):
            raise auth.Refused(400, "bad_request", "That request has the wrong shape.")
        return value

    def signed_in(self, account, role, old, extra=None, cookies=()):
        token = auth.new_session(account, role, old)
        s = auth.session_of(token)
        return self.reply(200, {**auth.public(s), "csrf": auth.csrf_of(token), **(extra or {})}, [(COOKIE, token, auth.SESSION_S), *cookies])

    def do_POST(self):
        if not self.host_ok() or self.headers.get("Origin") not in ORIGINS:
            return self.reply(403, {"error": "origin_refused", "words": "This request did not come from this site."})
        if self.headers.get("X-CrashLab-Request") != "1":  # A cross-site form cannot set this header.
            return self.reply(403, {"error": "csrf_refused", "words": "This request did not come from this site."})
        path = urlsplit(self.path).path
        token, s = self.session()
        try:
            if path in ("/site-api/auth/logout", "/site-api/auth/wallet", "/site-api/auth/board-token", "/site-api/auth/screener/start", "/site-api/auth/screener/grade") and s and not auth.csrf_ok(token, self.headers.get("X-CSRF-Token")):
                return self.reply(403, {"error": "csrf_refused", "words": "This page is out of date. Reload it and try again."})
            if path == "/site-api/auth/logout":
                auth.drop_session(token)
                return self.reply(200, {"ok": True}, [(COOKIE, "", 0)])
            if path == "/site-api/auth/board-token":
                if not s:
                    return self.reply(401, {"error": "sign_in_needed", "words": "Sign in first."})
                return self.reply(200, {"token": auth.board_token(token), "expires_in": auth.BOARD_TOKEN_S})
            if path == "/site-api/auth/wallet":
                if not s or s["role"] != "engineer":
                    return self.reply(403, {"error": "role_refused", "words": "Only an engineer has a payout address."})
                auth.save_payout(s["account_id"], self.json_body().get("address"))
                return self.reply(200, auth.public(auth.session_of(token)))
            if path in ("/site-api/auth/screener/start", "/site-api/auth/screener/grade"):
                if not s or s["role"] != "engineer":
                    return self.reply(403, {"error": "role_refused", "words": "This quiz is for signed-in engineers."})
                if s["screened"]:
                    return self.reply(200, {"screened": True, "passed": True})
                if path.endswith("/start"):
                    return self.reply(200, screener.start(s["account_id"]))
                return self.reply(200, screener.grade(s["account_id"], self.json_body().get("answers")))
            if path == "/site-api/auth/signup":
                v = self.json_body()
                return self.signed_in(auth.sign_up(v.get("email"), v.get("password"), v.get("company"), self.ip()), "company", token)
            if path == "/site-api/auth/signin":
                v = self.json_body()
                return self.signed_in(auth.sign_in(v.get("email"), v.get("password"), self.ip()), "company", token)
            if path == "/site-api/auth/guest":
                auth.limit("guest", self.ip(), auth.IP_GUESTS)
                auth.limit("guest", "all", auth.ALL_GUESTS)
                return self.signed_in(None, "guest", token)
            if path == "/site-api/auth/demo":
                role = self.json_body().get("role")
                if not demo_on() or role not in auth.DEMO:
                    return self.reply(404, {"error": "not_found"})
                auth.limit("demo", self.ip(), auth.IP_GUESTS)
                auth.limit("demo", "all", auth.ALL_GUESTS)
                return self.signed_in(auth.demo_account(role), role, token)
            if path in ("/site-api/auth/world/context", "/site-api/auth/world/verify"):
                return self.world_route(path, token)
        except auth.Refused as r:
            return self.reply(r.status, {"error": r.code, "words": r.words})
        self.reply(404, {"error": "not_found"})

    def world_route(self, path, token):
        jar = self.cookies()
        browser = jar.get("crashlab_browser") or secrets.token_urlsafe(24)
        keep = [("crashlab_browser", browser, 3600)]
        try:
            auth.limit("world", self.ip(), auth.IP_WORLD)
            if path.endswith("/context"):
                return self.reply(200, world.request_context(browser, jar.get("crashlab_world")), keep)
            done = world.verify(self.json_body(MAX_BODY), browser, jar.get("crashlab_world"))
            account = auth.engineer_for_world(done["human_id"], done["credential"])
            saved = [("crashlab_world", done["session_id"], 365 * 86400)] if done["session_id"] else []
            return self.signed_in(account, "engineer", token, {"verified": True, "human_id": done["human_id"], "environment": done["environment"], "credential": done["credential"]}, keep + saved)
        except world.Rejected as r:
            return self.reply(409 if r.code != "not_configured" else 503, {"verified": False, "code": r.code, "words": r.words}, keep)


def main():
    load_env()
    if not shutil.which("node"):
        print("node is needed for World ID signing", file=sys.stderr)
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    if not auth.PUBLIC_ORIGIN:
        HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
