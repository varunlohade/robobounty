"""One recorded campaign per robot, played with no AI and no sim: server.py --recorded policy/runs/demo. Results are simulated, and were recorded by record_batch.py from a real campaign on the real server.

A batch folder holds batch.json and one folder per pack: opening.json (the events a new session shows), scenarios.json.gz (the list), timeline.json.gz (the grid about once a second), and w<index>/ for each run that ended (job_result.json, job.log, film.jpg, replay.json.gz or export/*.gz).
A session here starts no child process. The run's files reach the session's campaign folder as each run ends in the timeline, so the normal fetch routes serve them.
"""
import gzip
import json
import shutil
import time
from pathlib import Path

import pack_campaign

MARKER = "batch.json"
LABEL = "Recorded run"
PLAY_S = 40.0  # A long campaign plays faster than it ran.
MAX_STEP_S = 1.0
ENDED = ("passed", "failed", "stuck", "held")
BANNER = "Recorded run. No AI and no sim run here. These are stored results from one earlier simulated campaign. The buttons work, and new words change nothing."
NO_RERUN = "This is a recorded run, so no sim runs here and a re-run cannot start. Start the demo without --recorded to run your edit."
STORED_FIX = "stored_fix.json"
NO_CHAT = "This is a recorded run, so words cannot change the world. Press List test scenarios, then Run."


def is_batch(folder):
    return (Path(folder) / MARKER).exists()


def _read_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def open_session(s, folder):
    for event in json.loads((Path(folder) / s.pack / "opening.json").read_text()):
        s.emit(**event)
    s.say(BANNER)


def no_chat(s):
    s.say(NO_CHAT)


def list_scenarios(s, folder):
    s.emit(type="retire")
    plan = _read_gz(Path(folder) / s.pack / "scenarios.json.gz")
    s.campaign_n += 1
    cid = f"c{s.campaign_n}"
    out = s.dir / "campaigns" / cid
    out.mkdir(parents=True)
    plan["note"] = f"{LABEL}. {plan['note']}"
    (out / "scenarios.json").write_text(json.dumps(plan))
    public = {k: v for k, v in plan.items() if k not in ("llm_reply", "ai_seconds")}
    public["worlds"] = [{k: w[k] for k in ("index", "name", "group", "reason", "held_back", "seed", "changes")} for w in plan["worlds"]]
    s.emit(type="scenarios", campaign=cid, recorded=True, **public)
    s.pending_campaign, s.pending_base = cid, None
    s.say(f"The recorded list has {plan['count']} worlds in {len(plan['groups'])} groups. {plan['to_run']} ran, and {plan['held_back']} stayed held back to test a fix. The reasons are the AI's reasoned guesses, stored with the run.")
    s.emit(type="card", title=f"Play {plan['to_run']} recorded worlds", body=plan["note"], actions=[{"label": f"Play {plan['to_run']} recorded worlds", "action": "run_campaign", "primary": True}])


def _publish(s, out, grid):
    tmp = out / "grid.tmp"
    tmp.write_text(json.dumps(grid))
    tmp.replace(out / "grid.json")
    s.set_grid(grid)


def run_campaign(s, folder):
    cid, s.pending_campaign = s.pending_campaign, None
    source = Path(folder) / s.pack
    out = s.dir / "campaigns" / cid
    plan = pack_campaign.read_json(out / "scenarios.json")
    timeline = _read_gz(source / "timeline.json.gz")
    s.emit(type="retire")
    s.working("playing the recorded runs")
    s.live_campaign = cid
    step = min(MAX_STEP_S, PLAY_S / max(1, len(timeline)))
    copied, filmed = set(), set()
    films = {w["index"]: (pack_campaign.read_json(source / f"w{w['index']:03d}" / "job_result.json") or {}).get("film") for w in plan["worlds"]}
    first = pack_campaign.initial_row
    for moment in timeline:
        rows = [{**first(w), **row} for w, row in zip(plan["worlds"], moment["rows"])]
        for row in rows:
            run = source / f"w{row['index']:03d}"
            # A stored run has its loop from the start, in place of live frames.
            if films[row["index"]] and row["status"] != "queued" and not row["held_back"]:
                if row["index"] not in filmed:
                    (out / run.name).mkdir(exist_ok=True)
                    shutil.copyfile(run / "film.jpg", out / run.name / "film.jpg")
                    filmed.add(row["index"])
                row["film"] = films[row["index"]]
            if row["status"] in ENDED and not row["held_back"] and row["index"] not in copied and run.exists():
                shutil.copytree(run, out / run.name, ignore=shutil.ignore_patterns("export", STORED_FIX), dirs_exist_ok=True)
                _copy_gunzipped(run / "export" / "result.json.gz", out / run.name / "run" / "result.json")
                if (run / "export" / "qpos.json.gz").exists():  # A posted bounty replays these, to show its public failing worlds.
                    fill_run(out, folder, s.pack, row["index"])
                copied.add(row["index"])
        grid = {"type": "grid", "campaign": cid, "pack": s.pack, "running": moment["running"], "elapsed_s": moment["elapsed_s"], "max_procs": moment["max_procs"], "recorded": True, "counts": pack_campaign.count_rows(rows), "rows": rows}
        _publish(s, out, grid)
        time.sleep(step)
    s.live_campaign = None
    s.working()
    counts = grid["counts"]
    s.emit(type="campaign_done", campaign=cid, counts=counts, wall_s=grid["elapsed_s"], max_procs=grid["max_procs"], label=f"{LABEL}, {moment['label']}", note=plan["note"])
    s.say(f"Recorded result, as it ran in {grid['elapsed_s']:.0f} s: {counts['passed']} passed, {counts['failed']} failed, {counts['stuck']} stuck, {counts['safe_hold']} safe holds, {counts['held']} held back. Simulated. {len(plan['not_tested'])} things stay not tested.")


def _copy_gunzipped(source, target):
    """The run's own result file, so a bounty can compare the code that ran with the code frozen now."""
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(source, "rb") as f:
            target.write_bytes(f.read())


def fill_run(out, folder, pack, index):
    """The stored run's files in the shape of a run folder, for the Rerun export."""
    stored = Path(folder) / pack / f"w{index:03d}" / "export"
    run = Path(out) / f"w{index:03d}" / "run"
    run.mkdir(parents=True, exist_ok=True)
    _copy_gunzipped(stored / "result.json.gz", run / "result.json")
    _copy_gunzipped(stored / "world.json.gz", run / "world.json")
    for name in ("qpos.json.gz", "trace.json.gz"):
        shutil.copyfile(stored / name, run / name)


def stored_fix(s, cid, group, folder):
    """The stored result of one real AI fix, from an earlier campaign on these same worlds. No AI call and no sim run. A group with no stored result says so."""
    path = Path(folder) / s.pack / STORED_FIX
    stored = json.loads(path.read_text()) if path.exists() else None
    if not stored or stored["group"] != group:
        s.say(f"This recorded run has no stored AI fix for this failure, so no AI fix shows here.{' It holds one for ' + stored['group'].replace('_', ' ') + '. Open a world with that failure.' if stored else ''}", fail=True)
        return
    s.emit(type="code_fix", fix="f1", campaign=cid, recorded=True, llm_note=f"{LABEL}. {stored['source']} No AI call and no sim ran now.", **{k: stored[k] for k in ("group", "status", "words", "diff", "flags", "sets", "validation", "limits", "held_back_worlds_shown_to_llm", "proof_wall_s")})


def trial(s, cid, index, folder):
    """A window robot's run: its stored export files, unpacked once into the session. The check that replays the run ran when the batch was recorded."""
    tid = f"{cid}-{index:03d}"
    stored = Path(folder) / s.pack / f"w{index:03d}" / "export"
    if not stored.exists():
        return None
    with s.export_lock:
        if tid not in s.exports:
            out = s.dir / "exports" / tid
            out.mkdir(parents=True, exist_ok=True)
            for path in stored.glob("*.gz"):
                with gzip.open(path, "rb") as f:
                    (out / path.name[:-3]).write_bytes(f.read())
            s.exports[tid] = out
            s.save()
    return {"kind": "trial", "tid": tid, "label": f"{LABEL}, world {index}"}
