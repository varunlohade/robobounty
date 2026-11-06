"""The code tab's server side: a session copy of the robot's controller, re-runs in the sandbox, and an AI fix on that copy. Results are simulated.

A source file never changes here. Edits live in <session>/code/. fix.py checks each source and runs it under sandbox-exec, so no session copy runs in this process.
Each re-run has its own folder, campaigns/<cid>/code_runs/rN/. code_runs/index.json names the latest result per world, and the first run's files stay as they are.
"""
import dataclasses
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pack_campaign
import pack_job

FIX = pack_job.POLICY / "crashlab" / "fix.py"
PYTHON = pack_job.POLICY / ".venv" / "bin" / "python"
FILES = {
    "window": {"file": pack_job.POLICY / "highrise5" / "controller5.py", "shown": "policy/highrise5/controller5.py",
               "scope": "You can edit the whole controller. The judge and the world stay fixed.", "fix_scope": "The AI can change only this controller, never the judge or the world."},
    "inspection": {"file": pack_job.POLICY / "packs" / "inspection" / "controller.py", "shown": "policy/packs/inspection/controller.py",
                   "scope": "You can edit RouteFollower, its helper and its constants. WalkPolicy runs a fixed ONNX file and stays as it is.", "fix_scope": "The AI can change only the RouteFollower constants. It can fix stuck and off-route runs, not falls, since the walking policy is a fixed ONNX file."},
}
SANDBOX_NOTE = "Your edits stay in this session's copy. The source file does not change. It runs in a sandbox with no network, and writes only to its own run folder."
INSPECTION_SILENT_S = 660  # Above fix.py's 600 s limit: in the sandbox, Warp may compile a kernel before the run's first step, with no progress to show.
T = SimpleNamespace()  # The server's spawn, finish, kill_group, beat, watched, lock, slots, rule and recorded folder. Set once at start.


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def session_file(session):
    return session.dir / "code" / FILES[session.pack]["file"].name


def source_now(session):
    path = session_file(session)
    return (path if path.exists() else FILES[session.pack]["file"]).read_text()


def reply(session):
    f = FILES[session.pack]
    source, original = source_now(session), f["file"].read_text()
    return {"pack": session.pack, "name": f["file"].name, "file": f["shown"], "source": source, "original": original, "sha": sha(source), "original_sha": sha(original), "edited": source != original,
            "scope": f["scope"], "fix_scope": f["fix_scope"], "note": SANDBOX_NOTE, "trace": session.pack == "window"}


def check(pack, source, folder):
    """Reasons a source may not run. The check is fix.py's, in its own process, so the server's imports stay its own."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "checking.py"
    path.write_text(source)
    done = subprocess.run([str(PYTHON), str(FIX), "check5", pack, str(path)], capture_output=True, text=True)
    path.unlink()
    return json.loads(done.stdout)["reasons"]


def save(session, source):
    """Returns (status, reply). A refused source changes nothing."""
    if not isinstance(source, str):
        return 400, {"error": "no_source"}
    reasons = check(session.pack, source, session.dir / "code")
    if reasons:
        return 422, {"error": "refused", "reasons": reasons, "words": "Refused. Nothing ran and nothing was saved."}
    session_file(session).write_text(source)
    return 200, {"ok": True, "sha": sha(source)}


def read_index(folder):
    return pack_campaign.read_json(folder / "code_runs" / "index.json") or {}


def run_folder(folder, index):
    """The folder of one world's latest result."""
    rel = read_index(folder).get(str(index))
    return folder / rel / f"w{index:03d}" if rel else folder / f"w{index:03d}"


def replay_tag(folder, index):
    rel = read_index(folder).get(str(index))
    return f"-{Path(rel).name}" if rel else ""


def code_of_run(session, folder, index):
    """The controller file that produced one world's latest result."""
    f = FILES[session.pack]["file"]
    rel = read_index(folder).get(str(index))
    return folder / rel / f.name if rel else f


def row_from(result):
    row = {"status": "passed" if result["passed"] else "held" if result.get("safe_hold") else "stuck" if result["verdict"] == "stuck" else "failed", "verdict": result["verdict"], "verdict_reason": result["reason"], "film": None, "frames": 0}
    if result.get("end_t") is not None:
        row.update(t=result["end_t"], x=result["end_x"], y=result["end_y"])
    return row


def merged(base, rows, running, elapsed):
    """The whole campaign's grid with these rows replaced. Each changed row keeps what its first run said, so old and new stay side by side."""
    by_index = {r["index"]: r for r in rows}
    out = []
    for row in base["rows"]:
        new = by_index.get(row["index"])
        if new is None:
            out.append(row)
            continue
        first = row.get("first") or {k: row[k] for k in ("status", "verdict", "verdict_reason")}
        out.append({**row, **new, "first": first})
    return {**base, "rows": out, "running": running, "elapsed_s": elapsed, "counts": pack_campaign.count_rows(out)}


def write_grid(folder, grid):
    tmp = folder / "grid.tmp"
    tmp.write_text(json.dumps(grid))
    tmp.replace(folder / "grid.json")


RANK = {"passed": 3, "held": 2, "failed": 1, "stuck": 1}
WORST = {"detach", "tether_load", "fell"}


def rank(row):
    return 0 if row["status"] in ("failed", "stuck") and row.get("verdict") in WORST else RANK.get(row["status"], 1)


def compared(before, after, run):
    """One line per re-run world for the tab: first run, the run before this, this run."""
    rows = []
    for new in after:
        old = before[new["index"]]
        first = old.get("first") or old
        change = "better" if rank(new) > rank(old) else "worse" if rank(new) < rank(old) else "same"
        rows.append({"index": new["index"], "name": new["name"], "change": change, "run": run, "first": {k: first.get(k) for k in ("status", "verdict")}, "old": {k: old.get(k) for k in ("status", "verdict")},
                     "new": {k: new.get(k) for k in ("status", "verdict", "verdict_reason")}})
    return rows


def report_run(session, cid, run, scope, rows, source_sha):
    count = {c: sum(r["change"] == c for r in rows) for c in ("better", "worse", "same")}
    session.emit(type="code_run", campaign=cid, run=run, scope=scope, sha=source_sha, rows=rows, counts=count)
    session.say(f"Run {run}, {len(rows)} worlds: {count['better']} better, {count['worse']} worse, {count['same']} same. Simulated.")


def run_worlds(session, cid, indexes, scope):
    """Re-runs worlds with the session copy, under the same loop as a campaign. Held-back worlds stay out: they are kept to test a fix."""
    folder = session.dir / "campaigns" / cid
    plan = pack_campaign.read_json(folder / "scenarios.json")
    worlds = [w for w in plan["worlds"] if not w["held_back"] and (indexes is None or w["index"] in indexes)]
    name = FILES[session.pack]["file"].name
    runs = folder / "code_runs"
    runs.mkdir(exist_ok=True)
    number = sum(1 for p in runs.glob("r*") if p.is_dir()) + 1
    run = f"r{number}"
    run_dir = runs / run
    run_dir.mkdir()
    snapshot = run_dir / name
    source = source_now(session)
    snapshot.write_text(source)
    base = pack_campaign.read_json(folder / "grid.json")
    before = {r["index"]: dict(r) for r in base["rows"]}
    started = time.monotonic()

    def on_grid(sub):
        grid = merged(base, sub["rows"], sub["running"], round(time.monotonic() - started, 1))
        write_grid(folder, grid)
        session.set_grid(grid)

    def argv_for(world):
        return [str(PYTHON), str(FIX), "sandbox5", session.pack, str(snapshot), str(run_dir / f"w{world['index']:03d}" / "request.json")]

    session.working(f"running {len(worlds)} worlds with your code, in the sandbox")
    limit = pack_job.PACKS[session.pack]["max_procs"]
    while not T.lock.acquire(timeout=1.0):
        T.beat()
    try:
        T.slots.take(T.max_procs)
        rule = dataclasses.replace(T.rule, silent_s=INSPECTION_SILENT_S) if session.pack == "inspection" else T.rule
        campaign = pack_campaign.Campaign(session.pack, cid, {**plan, "worlds": worlds}, run_dir, limit, rule, T.spawn, T.finish, T.kill_group, argv_for=argv_for, on_grid=on_grid, beat=T.beat)
        grid = campaign.run()
    finally:
        T.slots.give(T.max_procs)
        T.lock.release()
    index = read_index(folder)
    for w in worlds:
        index[str(w["index"])] = f"code_runs/{run}"
    (runs / "index.json").write_text(json.dumps(index))
    session.working()
    report_run(session, cid, run, scope, compared(before, grid["rows"], run), sha(source))


def fix_words(pack):
    return FILES[pack]["fix_scope"]


def run_fix(session, cid, group):
    """One AI edit of the session copy for one failure group, proved by fix.py. It offers the diff. It never applies it."""
    folder = session.dir / "campaigns" / cid
    source = source_now(session)
    path = session_file(session)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    number = sum(1 for p in (folder / "fix5").glob("f*")) + 1 if (folder / "fix5").exists() else 1
    fid = f"f{number}"
    out = folder / "fix5" / fid
    out.mkdir(parents=True)
    argv = [str(PYTHON), str(FIX), "run", str(folder), "--base", str(path), "--group", group, "--pack", session.pack, "--out", str(out)]
    stored = pack_job.POLICY / "server" / "fixtures" / f"fix5_{session.pack}.py"
    if T.fix_patch:
        argv += ["--patch", T.fix_patch, "--patch-note", "A stored edit stands in for the AI here, for a check. No AI call ran."]
    elif T.recorded():
        if not stored.exists():
            session.say("This server runs on stored AI replies and has no stored fix for this robot, so no AI fix ran.", fail=True)
            return
        argv += ["--patch", str(stored), "--patch-note", "Stored AI edit, tested now. No AI call ran."]
    elif not session.llm_allowed():
        return
    session.say(f"{fix_words(session.pack)} A fix shows here as a diff, and nothing changes until you accept it.")
    session.working("the AI is editing a copy, then the sandbox tests it on worlds it never saw")
    T.slots.take(T.max_procs)
    try:
        with open(out / "fix.log", "ab") as log:
            code = T.watched("fix", argv, stdout=log, stderr=subprocess.STDOUT)[0]
    finally:
        T.slots.give(T.max_procs)
    session.working()
    report = pack_campaign.read_json(out / "report.json")
    if code != 0 or not report:
        session.say(f"The fix test stopped with an error (exit {code}), so no fix was tested and nothing changed.", fail=True)
        return
    session.tool("code_fix", report["status"], [json.dumps({"group": group, "llm": report["llm"], "sets": report["sets"]})])
    session.emit(type="code_fix", fix=fid, campaign=cid, group=group, **{k: report.get(k) for k in ("status", "words", "diff", "flags", "sets", "pairs", "validation", "limits", "held_back_worlds_shown_to_llm", "proof_wall_s")}, llm_note=(report["llm"] or {}).get("note"), base_sha=report["base_sha256"])


def decide_fix(session, cid, fid, accept):
    """Accept copies the tested file to the session copy and shows its results on the grid. Only a fix that helped can be accepted."""
    folder = session.dir / "campaigns" / cid
    out = folder / "fix5" / fid
    report = pack_campaign.read_json(out / "report.json")
    if not report:
        return 404, {"error": "no_fix"}
    if not accept:
        session.emit(type="code_fix_decided", fix=fid, accepted=False)
        session.say("Rejected. Your code stays as it was.")
        return 200, {"ok": True}
    if report["status"] != "helped":
        return 409, {"error": "not_helped", "words": "This fix did not help, so it cannot be applied."}
    if sha(source_now(session)) != report["base_sha256"]:
        return 409, {"error": "code_changed", "words": "The code changed after this fix was tested, so it no longer fits. Ask again."}
    name = FILES[session.pack]["file"].name
    new_source = (out / name).read_text()
    session_file(session).write_text(new_source)
    base = pack_campaign.read_json(folder / "grid.json")
    before = {r["index"]: dict(r) for r in base["rows"]}
    index = read_index(folder)
    rows = []
    for pair in report["pairs"]:
        if pair["set"] == "held_back":
            continue
        result = pack_campaign.read_json(out / "b" / f"w{pair['index']:03d}" / "job_result.json")
        rows.append({**before[pair["index"]], **row_from(result), "index": pair["index"], "name": pair["name"]})
        index[str(pair["index"])] = f"fix5/{fid}/b"
    (folder / "code_runs").mkdir(exist_ok=True)
    (folder / "code_runs" / "index.json").write_text(json.dumps(index))
    shutil.copyfile(out / name, out / "b" / name)
    grid = merged(base, rows, False, base.get("elapsed_s"))
    write_grid(folder, grid)
    session.set_grid(grid)
    session.emit(type="code_fix_decided", fix=fid, accepted=True)
    session.emit(type="code_changed", sha=sha(new_source))
    report_run(session, cid, fid, "fix", compared(before, rows, fid), sha(new_source))
    return 200, {"ok": True}


def overlay(session, folder, index, detail):
    """A world's detail with its latest code run on top, and what each run said."""
    grid = pack_campaign.read_json(folder / "grid.json")
    row = grid["rows"][index] if grid else {}
    run = run_folder(folder, index)
    frozen_sha = sha(FILES[session.pack]["file"].read_text())
    result = pack_campaign.read_json(run / "job_result.json") or {}
    if read_index(folder).get(str(index)):
        detail.update(numbers=result.get("numbers", {}), events=result.get("events", []), log=pack_campaign.tail(run / "job.log"), code=result.get("code"), wall_s=result.get("wall_s"), label=result.get("label"), note=result.get("note") or detail["note"], replay=bool(result) and (result["verdict"] != "controller_crashed"))
    detail["first"] = row.get("first")
    detail["controller_sha"] = result.get("controller_sha256") or frozen_sha
    traced = pack_campaign.read_json(run / "line_trace.json")
    if traced and traced.get("traced") and detail.get("code"):
        detail["code"] = traced_code(detail["code"], traced)
    return detail


def traced_code(code, traced):
    return {**code, "line": traced["line"], "traced": True, "why": f"This line ran on the step where {traced['rule'].replace('_', ' ')} fired, at {traced['t']:.1f} s, in the {traced['phase']} phase. The re-run had the same hash chain as the record."}


def world_trace(session, cid, index):
    """The window robot's executed line for one finished run. A traced re-run in the sandbox, cached in the run's folder. Anything less stays labelled as active code."""
    folder = session.dir / "campaigns" / cid
    run = run_folder(folder, index)
    if session.pack != "window" or not (run / "run" / "result.json").exists():
        return {"traced": False}
    target = run / "line_trace.json"
    if not target.exists():
        T.watched("trace", [str(PYTHON), str(FIX), "trace5", str(code_of_run(session, folder, index)), str(run / "run"), str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    traced = pack_campaign.read_json(target) or {"traced": False}
    return traced
