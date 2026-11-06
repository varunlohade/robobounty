"""The agent's capped budget. budget.json {cap, held, spent, stopped, per_bounty_max, by_bounty, owner} and spend.jsonl, one row per decision. LOCAL. NOT ON CHAIN. Test units only.

Code holds money when a bounty is posted and spends it on a claim. The agent chooses no payout: the gate result and the ledger do.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_store as B

FILE = "budget.json"
LOG = "spend.jsonl"


def _path(root):
    return Path(root) / FILE


def _log(root, **row):
    with open(Path(root) / LOG, "a") as f:
        f.write(json.dumps({"at": time.time(), **row}) + "\n")


def fund(cap, per_bounty_max, root=B.ROOT, owner=None):
    """Sets the company's budget once. A second fund is refused, so a cap cannot grow behind the log. owner is the depositing company's account. With none, no company can stop this budget."""
    cap, per = B._amount(cap, "The budget cap"), B._amount(per_bounty_max, "The per-bounty limit")
    if per > cap:
        raise B.BoardError("bad_budget", "The per-bounty limit cannot be above the cap.")
    Path(root).mkdir(parents=True, exist_ok=True)
    with B.locked(Path(root) / ".budget.lock"):
        if _path(root).is_file():
            raise B.BoardError("budget_exists", "This board already has a budget.")
        B.write_json(_path(root), {"cap": cap, "held": 0, "spent": 0, "stopped": False, "per_bounty_max": per, "by_bounty": {}, "owner": owner})
        _log(root, kind="fund", amount=cap, per_bounty_max=per)
    return view(root)


def view(root=B.ROOT):
    if not _path(root).is_file():
        return {"funded": False, "ledger_label": B.LEDGER_LABEL}
    saved = json.loads(_path(root).read_text())
    saved.pop("owner", None)
    return {"funded": True, **saved, "left": saved["cap"] - saved["held"] - saved["spent"], "unit": "test units", "ledger_label": B.LEDGER_LABEL}


def owner_of(root=B.ROOT):
    """The company account that deposited this budget, or None."""
    return json.loads(_path(root).read_text()).get("owner") if _path(root).is_file() else None


def _refuse(root, code, reason, amount, what):
    _log(root, kind="refused", code=code, amount=amount, what=what)
    raise B.BoardError(code, reason)


def check(amount, what, root=B.ROOT):
    """Refuses before any post work. hold() decides again in its own lock."""
    saved = view(root)
    if not saved["funded"]:
        _refuse(root, "no_budget", "This board has no agent budget.", amount, what)
    if saved["stopped"]:
        _refuse(root, "budget_stopped", "The company pressed stop, so the agent posts nothing.", amount, what)
    if amount > saved["per_bounty_max"]:
        _refuse(root, "over_per_bounty", f"{amount} is above the limit of {saved['per_bounty_max']} per bounty.", amount, what)
    if amount > saved["left"]:
        _refuse(root, "over_budget", f"{amount} is above the {saved['left']} test units left of the cap.", amount, what)


def hold(bounty_id, amount, what, root=B.ROOT):
    with B.locked(Path(root) / ".budget.lock"):
        check(amount, what, root)
        saved = json.loads(_path(root).read_text())
        saved["held"] += amount
        saved["by_bounty"][str(bounty_id)] = {"held": amount, "spent": 0}
        B.write_json(_path(root), saved)
        _log(root, kind="hold", bounty=bounty_id, amount=amount, what=what)


def spend(bounty_id, amount, what, root=B.ROOT):
    with B.locked(Path(root) / ".budget.lock"):
        saved = json.loads(_path(root).read_text())
        row = saved["by_bounty"].get(str(bounty_id))
        if not row or row["held"] < amount:
            raise B.BoardError("budget_mismatch", "This bounty holds less than this amount in the budget.")
        row["held"] -= amount
        row["spent"] += amount
        saved["held"] -= amount
        saved["spent"] += amount
        B.write_json(_path(root), saved)
        _log(root, kind="spend", bounty=bounty_id, amount=amount, what=what)


def stop(root=B.ROOT):
    with B.locked(Path(root) / ".budget.lock"):
        if not _path(root).is_file():
            raise B.BoardError("no_budget", "This board has no agent budget.")
        saved = json.loads(_path(root).read_text())
        saved["stopped"] = True
        B.write_json(_path(root), saved)
        _log(root, kind="stop")
    return view(root)


def adds_up(root=B.ROOT):
    """The log rebuilt from its rows, against budget.json. Returns (ok, rebuilt numbers)."""
    rows = [json.loads(line) for line in (Path(root) / LOG).read_text().splitlines()]
    cap = sum(r["amount"] for r in rows if r["kind"] == "fund")
    spent = sum(r["amount"] for r in rows if r["kind"] == "spend")
    held = sum(r["amount"] for r in rows if r["kind"] == "hold") - spent
    saved = json.loads(_path(root).read_text())
    built = {"cap": cap, "held": held, "spent": spent, "refused": sum(r["kind"] == "refused" for r in rows), "stopped": any(r["kind"] == "stop" for r in rows)}
    return (built["cap"] == saved["cap"] and held == saved["held"] and spent == saved["spent"] and held + spent <= cap and built["stopped"] == saved["stopped"]), built
