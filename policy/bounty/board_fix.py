"""Fix bounties: a company posts a failure group from a real campaign, and an engineer submits a controller change.

Folder policy/runs/board/<id>/: pack.json (public), hidden.json 0600, campaign/ 0700, ledger.json, fixes/<n>/.
hidden.json and campaign/ hold the held-back and passed-before worlds. No route serves them: routes read pack.json through view() and fix rows through fix_view().
LOCAL LEDGER. NOT ON CHAIN. Amounts are test units. Results are simulated. World ID is not connected, so a tester is only a name.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "crashlab"))
import board_store as B
import fix as F
import gate as G

POLICY = HERE.parent
SERVER_RUNS = POLICY / "runs" / "server"
PYTHON = POLICY / ".venv" / "bin" / "python"
RUNNER = HERE / "board_fix_run.py"
SCHEMA = "crashlab.board.fix.v1"
MAX_PUBLIC_REPLAYS = 6
SESSION = re.compile(r"[0-9a-f]{32}")
CAMPAIGN = re.compile(r"c[0-9]{1,6}")
GROUP = re.compile(r"[a-z_]{1,40}")
SIM_LABEL = "Simulated with hand-built physics. Not checked against real hardware. A pass says nothing about a real robot."
SANDBOX_LABEL = "sandbox-exec shares the kernel with this machine. It is one layer, not a VM."
FROZEN_FILES = {
    "window": ["highrise5/judge5.py", "highrise5/sim5.py", "highrise5/compile5.py", "highrise5/engine5.py", "highrise5/parts5.py", "highrise5/geoms5.py", "highrise5/scene5.py", "highrise5/world5.py", "highrise5/run_trial5.py"],
    "inspection": ["packs/inspection/judge.py", "packs/inspection/sim.py", "packs/inspection/world.py", "packs/inspection/model.py", "packs/inspection/plant.py"],
}
ROBOT_NAME = {"window": "Window cleaning robot", "inspection": "Inspection robot"}
SCOPE = {"window": "You can edit the whole of controller5.py under the code rules. The judge and the worlds stay frozen.",
         "inspection": "You can change only the six RouteFollower number constants. This robot has no replay re-judge, so a controller's reported result is not re-checked."}


def frozen_shas(pack, code_root=POLICY):
    return {name: hashlib.sha256((Path(code_root) / name).read_bytes()).hexdigest() for name in FROZEN_FILES[pack]}


def _read(path):
    return json.loads(Path(path).read_text())


def _campaign(session, cid, runs):
    if not (isinstance(session, str) and SESSION.fullmatch(session) and isinstance(cid, str) and CAMPAIGN.fullmatch(cid)):
        raise B.BoardError("bad_campaign", "The session or campaign name is not valid.")
    folder = Path(runs) / session / "campaigns" / cid
    if not (folder / "grid.json").is_file() or not (folder / "scenarios.json").is_file():
        raise B.BoardError("unknown_campaign", "There is no such finished campaign.")
    return folder


def _fixable_groups(pack, rows):
    groups = {}
    for r in rows:
        v = r.get("verdict")
        if r["held_back"] or r["status"] not in ("failed", "stuck") or not v or v in F.NOT_A_CONTROLLER_FAILURE or (pack == "inspection" and v in F.INSPECTION_CANNOT):
            continue
        groups[v] = groups.get(v, 0) + 1
    return groups


def fixable(root=B.ROOT, runs=SERVER_RUNS):
    """What can be posted: each failure group of each finished campaign. Names and counts only."""
    posted = {tuple(_hidden(p.parent)["source"]) for p in Path(root).glob("*/pack.json")} if Path(root).is_dir() else set()
    out = []
    for grid_path in Path(runs).glob("*/campaigns/*/grid.json"):
        folder = grid_path.parent
        try:
            grid = _read(grid_path)
        except (OSError, ValueError):
            continue
        if grid.get("running") or grid.get("pack") not in FROZEN_FILES or not (folder / "scenarios.json").is_file():
            continue
        session, cid = folder.parent.parent.name, folder.name
        for group, count in _fixable_groups(grid["pack"], grid["rows"]).items():
            out.append({"session": session, "cid": cid, "group": group, "pack": grid["pack"], "robot": ROBOT_NAME[grid["pack"]], "failed": count, "at": grid_path.stat().st_mtime,
                        "worlds": len(grid["rows"]), "posted": (session, cid, group) in posted, "ref": f"{session}/{cid}/{group}"})
    return sorted(out, key=lambda r: (-r["at"], r["session"], r["group"]))


def _hidden(folder):
    return _read(folder / "hidden.json")


def _is_stale(folder, target, pack):
    """A stored run from other judge or sim code says nothing about the code frozen now."""
    if pack != "window":
        return False
    now = frozen_shas(pack)
    for w in target:
        result = Path(F.latest_run5(folder, w["index"])) / "run" / "result.json"
        if not result.is_file():
            return True
        code = _read(result)["code_sha256"]
        if any(code[Path(name).name] != sha for name, sha in now.items() if Path(name).name in code):
            return True
    return False


def _public_world(world, row, result):
    return {"index": world["index"], "name": world["name"], "scenario": world["group"], "changes": world["changes"], "seed": world["seed"], "world": world["world"],
            "verdict": row["verdict"], "status": row["status"], "reason": row["verdict_reason"], "numbers": result.get("numbers", {}), "events": result.get("events", [])}


def _export_public(pack, campaign, index, out):
    """The recorded run of one public world, for the engineer. export5 refuses a run that no longer replays."""
    run = F.latest_run5(campaign, index) / "run"
    if pack != "window" or not run.is_dir():
        return False
    done = subprocess.run([str(F.PY), str(F.HIGHRISE5 / "export5.py"), str(run), f"w{index}", f"World {index}", "--out", str(out)], capture_output=True, timeout=120)
    return done.returncode == 0


def post(session, cid, group, title, company, pay, window=B.ledger_module.MIN_DISPUTE_WINDOW, posted_by="company", root=B.ROOT, runs=SERVER_RUNS):
    """Makes one fix bounty from one failure group. cap = pay, so one fix can win. Returns the public view."""
    title, company = B._text(title, "The title", 120), B._text(company, "The company", 80)
    pay, window = B._amount(pay, "The pay"), B._amount(window, "The dispute window", B.MAX_WINDOW_S)
    if not (isinstance(group, str) and GROUP.fullmatch(group)):
        raise B.BoardError("bad_group", "The failure group is not valid.")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = _campaign(session, cid, runs)
    grid, plan = _read(source / "grid.json"), _read(source / "scenarios.json")
    pack = grid["pack"]
    if grid.get("running") or pack not in FROZEN_FILES:
        raise B.BoardError("bad_campaign", "This campaign is still running, or its robot has no fix bounty.")
    if group not in _fixable_groups(pack, grid["rows"]):
        raise B.BoardError("not_fixable", "This campaign has no world with this failure that a controller change could fix.")
    rows = {r["index"]: r for r in grid["rows"]}
    target = [w for w in plan["worlds"] if not w["held_back"] and rows[w["index"]]["verdict"] == group and rows[w["index"]]["status"] in ("failed", "stuck")]
    held_back = [w for w in plan["worlds"] if w["held_back"]]
    passed = [w for w in plan["worlds"] if not w["held_back"] and rows[w["index"]]["status"] in ("passed", "held")]
    other = [w for w in plan["worlds"] if not w["held_back"] and w not in target and w not in passed]
    if not held_back:
        raise B.BoardError("no_hidden_worlds", "This campaign has no held-back worlds, so a fix could not be proved on worlds it never saw.")
    if _is_stale(source, target, pack):
        raise B.BoardError("campaign_stale", "The sim or judge changed after this campaign ran. Run the campaign again before you post it.")
    session_copy = source.parent.parent / "code" / F.PACK5[pack]["file"].name
    base = session_copy if session_copy.is_file() else F.PACK5[pack]["file"]
    base_text = base.read_text()

    with B.locked(root / ".lock"):
        for p in root.glob("*/hidden.json"):
            if _hidden(p.parent)["source"] == [session, cid, group]:
                raise B.BoardError("already_posted", f"Bounty {p.parent.name} already holds this failure group.")
        bounty_id = 1 + max((int(p.name) for p in root.iterdir() if p.name.isdigit()), default=0)
        tmp = root / f".newfix-{bounty_id}"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "fixes").mkdir(parents=True)
        try:
            campaign = tmp / "campaign"
            campaign.mkdir(mode=0o700)
            shutil.copyfile(source / "scenarios.json", campaign / "scenarios.json")
            shutil.copyfile(source / "grid.json", campaign / "grid.json")
            for w in plan["worlds"]:
                stored = F.latest_run5(source, w["index"]) / "job_result.json"
                if not w["held_back"] and stored.is_file():
                    (campaign / f"w{w['index']:03d}").mkdir()
                    shutil.copyfile(stored, campaign / f"w{w['index']:03d}" / "job_result.json")
            (tmp / F.PACK5[pack]["file"].name).write_text(base_text)
            public = []
            for n, w in enumerate(target):
                stored = F.latest_run5(source, w["index"]) / "job_result.json"
                entry = _public_world(w, rows[w["index"]], _read(stored) if stored.is_file() else {})
                entry["replay"] = n < MAX_PUBLIC_REPLAYS and _export_public(pack, source, w["index"], tmp / "public" / f"w{w['index']:03d}")
                public.append(entry)
            hidden = {"held_back": held_back, "passed_before": passed, "other_failed": other, "plan_sha256": hashlib.sha256((source / "scenarios.json").read_bytes()).hexdigest(), "source": [session, cid, group]}
            fd = os.open(tmp / "hidden.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(hidden, f)
            info = {"schema": SCHEMA, "kind": "fix_failure", "id": bounty_id, "title": title, "company": company, "pack": pack, "robot": ROBOT_NAME[pack], "group": group, "posted_by": posted_by, "posted_at": time.time(),
                    "controller": {"file": base.name, "sha256": hashlib.sha256(base_text.encode()).hexdigest()}, "frozen": frozen_shas(pack), "public_worlds": public,
                    "hidden_counts": {"held_back": len(held_back), "passed_before": len(passed), "other_failed": len(other)}, "pay": pay, "cap": pay, "window_s": window, "scope": SCOPE[pack], "replay_rejudge": pack == "window"}
            B.write_json(tmp / "pack.json", info)
            spec_hash = "0x" + G.sha256_hex(G.canonical(info))
            book = B.ledger_module.Ledger(tmp / "ledger.json")
            book.fund(spec_hash, pay, pay, window, B.COMPANY, B.RESOLVER, B.ARBITER)
            saved = _read(book.path)
            saved["bounty"]["id"] = bounty_id
            B.write_json(book.path, saved)
        except B.ledger_module.LedgerError as e:
            shutil.rmtree(tmp)
            raise B.BoardError("bad_bounty", f"The ledger refused this bounty: {e}.") from None
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        os.rename(tmp, root / str(bounty_id))
    return view(bounty_id, root)


def folder_of(bounty_id, root=B.ROOT):
    folder = Path(root) / str(bounty_id)
    if not (isinstance(bounty_id, int) and (folder / "pack.json").is_file()):
        raise B.BoardError("unknown_bounty", "There is no fix bounty with this id.")
    return folder


def is_fix(bounty_id, root=B.ROOT):
    return (Path(root) / str(bounty_id) / "pack.json").is_file()


def _rows(folder):
    return [_read(p / "fix.json") for p in sorted((folder / "fixes").iterdir(), key=lambda p: int(p.name))]


def view(bounty_id, root=B.ROOT):
    """The only form of a fix bounty that leaves this machine's disk. It holds no hidden world."""
    folder = folder_of(bounty_id, root)
    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        rows = _rows(folder)
    info = _read(folder / "pack.json")
    money = book.bounty
    won = next((f for f in book.failures.values() if f["status"] != "Rejected"), None)
    return {**info, "status": won["status"].lower() if won else "open", "spec_hash": money["spec_hash"], "per_failure": money["per_failure"], "available": money["available"], "dispute_window_s": money["dispute_window_s"],
            "unit": "test units", "failures": book.failures, "balance": B._balance(money, book.failures, [r for r in rows if r.get("payout")]), "submissions": len(rows), "checking": sum(r["state"] in ("queued", "running", "awaiting_company") for r in rows), "now": time.time(),
            "ledger_label": B.LEDGER_LABEL, "world_id_label": B.WORLD_ID_LABEL, "sim_label": SIM_LABEL, "sandbox_label": SANDBOX_LABEL, "chain_mirror": _mirror_of(folder)}


def _mirror_of(folder):
    path = folder / "chain_mirror.json"
    if not path.is_file():
        return None
    saved = _read(path)
    return {k: saved[k] for k in ("label", "chain_id", "txs", "fingerprint", "balances_after_claim")}


def list_views(root=B.ROOT):
    root = Path(root)
    if not root.is_dir():
        return []
    return [view(i, root) for i in sorted(int(p.name) for p in root.iterdir() if p.name.isdigit() and (p / "pack.json").is_file())]


FIX_KEYS = ("n", "bounty_id", "tester", "source_sha256", "state", "submitted_at", "result", "payout", "wall_s", "used_before")


def fix_view(row):
    return {k: row.get(k) for k in FIX_KEYS}


def list_fixes(bounty_id, root=B.ROOT):
    return [fix_view(r) for r in _rows(folder_of(bounty_id, root))]


def get_fix(bounty_id, n, root=B.ROOT):
    path = folder_of(bounty_id, root) / "fixes" / str(n) / "fix.json"
    if not path.is_file():
        raise B.BoardError("unknown_submission", "There is no fix with this number.")
    return {**fix_view(_read(path)), "now": time.time()}


def save_fix(row, root=B.ROOT):
    B.write_json(folder_of(row["bounty_id"], root) / "fixes" / str(row["n"]) / "fix.json", row)


def reserve(bounty_id, tester, source, root=B.ROOT):
    """Counts one submission in the bounty's lock, so two requests cannot both take the last place. The source stays on disk at 0600 and is never served."""
    folder = folder_of(bounty_id, root)
    key = B.tester_key(tester)
    if not isinstance(source, str) or not source.strip():
        raise B.BoardError("bad_source", "The source must be the text of one Python file.")
    data = source.encode("utf-8", "replace")
    if len(data) > F.MAX_SOURCE_BYTES:
        raise B.BoardError("source_too_large", f"The source is larger than {F.MAX_SOURCE_BYTES} bytes.")
    sha = hashlib.sha256(data).hexdigest()
    with B.locked(folder / ".lock"):
        rows = _rows(folder)
        book = B._ledger(folder)
        if book.bounty["available"] < book.bounty["per_failure"]:
            raise B.BoardError("cap_reached", "A fix already holds this bounty's pay. If it gets rejected, the bounty opens again.")
        used = sum(r["tester"] == key and r["state"] != "interrupted" for r in rows)
        if used >= B.MAX_PER_TESTER:
            raise B.BoardError("tester_cap", f"{key} already used {used} of {B.MAX_PER_TESTER} submissions for this bounty. {B.WORLD_ID_LABEL}, so this cap counts names and not people.")
        if any(r["source_sha256"] == sha and r["state"] != "interrupted" for r in rows):
            raise B.BoardError("same_source", "This exact source was already submitted to this bounty, so it gets no new run.")
        n = 1 + max((r["n"] for r in rows), default=0)
        row = {"n": n, "bounty_id": bounty_id, "tester": key, "source_sha256": sha, "state": "queued", "submitted_at": time.time(), "result": None, "payout": None, "used_before": used}
        (folder / "fixes" / str(n)).mkdir()
        fd = os.open(folder / "fixes" / str(n) / "source.py", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        save_fix(row, root)
    return row


def _settle_budget(info, amount, root, what):
    """A claim on an agent-posted bounty moves the budget's hold to spent. Only this code path does."""
    if info.get("posted_by") == "agent":
        import budget
        budget.spend(info["id"], amount, what, root)


def ledger_step(bounty_id, n, step, tester=None, root=B.ROOT):
    """One step on the local ledger, with the contract's rules. No account exists, so anyone who can reach the board can press these. Claim checks only the name."""
    folder = folder_of(bounty_id, root)
    caller = B.tester_address(B.tester_key(tester)) if step == "claim" else None
    with B.locked(folder / ".lock"):
        path = folder / "fixes" / str(n) / "fix.json"
        if not path.is_file():
            raise B.BoardError("unknown_submission", "There is no fix with this number.")
        row = _read(path)
        fingerprint = (row.get("payout") or {}).get("fingerprint")
        if not fingerprint:
            raise B.BoardError("ledger_refused", "This fix holds nothing on the ledger.")
        book = B._ledger(folder)
        try:
            {"reject": book.reject, "finalize": book.finalize}[step](fingerprint) if step != "claim" else book.claim(fingerprint, caller)
        except B.ledger_module.LedgerError as e:
            raise B.BoardError("ledger_refused", f"The ledger refused this: {e}.") from None
        entry = book.failures[fingerprint]
        row["payout"] = {**row["payout"], **entry}
        save_fix(row, root)
    if step == "claim":
        _settle_budget(_read(folder / "pack.json"), entry["amount"], root, f"claim of fix {n}")
    return row


def fingerprint_of(bounty_id, patched_sha):
    """The local ledger's key. The chain mirror uses keccak256(bountyId, patched sha). Both keep one payout per fix."""
    return "0x" + hashlib.sha256(f"crashlab.board.fix|{bounty_id}|{patched_sha}".encode()).hexdigest()
