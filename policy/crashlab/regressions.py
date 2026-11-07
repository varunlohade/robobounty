"""The regression suite: every failed world, per robot, saved and run again on each code change. Results are simulated.

An entry is one world and one seed, deduped by physics hash and seed, with the code sha and verdict that failed. A run with no judge's verdict, such as a crashed child, is not a failure of the robot, so it stays out.
Each suite run uses each entry's own seed and compares with that entry's last result. Fixed needs all of: the same world, the same seed, a different code sha, and a run that no longer fails. A pass from another seed, or on the same code, is never called fixed.
"""
import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import testing_runs as TR

ROOT = Path(__file__).resolve().parent.parent / "runs" / "regressions"
ROOT_ENV = "CRASHLAB_REGRESSIONS_ROOT"  # A check keeps its own suite.
FAILED = ("failed", "stuck")
KEPT_RUNS = 30
KEPT_HISTORY = 12
NOTE = "Same world, same seed, each time. Only a code change that stops the failure counts as fixed."
CHANGES = ("fixed", "still_failing", "new_failure", "still_passing", "passes_same_code", "world_changed", "could_not_run")


def root():
    return Path(os.environ.get(ROOT_ENV) or ROOT)


def _path(pack):
    return root() / f"{pack}.json"


@contextmanager
def _locked(pack):
    root().mkdir(parents=True, exist_ok=True)
    with open(root() / f"{pack}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load(pack):
    try:
        return json.loads(_path(pack).read_text())
    except (OSError, ValueError):
        return {"pack": pack, "entries": [], "runs": []}


def _save(pack, suite):
    tmp = _path(pack).with_suffix(".tmp")
    tmp.write_text(json.dumps(suite))
    tmp.replace(_path(pack))


def key_of(world_hash, seed):
    return f"{world_hash[:16]}-{seed}"


def ingest(pack, failed, code_sha, label, source):
    """failed: rows of world, hash, name, group, seed, outline, t_limit, status, verdict, reason. Returns how many came in new and how many it knew."""
    added, known = 0, 0
    with _locked(pack):
        suite = load(pack)
        entries = {e["id"]: e for e in suite["entries"]}
        now = time.time()
        for row in failed:
            if row["status"] not in FAILED or row["verdict"] in TR.INFRA:
                continue
            key = key_of(row["hash"], row["seed"])
            result = {"status": row["status"], "verdict": row["verdict"], "reason": row.get("reason"), "code_sha": code_sha, "at": now, "run": None}
            if key in entries:
                known += 1
                entries[key]["last"] = result
                continue
            added += 1
            entry = {"id": key, "pack": pack, "name": row["name"], "group": row["group"], "seed": row["seed"], "hash": row["hash"], "world": row["world"], "outline": row["outline"], "t_limit": row["t_limit"], "label": label, "source": source,
                     "first": result, "last": result, "history": []}
            entries[key] = entry
            suite["entries"].append(entry)
        _save(pack, suite)
    return {"added": added, "known": known, "total": len(suite["entries"])}


def ingest_campaign(pack, plan, rows, code_sha, label, source):
    """The failed, not held-back worlds of one campaign."""
    by_index = {r["index"]: r for r in rows}
    failed = []
    for w in plan["worlds"]:
        row = by_index.get(w["index"])
        if row and not w["held_back"]:
            failed.append({**{k: w[k] for k in ("world", "hash", "name", "group", "seed", "outline", "t_limit")}, "status": row["status"], "verdict": row["verdict"], "reason": row["verdict_reason"]})
    return ingest(pack, failed, code_sha, label, source)


def classify(last, now, entry_seed, run_seed, code_sha, same_world):
    """What one re-run means against that entry's last result."""
    if run_seed != entry_seed or now["verdict"] in TR.INFRA:
        return "could_not_run"
    was_failing, failing = last["status"] in FAILED, now["status"] in FAILED
    if was_failing and failing:
        return "still_failing"
    if not was_failing and failing:
        return "new_failure"
    if not was_failing:
        return "still_passing"
    if not same_world:
        return "world_changed"
    return "fixed" if code_sha != last["code_sha"] else "passes_same_code"


CHANGE_WORDS = {"fixed": "Fixed", "still_failing": "Still failing", "new_failure": "New failure", "still_passing": "Still passing", "passes_same_code": "Passes, but the code did not change", "world_changed": "Passes, but the world's physics changed", "could_not_run": "Could not run"}


def run_suite(pack, code_sha, run_many, validate, publish=None, label=None, edited=False):
    """Runs every entry on this code. run_many(jobs, live) gives rows. validate(world) gives the pack's world, hash, outline and t_limit, or raises if that world no longer loads."""
    publish = publish or (lambda state: None)
    suite = load(pack)
    state = {"kind": "regressions", "pack": pack, "running": True, "code_sha": code_sha, "edited": edited, "note": NOTE, "rows": [], "counts": {c: 0 for c in CHANGES}}
    jobs, shown = [], []
    for e in suite["entries"]:
        row = {"id": e["id"], "name": e["name"], "group": e["group"], "seed": e["seed"], "status": "queued", "verdict": None, "was": {k: e["last"][k] for k in ("status", "verdict", "code_sha")}, "change": None}
        state["rows"].append(row)
        try:
            checked = validate(e["world"])
        except RuntimeError:
            row.update(status="failed", verdict="process_crashed", change="could_not_run", reason="This stored world no longer loads.")
            continue
        jobs.append({"world": checked["world"], "seed": e["seed"], "name": e["name"], "group": e["group"], "outline": checked["outline"], "t_limit": checked["t_limit"]})
        shown.append((row, e, checked["hash"] == e["hash"]))
    publish(state)
    if not state["rows"]:
        state.update(running=False, words="The suite is empty. Failed worlds join it when a campaign ends.")
        publish(state)
        return state

    def live(rows):
        for (row, _, _), s in zip(shown, rows):
            row.update(status=s["status"], verdict=s["verdict"])
        publish(state)
    results = run_many(jobs, live) if jobs else []
    with _locked(pack):
        suite = load(pack)
        number = (suite["runs"][-1]["run"] if suite["runs"] else 0) + 1
        by_id = {e["id"]: e for e in suite["entries"]}
        now = time.time()
        for (row, e, same_world), r in zip(shown, results):
            entry = by_id[e["id"]]
            change = classify(entry["last"], r, entry["seed"], r["seed"], code_sha, same_world)
            row.update(status=r["status"], verdict=r["verdict"], reason=r["reason"], change=change, words=CHANGE_WORDS[change])
            if change != "could_not_run":
                entry["last"] = {"status": r["status"], "verdict": r["verdict"], "reason": r["reason"], "code_sha": code_sha, "at": now, "run": number}
            entry["history"] = (entry["history"] + [{"run": number, "status": r["status"], "verdict": r["verdict"], "code_sha": code_sha, "change": change}])[-KEPT_HISTORY:]
        for row in state["rows"]:
            state["counts"][row["change"]] += 1
        state.update(running=False, run=number, at=now)
        suite["runs"] = (suite["runs"] + [{"run": number, "at": now, "code_sha": code_sha, "edited": edited, "label": label, "counts": state["counts"], "worlds": len(state["rows"])}])[-KEPT_RUNS:]
        _save(pack, suite)
    c = state["counts"]
    state["words"] = f"Run {number}, {len(state['rows'])} worlds: {c['fixed']} fixed, {c['still_failing']} still failing, {c['new_failure']} new failures."
    publish(state)
    return state


def public(pack):
    """The suite for a page. The worlds themselves stay on disk."""
    suite = load(pack)
    entries = [{**{k: e[k] for k in ("id", "name", "group", "seed", "first", "last", "history")}, "source": e.get("source")} for e in suite["entries"]]
    return {"pack": pack, "entries": entries, "runs": suite["runs"], "note": NOTE}
