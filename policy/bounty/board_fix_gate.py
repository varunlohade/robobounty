"""The solver check. Code decides, and no LLM takes part. Solver source runs only through fix.py, under sandbox-exec.

Pass: every target world passed or safe hold, zero worse in all four sets, zero replay mismatch, zero limits hit, and the fix helps at least half of the held-back worlds that had this failure.
Safety flags send a pass to awaiting_company, and the company approves it. Then the local ledger gets the proposal. Results are simulated.
"""
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix as X
import board_gate
import board_store as B
import gate as G

GATE_TIMEOUT_S = {"window": 1800, "inspection": 3600}  # An inspection world takes two full sim runs: the sandbox's and the one outside it.
PROCS = 6
NOTE = "Engineer's source, tested by the board. No AI call ran."
STORED_PROOF = X.POLICY / "runs" / "demo" / "window" / "stored_proof.json"
RECORDED_WORDS = "Recorded proof: this same source ran on these same worlds with this same code in an earlier real run, and no sim ran now. The stored runs replayed again before any pay. "


def _fail(code, words, stage, **more):
    return {"accepted": False, "code": code, "words": words, "stage": stage, "flags": [], "sets": None, "target": [], **more}


def _result(run_dir, index):
    path = Path(run_dir) / "b" / f"w{index:03d}" / "job_result.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def decide(report, out, patched_sha):
    """Turns one fix.py report into the board's result. Hidden sets leave here as counts only."""
    status = report["status"]
    if status == "no_change":
        return _fail("no_change", "The source is the same as the bounty's controller.", "check")
    if status == "rejected":
        return _fail("refused_source", "The code rules refused this source, so it never ran: " + "; ".join(report["validation"][:4]), "check")
    if status == "cannot_fix":
        return _fail("cannot_fix", report["words"], "check")
    sets = report["sets"]
    counts = {name: {k: sets[name][k] for k in ("n", "better", "worse", "same", "passed_before", "passed_after", "limits_hit", "replay_mismatch", "not_rejudged")} for name in sets}
    rows = [p for p in report["pairs"] if p["set"] == "target"]
    target = []
    for p in rows:
        got = _result(out, p["index"])
        if got.get("controller_sha256") != patched_sha:
            return _fail("forged_result", f"World {p['index']}'s result does not name the source under test.", "sim", sets=counts)
        target.append({"index": p["index"], "name": p["name"], "old": p["old"]["verdict"], "new": p["new"]["verdict"], "passed": p["new"]["passed"], "safe_hold": bool(got.get("safe_hold")), "reason": p["new"]["reason"]})
    held = [p for p in report["pairs"] if p["set"] == "held_back" and p["old"]["verdict"] == report["group"]]
    held_fixed = sum(p["new"]["verdict"] != report["group"] and (p["new"]["passed"] or bool(_result(out, p["index"]).get("safe_hold"))) for p in held)
    base = {"sets": counts, "target": target, "held_back_with_this_failure": len(held), "held_back_fixed": held_fixed, "flags": report["flags"], "proof_wall_s": report.get("proof_wall_s"), "patched_sha256": patched_sha, "diff_sha256": report.get("diff_sha256"), "limits": report["limits"]}
    forged = sum(s["replay_mismatch"] for s in counts.values())
    limits = sum(s["limits_hit"] for s in counts.values())
    worse = sum(s["worse"] for s in counts.values())
    unjudged = sum(s["not_rejudged"] for s in counts.values())
    if forged:
        return {**_fail("replay_mismatch", f"{forged} runs did not replay to their stored result, so the runs do not count.", "sim"), **base, "flags": []}
    if unjudged:
        return {**_fail("not_rejudged", f"{unjudged} runs have no verdict from the judge outside the sandbox, so the board pays nothing.", "sim"), **base, "flags": []}
    if limits:
        return {**_fail("limit_hit", f"{limits} runs hit a time, CPU or memory limit. A kill counts as a fail.", "sim"), **base, "flags": []}
    missed = [t["index"] for t in target if not (t["passed"] or t["safe_hold"])]
    if missed:
        return {**_fail("target_not_fixed", f"{len(missed)} of {len(target)} failing worlds still fail.", "sim"), **base, "flags": []}
    if worse:
        return {**_fail("worse_on_hidden", f"The public worlds pass, but {counts['held_back']['worse'] + counts['passed_before']['worse'] + counts['other_failed']['worse']} other worlds got worse. Their names stay hidden.", "sim"), **base, "flags": []}
    if held and held_fixed * 2 < len(held):
        return {**_fail("overfit", f"The public worlds pass, but only {held_fixed} of {len(held)} held-back worlds with this failure got fixed. The fix does not carry over.", "sim"), **base, "flags": []}
    note = "" if held else " No held-back world had this failure, so they show only that it did no harm there."
    if report["flags"]:
        return {"accepted": False, "code": "awaiting_company", "words": f"It passed, but {len(report['flags'])} changed lines touch a safety check. The company must read them and approve.{note}", "stage": "company", **base}
    return {"accepted": True, "code": "accepted", "words": f"Every failing world now passes or holds safely, and no world got worse.{note}", "stage": "done", **base}


def result_hash_of(row, result, bounty_id, spec_hash):
    body = {"bounty": bounty_id, "spec": spec_hash, "source": row["source_sha256"], "patched": result["patched_sha256"], "code": result["code"], "sets": result["sets"], "target": result["target"]}
    return "0x" + G.sha256_hex(G.canonical(body))


def propose(row, result, folder, root):
    """The only place in the board that creates a payout. It runs only on a result this file computed."""
    bounty_id = row["bounty_id"]
    fingerprint = X.fingerprint_of(bounty_id, result["patched_sha256"])
    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        try:
            book.propose(B.tester_address(row["tester"]), fingerprint, result_hash_of(row, result, bounty_id, book.bounty["spec_hash"]))
            return {**book.failures[fingerprint], "fingerprint": fingerprint, "unit": "test units", "ledger_label": B.LEDGER_LABEL}
        except B.ledger_module.LedgerError as e:
            return {"status": "LedgerRefused", "error": str(e), "ledger_label": B.LEDGER_LABEL}


STALE_WORDS = "A stored run no longer matches or no longer replays on the code here, so this proof says nothing about it. Nothing is held. The company must post again."


def _stale_for_payout(folder, code_root):
    """The last check before any payout: the bounty's own stored runs against the code on disk now. Anything that cannot be read counts as stale."""
    try:
        info = json.loads((folder / "pack.json").read_text())
        hidden = json.loads((folder / "hidden.json").read_text())
        plan = folder / "campaign" / "scenarios.json"
        if hashlib.sha256(plan.read_bytes()).hexdigest() != hidden["plan_sha256"]:
            return True
        return X._is_stale(folder / "campaign", json.loads(plan.read_text())["worlds"], info["pack"], info["controller"]["sha256"], code_root)
    except (OSError, ValueError, KeyError, TypeError):
        return True


def _frozen_problem(info, code_root):
    now = X.frozen_shas(info["pack"], code_root)
    changed = sorted(Path(k).name for k, v in info["frozen"].items() if now.get(k) != v)
    return changed


def proof_key(row, info, hidden):
    """What a stored proof must match exactly: the source, the worlds, the controller and each frozen file."""
    return {"source": row["source_sha256"], "plan": hidden["plan_sha256"], "controller": info["controller"]["sha256"], "group": info["group"], "pack": info["pack"], "frozen": info["frozen"]}


def _stored_proof(row, info, hidden):
    """Only scripts/demo.sh --recorded --arc turns this on, so a film need not wait for the sims. Any difference means a real run."""
    if os.environ.get("CRASHLAB_ARC_DEMO") != "1" or not STORED_PROOF.is_file():
        return None
    stored = json.loads(STORED_PROOF.read_text())
    if stored["key"] != proof_key(row, info, hidden):
        return None
    return {**stored["result"], "recorded": True, "words": RECORDED_WORDS + stored["result"]["words"]}


def _run(row, root, code_root, folder, sub, t0):
    info = json.loads((folder / "pack.json").read_text())
    hidden = json.loads((folder / "hidden.json").read_text())
    changed = _frozen_problem(info, code_root)
    if changed:
        return _fail("judge_changed", f"{', '.join(changed)} changed after this bounty was posted, so the frozen judge is gone and no run counts. The company must post again.", "frozen")
    plan = folder / "campaign" / "scenarios.json"
    if hashlib.sha256(plan.read_bytes()).hexdigest() != hidden["plan_sha256"]:
        return _fail("worlds_changed", "The stored worlds changed after this bounty was posted, so no run counts.", "frozen")
    source = sub / "source.py"
    base = folder / info["controller"]["file"]
    if hashlib.sha256(base.read_bytes()).hexdigest() != info["controller"]["sha256"]:
        return _fail("controller_changed", "The bounty's controller copy changed after it was posted, so no run counts.", "frozen")
    recorded = _stored_proof(row, info, hidden)
    if recorded:
        return recorded
    work = sub / "gate"
    work.mkdir(exist_ok=True)
    py = str(X.PYTHON)
    checked = work / "check.json"
    code = board_gate._process([py, str(X.RUNNER), "check", info["pack"], str(source), str(checked)], sub / "gate.log", 60)
    reasons = json.loads(checked.read_text())["reasons"] if code == 0 else ["The code check stopped with an error."]
    if reasons:
        return _fail("refused_source", "The code rules refused this source, so it never ran: " + "; ".join(reasons[:4]), "check")
    if source.read_bytes() == base.read_bytes():
        return _fail("no_change", "The source is the same as the bounty's controller.", "check")

    # One world first, so an endless loop costs one kill and not a whole campaign of kills.
    first = info["public_worlds"][0]
    world_file = work / "preflight_world.json"
    world_file.write_text(json.dumps({"index": first["index"], "name": first["name"], "world": first["world"], "seed": first["seed"]}))
    controller = work / "preflight_controller.py"
    shutil.copyfile(source, controller)
    reply = work / "preflight.json"
    code = board_gate._process([py, str(X.RUNNER), "preflight", info["pack"], str(controller), str(world_file), str(work / "preflight"), str(reply)], sub / "gate.log", 300)
    if code != 0 or not reply.is_file():
        return _fail("gate_crashed", "The first run stopped with an error in the board, so there is no verdict.", "gate")
    row_one = json.loads(reply.read_text())
    if row_one.get("limit"):
        return _fail("limit_hit", f"The first run hit a limit ({row_one['limit']}), so the sandbox stopped it. A kill counts as a fail.", "sim")

    out = work / "proof"
    code = board_gate._process([py, str(X.RUNNER), "run", str(folder / "campaign"), "--base", str(base), "--group", info["group"], "--pack", info["pack"], "--out", str(out), "--patch", str(source), "--patch-note", NOTE, "--procs", str(PROCS)], sub / "gate.log", GATE_TIMEOUT_S[info["pack"]])
    report_path = out / "report.json"
    if code != 0 or not report_path.is_file():
        return _fail("gate_crashed", "The proof stopped with an error or hit the time limit, so there is no verdict.", "gate")
    changed = _frozen_problem(info, code_root)
    if changed:
        return _fail("judge_changed", f"{', '.join(changed)} changed during the proof, so it does not count.", "frozen")
    report = json.loads(report_path.read_text())
    if report.get("llm", {}).get("from_file") is not True and report["status"] not in ("cannot_fix",):
        return _fail("gate_crashed", "The proof did not test the submitted file.", "gate")
    return decide(report, out, hashlib.sha256(source.read_bytes()).hexdigest())


COULD_NOT_RUN = "The check could not run. The sandbox failed on the unchanged controller too, so this says nothing about your fix. No verdict, no pay, and it did not use one of your submissions. Send it again later."


def _sandbox_works(info, folder):
    first = info["public_worlds"][0]
    return X.F.sandbox_works5(info["pack"], {k: first[k] for k in ("index", "name", "world", "seed")}, folder / "canary")


def _could_not_run(result, sub):
    """A crash can come from the source or from the board. The frozen controller on one world tells them apart. Only a board failure comes here free."""
    if result["code"] != "gate_crashed" and not any(t["new"] == "controller_crashed" for t in result.get("target") or []):
        return None
    info = json.loads((sub.parent.parent / "pack.json").read_text())
    try:
        works = _sandbox_works(info, sub / "gate")
    except (OSError, ValueError, KeyError, TypeError):
        works = False
    return None if works else _fail("could_not_run", COULD_NOT_RUN, "gate")


def run(row, root=B.ROOT, code_root=X.POLICY):
    """Runs one reserved fix. The gate lock keeps one gate at a time, with the world gate too."""
    root = Path(root).resolve()  # the sandbox and fix.py run in other folders
    bounty_id, n = row["bounty_id"], row["n"]
    folder = root / str(bounty_id)
    sub = folder / "fixes" / str(n)
    t0 = time.time()
    with B.locked(root / ".gate.lock"):
        row = {**row, "state": "running", "started_at": t0}
        X.save_fix(row, root)
        try:
            result = _run(row, root, code_root, folder, sub, t0)
        except (OSError, ValueError, KeyError, TypeError) as e:
            result = _fail("gate_crashed", f"The board stopped this fix with an error ({type(e).__name__}), so there is no verdict.", "gate")
        result = _could_not_run(result, sub) or result
        if result["code"] == "accepted" and _stale_for_payout(folder, code_root):
            result = _fail("campaign_stale", STALE_WORDS, "frozen")
        state = "awaiting_company" if result["code"] == "awaiting_company" else X.COULD_NOT_RUN if result["code"] == "could_not_run" else "done"
        payout = propose(row, result, folder, root) if result["code"] == "accepted" else None
        row = {**row, "state": state, "result": result, "payout": payout, "wall_s": round(time.time() - t0, 1)}
        X.save_fix(row, root)
    return row


def company_decide(bounty_id, n, approve, root=B.ROOT, code_root=X.POLICY):
    """The company reads the flagged lines. Approve proposes on the ledger; decline ends the fix. It cannot approve a fix that did not pass, because only awaiting_company rows reach this."""
    folder = X.folder_of(bounty_id, root)
    path = folder / "fixes" / str(n) / "fix.json"
    if not path.is_file():
        raise B.BoardError("unknown_submission", "There is no fix with this number.")
    row = json.loads(path.read_text())
    if row["state"] != "awaiting_company":
        raise B.BoardError("wrong_state", "This fix is not waiting for the company.")
    if approve and _stale_for_payout(folder, code_root):
        row = {**row, "state": "done", "result": _fail("campaign_stale", STALE_WORDS, "frozen")}
    elif approve:
        result = {**row["result"], "accepted": True, "code": "accepted_by_company", "stage": "done", "words": "It passed, and the company read and approved the flagged lines."}
        row = {**row, "state": "done", "result": result, "payout": propose(row, result, folder, root)}
    else:
        row = {**row, "state": "done", "result": {**row["result"], "code": "declined_by_company", "stage": "done", "words": "It passed, but the company declined the flagged lines. Nothing is held."}}
    X.save_fix(row, root)
    return row
