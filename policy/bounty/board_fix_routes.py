"""The fix bounty routes, mounted by board_server.py after its origin and host check. Every reply comes from a public view, so no route reads hidden.json or campaign/.

GET  /api/bounties                         both kinds, each with its kind
GET  /api/bounties/<id>                    a fix bounty's public view
GET  /api/bounties/<id>/source             the controller copy engineers start from
GET  /api/bounties/<id>/fixes[/<n>]
GET  /api/bounties/<id>/public/<world>/<file>   a recorded run of one public failing world
GET  /api/fixable
GET  /api/fixable/check/<session>/<campaign>   counts of the stale check. A company session.
GET  /api/budget
POST /api/fixable/check                    {session, campaign, group}. A company session. Begins the stale check in the background.
POST /api/bounties/fix                     {session, campaign, group, title, pay, window?}. A company session; the company name comes from it.
POST /api/bounties/<id>/fix                {source}. An engineer session; the tester id comes from it. The server sets every other field. Any other field is refused. The reply holds claim_secret, once.
POST /api/bounties/<id>/fixes/<n>/approve|decline|reject|finalize   {}
POST /api/bounties/<id>/fixes/<n>/claim    {secret}. An engineer session.
POST /api/budget/stop                      {}. The company that deposited the budget.
"""
import os
import queue
import re
import threading
from pathlib import Path

import arc_wallet
import board_fix as X
import board_fix_gate
import board_store as B
import budget
import site_auth as A

QUEUE_CAP = 4
MAX_SOURCE_BODY = 3 * X.F.MAX_SOURCE_BYTES
MAX_POST_BODY = 4096
MAX_STEP_BODY = 256
POST_FIELDS = {"session", "campaign", "group", "title", "pay"}
CHECK_FIELDS = {"session", "campaign", "group"}
FIX_FIELDS = {"source"}
ERROR_STATUS = {"unknown_campaign": 404, "already_posted": 409, "campaign_published": 409, "not_fixable": 409, "campaign_stale": 409, "no_hidden_worlds": 409, "cap_reached": 409, "same_source": 409, "source_too_large": 413, "wrong_state": 409, "queue_full": 503,
                "bad_secret": 403, "on_chain": 409, "not_funded": 409, "no_wallet": 409, "budget_stopped": 409, "over_budget": 409, "over_per_bounty": 409, "no_budget": 404, "not_your_budget": 403, "not_found": 404, "budget_mismatch": 409}
PUBLIC_FILES = {"manifest.json": "application/json", "model.xml": "application/xml", "qpos.json": "application/json", "result.json": "application/json", "world.json": "application/json",
                "controller.py.txt": "text/plain", "trace.json": "application/json", "wind.json": "application/json", "dirt.bin": "application/octet-stream"}
ONE = re.compile(r"/api/bounties/([0-9]{1,9})")
SOURCE = re.compile(r"/api/bounties/([0-9]{1,9})/source")
FIXES = re.compile(r"/api/bounties/([0-9]{1,9})/fixes(?:/([0-9]{1,9}))?")
PUBLIC = re.compile(r"/api/bounties/([0-9]{1,9})/public/([0-9]{1,4})/([a-z.]+)")
SUBMIT = re.compile(r"/api/bounties/([0-9]{1,9})/fix")
STEP = re.compile(r"/api/bounties/([0-9]{1,9})/fixes/([0-9]{1,9})/(approve|decline|reject|finalize|claim)")
CHECK = re.compile(r"/api/fixable/check/([0-9a-f]{32})/(c[0-9]{1,6})")
FIND_CLAIM = re.compile(r"/api/bounties/([0-9]{1,9})/failures/(0x[0-9a-f]{64})/claim")

WAITING = queue.Queue(QUEUE_CAP)
SUBMIT_LOCK = threading.Lock()


def _worker(root):
    while True:
        row = WAITING.get()
        try:
            board_fix_gate.run(row, root)
        except Exception as e:  # noqa: BLE001 One bad run must not stop the queue. Its row says so.
            X.save_fix({**row, "state": "done", "result": board_fix_gate._fail("gate_crashed", f"The board stopped this fix with an error ({type(e).__name__}), so there is no verdict.", "gate")}, root)


def start(root):
    root = Path(root)
    for p in root.glob("*/pack.json"):
        for row in X._rows(p.parent):
            if row["state"] in ("queued", "running"):
                X.save_fix({**row, "state": "interrupted"}, root)
    threading.Thread(target=_worker, args=(root,), daemon=True).start()
    recorded = os.environ.get("CRASHLAB_DEMO_ACCOUNTS") == "1"  # scripts/demo.sh sets this only with --recorded.
    threading.Thread(target=X.watch_campaigns, args=(arc_wallet.DEMO_SESSION, "c1") if recorded else (), daemon=True).start()


def _both(root):
    return sorted([{**b, "kind": "find_failure"} for b in B.list_bounties(root)] + X.list_views(root), key=lambda b: -b["id"])


def route(h, method, root):
    """Returns True when this file answered. board_server's own handlers catch BoardError and its body refusals."""
    return _get(h, root) if method == "GET" else _post(h, root)


def _get(h, root):
    labels = {"ledger_label": B.LEDGER_LABEL, "world_id_label": B.WORLD_ID_LABEL}
    path = h.path
    if path == "/api/bounties":
        h.reply(200, {"bounties": [h.marked(b) for b in _both(root)], **labels})
    elif path == "/api/fixable":
        h.reply(200, {"fixable": X.fixable(root), **labels})
    elif m := CHECK.fullmatch(path):
        h.need("company")
        h.reply(200, X.check_view(m[1], m[2]))
    elif path == "/api/budget":
        h.reply(200, budget.view(root))
    elif (m := ONE.fullmatch(path)) and X.is_fix(int(m[1]), root):
        h.reply(200, h.marked(X.view(int(m[1]), root)))
    elif (m := SOURCE.fullmatch(path)) and X.is_fix(int(m[1]), root):
        folder = X.folder_of(int(m[1]), root)
        info = X._read(folder / "pack.json")
        h.reply(200, {"file": info["controller"]["file"], "sha256": info["controller"]["sha256"], "source": (folder / info["controller"]["file"]).read_text(), "scope": info["scope"]})
    elif (m := FIXES.fullmatch(path)) and X.is_fix(int(m[1]), root):
        h.reply(200, {**X.get_fix(int(m[1]), int(m[2]), root), **labels} if m[2] else {"fixes": X.list_fixes(int(m[1]), root), **labels})
    elif m := PUBLIC.fullmatch(path):
        info = X._read(X.folder_of(int(m[1]), root) / "pack.json")
        index, name = int(m[2]), m[3]
        file = Path(root) / m[1] / "public" / f"w{index:03d}" / name
        if name not in PUBLIC_FILES or index not in {w["index"] for w in info["public_worlds"]} or not file.is_file():
            raise B.BoardError("not_found", "There is no such public file.")
        data = file.read_bytes()
        h.head(200, PUBLIC_FILES[name], len(data))
        h.end_headers()
        h.wfile.write(data)
    else:
        return False
    return True


def _post(h, root):
    path = h.path
    if path == "/api/bounties/fix":
        s = h.need("company")
        v = h.body(MAX_POST_BODY, POST_FIELDS, ("window",))
        B.require_post_room(s["account_id"], root)
        extra = {"window": v["window"]} if "window" in v else {}
        made = X.post(v["session"], v["campaign"], v["group"], v["title"], A.company_name(s), v["pay"], root=root, **extra)
        B.set_owner(made["id"], s["account_id"], root)
        h.reply(201, {**made, "mine": True})
    elif path == "/api/fixable/check":
        h.need("company")
        v = h.body(MAX_POST_BODY, CHECK_FIELDS)
        h.reply(202, X.start_check(v["session"], v["campaign"], v["group"]))
    elif path == "/api/budget/stop":
        s = h.need("company")
        h.body(MAX_STEP_BODY, set())
        if budget.view(root)["funded"] and budget.owner_of(root) != s["account_id"]:
            raise B.BoardError("not_your_budget", "Only the company that deposited this budget can stop it.")
        h.reply(200, budget.stop(root))
    elif m := SUBMIT.fullmatch(path):
        bounty_id = int(m[1])
        if not X.is_fix(bounty_id, root):
            return False
        s = h.need_screened()
        v = h.body(MAX_SOURCE_BODY, FIX_FIELDS)
        wallet = arc_wallet.wallet_for_submit(bounty_id, s, root)
        with SUBMIT_LOCK:
            if WAITING.full():
                raise B.BoardError("queue_full", f"{QUEUE_CAP} fixes are already waiting. Try again soon. This did not use one of your submissions.")
            secret = B.new_claim_secret()
            row = X.reserve(bounty_id, s["tester"], v["source"], root, secret=secret)
            if wallet:
                row["wallet"] = wallet
                X.save_fix(row, root)
            WAITING.put_nowait(row)
        h.reply(202, {"claim_secret": secret, "n": row["n"], "state": row["state"], "used": row["used_before"] + 1, "of": B.MAX_PER_TESTER, "ledger_label": B.LEDGER_LABEL, "world_id_label": B.WORLD_ID_LABEL})
    elif m := STEP.fullmatch(path):
        bounty_id, n, step = int(m[1]), int(m[2]), m[3]
        if step in ("reject", "finalize", "claim") and arc_wallet.config(root)["on"]:
            raise B.BoardError("on_chain", "Arc decides this step, so the local ledger button is off.")
        s = h.need("engineer") if step == "claim" else h.own(bounty_id)
        v = h.body(MAX_STEP_BODY, {"secret"} if step == "claim" else set())
        if step in ("approve", "decline"):
            row = board_fix_gate.company_decide(bounty_id, n, step == "approve", root)
        else:
            row = X.ledger_step(bounty_id, n, step, s["tester"], root, secret=v.get("secret"))
        h.reply(200, {"fix": X.fix_view(row), "bounty": X.view(bounty_id, root), "ledger_label": B.LEDGER_LABEL})
    elif (m := FIND_CLAIM.fullmatch(path)) and str(int(m[1])) in budget.view(root).get("by_bounty", {}):
        s = h.need("engineer")
        v = h.body(MAX_STEP_BODY, {"secret"})
        row = B.ledger_step(int(m[1]), m[2], "claim", s["tester"], root, secret=v["secret"], on_claim=lambda amount: budget.spend(int(m[1]), amount, f"claim of failure {m[2][:10]}", root))
        h.reply(200, {"failure": row, "bounty": B.get(int(m[1]), root), "ledger_label": B.LEDGER_LABEL})
    else:
        return False
    return True
