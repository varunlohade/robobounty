"""The Arc wallet routes, mounted by board_server.py after its origin and host check. This process holds no key: it reads receipts and checks signatures, and arc_wallet.py serve sends.

GET  /api/arc                         network facts for the page, or {on: false}
GET  /api/arc/balance/<address>       USDC and gas, read from the chain now
GET  /api/arc/demo-fix                the stored good fix, on the recorded film path only
POST /api/arc/challenge               {purpose: wallet, address} or {purpose: reject, bounty, fix}. The message to sign, once.
POST /api/arc/wallet                  {nonce, signature}. An engineer session.
POST /api/arc/bounties/<id>/plan      {}. The company that posted it. The createBounty call to send.
POST /api/arc/bounties/<id>/funded    {create_tx, approve_tx?}. Saved only after the receipt and the contract agree.
POST /api/arc/bounties/<id>/fixes/<n>/reject   {nonce, signature}. Signed by the wallet that funded it.
POST /api/arc/bounties/<id>/fixes/<n>/claimed  {tx}. The engineer's fallback for a stuck agent.
"""
import os
import re
import secrets
import threading
import time

import arc_mirror as M
import arc_wallet as W
import board_store as B
import site_auth as A

CHALLENGE_S = 300
MAX_BODY = 1024
BALANCE = re.compile(r"/api/arc/balance/(0x[0-9a-fA-F]{40})")
PLAN = re.compile(r"/api/arc/bounties/([0-9]{1,9})/plan")
FUNDED = re.compile(r"/api/arc/bounties/([0-9]{1,9})/funded")
FIX_STEP = re.compile(r"/api/arc/bounties/([0-9]{1,9})/fixes/([0-9]{1,9})/(reject|claimed)")
ERROR_STATUS = {"arc_off": 409, "already_funded": 409, "tx_reverted": 409, "tx_not_funding": 409, "tx_wrong_fields": 409, "tx_not_claim": 409, "bad_signature": 403, "bad_challenge": 403, "public_key_wallet": 409, "over_cap": 409, "rpc_down": 502, "timeout": 504, "reverted": 409, "empty_balance": 409}
CHALLENGES = {}
LOCK = threading.Lock()


def _new_challenge(account_id, purpose, message_of, **held):
    nonce = secrets.token_hex(16)
    message = message_of(nonce)
    now = time.time()
    with LOCK:
        for key in [k for k, v in CHALLENGES.items() if v["until"] < now]:
            del CHALLENGES[key]
        CHALLENGES[nonce] = {"account": account_id, "purpose": purpose, "message": message, "until": now + CHALLENGE_S, **held}
    return {"nonce": nonce, "message": message}


def _take_challenge(nonce, account_id, purpose):
    with LOCK:
        held = CHALLENGES.pop(nonce, None) if isinstance(nonce, str) else None
    if not held or held["account"] != account_id or held["purpose"] != purpose or held["until"] < time.time():
        raise B.BoardError("bad_challenge", "This signing request ended. Press the button again.")
    return held


def route(h, method, root):
    if not h.path.startswith("/api/arc"):
        return False
    try:
        return _get(h, root) if method == "GET" else _post(h, root)
    except M.ArcError as e:
        raise B.BoardError(e.code, e.words) from None


def _get(h, root):
    if h.path == "/api/arc":
        h.reply(200, W.config(root))
    elif m := BALANCE.fullmatch(h.path):
        h.reply(200, W.balances(m[1], root))
    elif h.path == "/api/arc/demo-fix":
        if os.environ.get(W.DEMO_ENV) != "1":
            raise B.BoardError("not_found", "There is no stored fix outside the recorded film path.")
        h.reply(200, {"source": W.DEMO_FIX.read_text(), "group": W.DEMO_GROUP})
    else:
        return False
    return True


def _post(h, root):
    path = h.path
    if path == "/api/arc/challenge":
        return _challenge(h, root)
    if path == "/api/arc/wallet":
        s = h.need("engineer")
        v = h.body(MAX_BODY, {"nonce", "signature"})
        W.need_on(root)
        held = _take_challenge(v["nonce"], s["account_id"], "wallet")
        if not W.signer_ok(held["address"], held["message"], v["signature"]):
            raise B.BoardError("bad_signature", "That signature does not come from this wallet, so nothing was saved.")
        A.save_signed_wallet(s["account_id"], held["address"])
        h.reply(200, {"wallet": held["address"].lower(), "signed": True})
    elif m := PLAN.fullmatch(path):
        h.own(int(m[1]))
        h.body(MAX_BODY, set())
        h.reply(200, W.fund_plan(int(m[1]), root))
    elif m := FUNDED.fullmatch(path):
        h.own(int(m[1]))
        v = h.body(MAX_BODY, {"create_tx"}, ("approve_tx",))
        saved = W.verify_funded(int(m[1]), v["create_tx"], v.get("approve_tx"), root)
        h.reply(202 if saved is None else 200, {"waiting": True} if saved is None else saved)
    elif m := FIX_STEP.fullmatch(path):
        bounty_id, n = int(m[1]), int(m[2])
        if m[3] == "reject":
            s = h.own(bounty_id)
            v = h.body(MAX_BODY, {"nonce", "signature"})
            held = _take_challenge(v["nonce"], s["account_id"], "reject")
            if held["bounty"] != bounty_id or held["fix"] != n:
                raise B.BoardError("bad_challenge", "This signing request was for another fix. Press the button again.")
            W.request_reject(bounty_id, n, v["nonce"], v["signature"], root)
            h.reply(200, {"asked": True})
        else:
            h.need("engineer")
            v = h.body(MAX_BODY, {"tx"})
            saved = W.record_claim(bounty_id, n, v["tx"], root)
            h.reply(202 if saved is None else 200, {"waiting": True} if saved is None else saved)
    else:
        return False
    return True


def _challenge(h, root):
    v = h.body(MAX_BODY, {"purpose"}, ("address", "bounty", "fix"))
    value = W.need_on(root)
    if v["purpose"] == "wallet":
        s = h.need("engineer")
        address = v.get("address")
        if not (isinstance(address, str) and W.ADDRESS.fullmatch(address)):
            raise B.BoardError("bad_address", "That is not a wallet address.")
        if value["real"] and address.lower() in M.DEFAULT_ACCOUNTS:
            raise B.BoardError("public_key_wallet", "This is a public test account whose key anyone can get. Use a new wallet.")
        h.reply(200, _new_challenge(s["account_id"], "wallet", lambda nonce: W.wallet_message(s["tester"], address, nonce), address=address))
    elif v["purpose"] == "reject" and isinstance(v.get("bounty"), int) and isinstance(v.get("fix"), int):
        s = h.own(v["bounty"])
        h.reply(200, _new_challenge(s["account_id"], "reject", lambda nonce: W.reject_message(v["bounty"], v["fix"], nonce), bounty=v["bounty"], fix=v["fix"]))
    else:
        raise B.BoardError("bad_fields", "This signing request is not valid.")
    return True
