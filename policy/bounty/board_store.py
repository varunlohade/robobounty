"""Bounty board data: one folder per bounty, with spec.json, salt.hex, ledger.json, meta.json and submissions/.

LOCAL LEDGER. NOT ON CHAIN. Amounts are test units, not money. The salt stays on this disk and never leaves through a view.
World ID is not connected: a tester is only a name, so one person can use many names.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server"))
import board_spec
import gate as G
import ledger as ledger_module

ROOT = G.POLICY / "runs" / "board"
LEDGER_LABEL = ledger_module.LABEL
WORLD_ID_LABEL = "World ID is not connected"
SCENARIOS_LABEL = "Scenario text is for people to read. The gate does not enforce it."
SIM_LABEL = "Simulated with hand-built physics. Limits are the company's choice, so a world inside them is not shown to be physically possible."
ROBOT = "High-rise window robot"
MAX_PER_TESTER = 5
MAX_AMOUNT = 10**12
MAX_WINDOW_S = 30 * 24 * 3600
COMPANY, RESOLVER, ARBITER = ("0x" + c * 40 for c in "abc")  # local role names, the same as server.py. No keys exist.
TESTER = re.compile(r"[a-z0-9 ._-]{1,40}")


class BoardError(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code, self.reason = code, reason


@contextlib.contextmanager
def locked(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def write_json(path, value):
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1))
    os.replace(tmp, path)


def _text(value, what, most):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= most:
        raise BoardError("bad_bounty", f"{what} must be text of 1 to {most} characters.")
    return value.strip()


def _amount(value, what, top=MAX_AMOUNT):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= top:
        raise BoardError("bad_bounty", f"{what} must be a whole number from 1 to {top}.")
    return value


def _ledger(folder):
    book = ledger_module.Ledger(folder / "ledger.json")
    saved = json.loads(book.path.read_text())
    book.bounty, book.failures = saved["bounty"], saved["failures"]
    return book


def _folder(bounty_id, root):
    folder = Path(root) / str(bounty_id)
    if not (isinstance(bounty_id, int) and (folder / "spec.json").is_file()):
        raise BoardError("unknown_bounty", "There is no bounty with this id.")
    return folder


def post(title, company, scenarios, cap, per_failure, limits, window=ledger_module.MIN_DISPUTE_WINDOW, root=ROOT):
    """The robot is fixed, so no caller can name one. Returns the public view of the new bounty."""
    title, company = _text(title, "The title", 120), _text(company, "The company", 80)
    if not isinstance(scenarios, list) or len(scenarios) > 10:
        raise BoardError("bad_bounty", "Scenarios must be a list of at most 10 texts.")
    scenarios = [_text(s, "A scenario", 300) for s in scenarios]
    cap, per_failure, window = _amount(cap, "The cap"), _amount(per_failure, "The pay per failure"), _amount(window, "The dispute window", MAX_WINDOW_S)
    root = Path(root)
    with locked(root / ".lock"):
        bounty_id = 1 + max((int(p.name) for p in root.iterdir() if p.name.isdigit()), default=0)
        salt = secrets.token_hex(32)
        try:
            spec, narrowed = board_spec.build(bounty_id, limits, salt)
        except G.Rejected as r:
            raise BoardError(r.code, r.reason) from None
        tmp = root / f".new-{bounty_id}"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "submissions").mkdir(parents=True)
        try:
            write_json(tmp / "spec.json", spec)
            fd = os.open(tmp / "salt.hex", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(salt)
            book = ledger_module.Ledger(tmp / "ledger.json")
            book.fund("0x" + G.sha256_hex(G.canonical(spec)), cap, per_failure, window, COMPANY, RESOLVER, ARBITER)
            book.bounty["id"] = bounty_id  # fund() always writes 1, and the spec holds the real id
            book._save()
            write_json(tmp / "meta.json", {"id": bounty_id, "title": title, "company": company, "robot": ROBOT, "scenarios": scenarios, "narrowed": narrowed, "posted_at": time.time()})
        except ledger_module.LedgerError as e:
            shutil.rmtree(tmp)
            raise BoardError("bad_bounty", f"The ledger refused this bounty: {e}.") from None
        os.rename(tmp, root / str(bounty_id))
    return get(bounty_id, root)


def get(bounty_id, root=ROOT):
    folder = _folder(bounty_id, root)
    with locked(folder / ".lock"):
        book = _ledger(folder)
    meta = json.loads((folder / "meta.json").read_text())
    spec = json.loads((folder / "spec.json").read_text())
    money = book.bounty
    return {**meta, "status": "open" if money["available"] >= money["per_failure"] else "cap_reached", "limits": spec["limits"], "schema_limits": {k: list(v) for k, v in G.W.FIELDS.items()},
            "spec_hash": money["spec_hash"], "cap": money["cap"], "per_failure": money["per_failure"], "available": money["available"], "dispute_window_s": money["dispute_window_s"],
            "unit": "test units", "failures": book.failures, "ledger_label": LEDGER_LABEL, "world_id_label": WORLD_ID_LABEL, "scenarios_label": SCENARIOS_LABEL, "sim_label": SIM_LABEL}


def list_bounties(root=ROOT):
    root = Path(root)
    if not root.is_dir():
        return []
    ids = sorted(int(p.name) for p in root.iterdir() if p.name.isdigit() and (p / "spec.json").is_file())
    return [get(i, root) for i in ids]


def tester_key(name):
    """One form per name, so "Ana" and "ana " share a count."""
    key = " ".join(name.split()).casefold() if isinstance(name, str) else ""
    if not TESTER.fullmatch(key):
        raise BoardError("bad_tester", "A tester name must be 1 to 40 letters, digits, spaces, dots, dashes or underscores.")
    return key


def tester_address(key):
    """A label made from the name, for the gate and the ledger. It is not a wallet and no key exists for it."""
    return "0x" + hashlib.sha256(f"crashlab.board.tester|{key}".encode()).hexdigest()[:40]


def human_id(bounty_id, key):
    return "0x" + hashlib.sha256(f"crashlab.board.human|{bounty_id}|{key}".encode()).hexdigest()


def _rows(folder):
    return [json.loads((p / "submission.json").read_text()) for p in sorted((folder / "submissions").iterdir(), key=lambda p: int(p.name))]


def reserve(bounty_id, tester, seed, root=ROOT):
    """Counts a new submission against the tester's cap, in the same lock, so two requests cannot both take the last place."""
    folder = _folder(bounty_id, root)
    key = tester_key(tester)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise BoardError("bad_seed", "The seed must be a whole number from 0 to 2147483647.")
    with locked(folder / ".lock"):
        rows = _rows(folder)
        used = sum(r["tester"] == key and r["state"] != "interrupted" for r in rows)
        if used >= MAX_PER_TESTER:
            raise BoardError("tester_cap", f"{key} already used {used} of {MAX_PER_TESTER} submissions for this bounty. {WORLD_ID_LABEL}, so this cap counts names and not people.")
        n = 1 + max((r["n"] for r in rows), default=0)
        row = {"n": n, "bounty_id": bounty_id, "tester": key, "seed": seed, "used_before": used, "state": "queued", "submitted_at": time.time(), "result": None, "payout": None}
        (folder / "submissions" / str(n)).mkdir()
        write_json(folder / "submissions" / str(n) / "submission.json", row)
    return row


def save_submission(row, root=ROOT):
    folder = _folder(row["bounty_id"], root)
    write_json(folder / "submissions" / str(row["n"]) / "submission.json", row)


def get_submission(bounty_id, n, root=ROOT):
    path = _folder(bounty_id, root) / "submissions" / str(n) / "submission.json"
    if not path.is_file():
        raise BoardError("unknown_submission", "There is no submission with this number.")
    return json.loads(path.read_text())


def mark_interrupted(root=ROOT):
    """After a restart, nothing runs. Such a row no longer counts against its tester."""
    root = Path(root)
    if not root.is_dir():
        return
    for p in root.iterdir():
        if p.name.isdigit() and (p / "spec.json").is_file():
            for row in _rows(p):
                if row["state"] in ("queued", "running"):
                    save_submission({**row, "state": "interrupted"}, root)


def ledger_of(bounty_id, root=ROOT):
    """For board_gate only. The caller holds the bounty lock."""
    return _ledger(_folder(bounty_id, root))
