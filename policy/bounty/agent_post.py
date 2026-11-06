"""The agent posts bounties from its budget. Code decides, and no LLM runs here: agent_post.py --session S --campaign C [--pay N] [--root DIR].

Triggers, read from files the lab wrote:
- A fix report under <campaign>/fix5/*/report.json with status did_not_help, rejected or no_change gives a fix_failure for that report's group.
- A not_tested item that names a factor in PHYSICS gives a find_failure, with limits from the campaign's own worlds. Any other item gets "no gate, not posted".
Only a report's status and group, and a factor's words against the table, steer this. Submission text, tester names and source never enter any prompt, because no prompt exists on this path. Payouts stay with the gate and the ledger.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix as X
import board_store as B
import budget

TRIGGER_STATUS = {"did_not_help", "rejected", "no_change"}
COMPANY = "Agent budget"
# A factor counts only if the world gate has real physics for it. The field names belong to gate.py's world, and the second name gives each field's value in the campaign's v5 world.
PHYSICS = (
    (re.compile(r"\b(wind|gust)", re.I), {"steady_wind_ms": ("wind", "steady_ms"), "gust_speed_ms": ("wind", "gust_ms")}),
    (re.compile(r"\b(wet|drizzle)", re.I), {"wetness": ("weather", "wetness")}),
    (re.compile(r"\b(dust)", re.I), {"dust_gm2": ("weather", "dust_gm2")}),
)
NO_GATE = "no gate, not posted"


def fix_triggers(campaign):
    """Each failure group whose AI fix did not help. A report's words stay unread."""
    found = {}
    for path in sorted(Path(campaign).glob("fix5/*/report.json")):
        report = json.loads(path.read_text())
        if report.get("status") in TRIGGER_STATUS and isinstance(report.get("group"), str):
            found.setdefault(report["group"], report["status"])
    return found


def limits_of(plan, fields):
    """Each field spans the campaign's own values, as the company tested them. Fields the gate does not name keep their schema range."""
    limits = {}
    for field, (section, name) in fields.items():
        values = [w["world"][section][name] for w in plan["worlds"]]
        limits[field] = [min(values), max(values)]
    return limits


def post_fix(session, cid, group, status, pay, root, runs):
    what = f"fix_failure {session[:8]}/{cid}/{group}"
    budget.check(pay, what, root)
    view = X.post(session, cid, group, f"Fix {group.replace('_', ' ')}: the AI could not", COMPANY, pay, posted_by="agent", root=root, runs=runs)
    budget.hold(view["id"], pay, what, root)
    return {"kind": "fix_failure", "posted": True, "id": view["id"], "group": group, "trigger": status, "pay": pay}


def post_find(factor, fields, plan, pay, root):
    what = "find_failure"
    budget.check(pay, what, root)
    limits = limits_of(plan, fields)
    view = B.post(f"Find a new failure: {factor[:80]}", COMPANY, [factor[:300]], pay, pay, limits, root=root)
    budget.hold(view["id"], pay, what, root)
    return {"kind": "find_failure", "posted": True, "id": view["id"], "pay": pay, "limits": limits}


def physics_of(factor):
    return next((fields for pattern, fields in PHYSICS if pattern.search(factor)), None)


def run(session, cid, pay, root=B.ROOT, runs=X.SERVER_RUNS):
    """Returns one row for each trigger: posted, or refused with the reason. A refusal is a result and not an error."""
    folder = X._campaign(session, cid, runs)
    plan = json.loads((folder / "scenarios.json").read_text())
    rows = []
    for group, status in fix_triggers(folder).items():
        try:
            rows.append(post_fix(session, cid, group, status, pay, root, runs))
        except B.BoardError as e:
            rows.append({"kind": "fix_failure", "posted": False, "group": group, "trigger": status, "code": e.code, "reason": e.reason})
    for item in plan.get("not_tested", []):
        fields = physics_of(item["factor"])
        if fields is None:
            rows.append({"kind": "find_failure", "posted": False, "factor": item["factor"], "code": "no_gate", "reason": NO_GATE})
            continue
        try:
            rows.append({**post_find(item["factor"], fields, plan, pay, root), "factor": item["factor"]})
        except B.BoardError as e:
            rows.append({"kind": "find_failure", "posted": False, "factor": item["factor"], "code": e.code, "reason": e.reason})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--pay", type=int, default=30)
    ap.add_argument("--root", default=str(B.ROOT))
    a = ap.parse_args()
    print(json.dumps(run(a.session, a.campaign, a.pay, a.root), indent=1))


if __name__ == "__main__":
    main()
