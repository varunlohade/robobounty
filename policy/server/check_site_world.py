#!/usr/bin/env python3
"""MOCK TESTS. No World ID service gets a call here. Every upstream reply below is invented in this file, and the test signing key is random.

They prove what the server does with each kind of reply. They do not prove that a real World App proof passes.
Run: policy/.venv/bin/python policy/server/check_site_world.py
"""
import json
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_world as W

failed = 0


def check(ok, what):
    global failed
    print(f"{'PASS' if ok else 'FAIL'} MOCK {what}")
    failed += 0 if ok else 1


def code_of(run):
    try:
        run()
    except W.Rejected as r:
        return r.code
    return None


ENV = {"PATH": __import__("os").environ["PATH"], "WORLD_APP_ID": "app_mock", "WORLD_ACTION": "crashlab-site-login", "WORLD_RP_ID": "rp_mock", "WORLD_RP_SIGNING_KEY": "0x" + secrets.token_hex(32), "WORLD_ENVIRONMENT": "staging"}
GOOD = {"success": True, "environment": "staging", "results": [{"identifier": "proof_of_human", "success": True}]}
tmp = tempfile.mkdtemp(prefix="site-world-mock-")
db = Path(tmp) / "world.sqlite"
SESSION = "session_abc123"


def upstream(ok, reply):
    return lambda result, env: (ok, reply)


def enrol_result(nonce, **over):
    return {"protocol_version": "4.0", "nonce": nonce, "action": ENV["WORLD_ACTION"], "session_id": SESSION, "environment": "staging",
            "responses": [{"identifier": "proof_of_human", "nullifier": "0x" + "ab" * 16, "proof": ["0x1"]}], **over}


def fresh(browser="b1", saved=None):
    ctx = W.request_context(browser, saved, ENV, db)
    assert ctx["rp_context"]["signature"] and ctx["rp_context"]["nonce"]
    return ctx


check(not W.status({})["on"] and "WORLD_APP_ID" in W.status({})["missing"], "no settings means off, and names what is missing")
check(code_of(lambda: W.request_context("b1", None, {}, db)) == "not_configured", "no settings refuses to sign")
check(code_of(lambda: W.verify({}, "b1", None, {}, db, upstream(True, GOOD))) == "not_configured", "no settings refuses to verify")

ctx = fresh()
check(ctx["mode"] == "enrol" and ctx["action"] == ENV["WORLD_ACTION"], "a new browser enrols")
check(ENV["WORLD_RP_SIGNING_KEY"] not in json.dumps(ctx), "the signing key stays out of the reply")

check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"], protocol_version="3.0"), "b1", None, ENV, db, upstream(True, GOOD))) == "bad_shape", "a legacy proof is refused")
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"], action="other"), "b1", None, ENV, db, upstream(True, GOOD))) == "wrong_action", "another action is refused")
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "someone-else", None, ENV, db, upstream(True, GOOD))) == "bad_nonce", "a nonce from another browser is refused")

ctx = fresh()
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, upstream(False, {"code": "invalid_proof"}))) == "proof_rejected", "an upstream refusal is refused")
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, upstream(True, GOOD))) == "bad_nonce", "a nonce works once")
ctx = fresh()
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, upstream(True, {**GOOD, "environment": "production"}))) == "wrong_environment", "the wrong environment is refused")
ctx = fresh()
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, upstream(True, {**GOOD, "results": []}))) == "proof_rejected", "success with no passed credential is refused")


def unreachable(result, env):
    raise W.Rejected("verify_unreachable")


ctx = fresh()
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, unreachable)) == "verify_unreachable", "no answer means not verified")

ctx = fresh()
done = W.verify(enrol_result(ctx["rp_context"]["nonce"]), "b1", None, ENV, db, upstream(True, GOOD))
check(done["verified"] is True and done["human_id"].startswith("0x") and "ab" * 16 not in done["human_id"], "a good reply verifies, and the id hides the nullifier")

ctx = fresh("b2")
check(code_of(lambda: W.verify(enrol_result(ctx["rp_context"]["nonce"], session_id="session_other"), "b2", None, ENV, db, upstream(True, GOOD))) == "already_enrolled", "one human cannot enrol twice")

ctx = fresh("b1", SESSION)
check(ctx["mode"] == "prove" and ctx["session_id"] == SESSION and "action" not in ctx, "a returning browser proves its session")


def prove_result(nonce, session=SESSION, nullifier="0x77"):
    return {"protocol_version": "4.0", "nonce": nonce, "session_id": session, "environment": "staging", "responses": [{"identifier": "proof_of_human", "session_nullifier": [nullifier, "0x1"], "proof": ["0x1"]}]}


check(code_of(lambda: W.verify(prove_result(ctx["rp_context"]["nonce"], "session_other"), "b1", SESSION, ENV, db, upstream(True, GOOD))) == "wrong_session", "another session is refused")
again = W.verify(prove_result(ctx["rp_context"]["nonce"]), "b1", SESSION, ENV, db, upstream(True, GOOD))
check(again["human_id"] == done["human_id"], "the returning proof names the same human")
ctx = fresh("b1", SESSION)
check(code_of(lambda: W.verify(prove_result(ctx["rp_context"]["nonce"]), "b1", SESSION, ENV, db, upstream(True, GOOD))) == "replayed", "a session proof works once")

W.add_login("tok", done["human_id"], "staging", db)
check(W.login_of("tok", db)["human_id"] == done["human_id"], "a login names its human")
check(W.login_of("forged", db) is None and W.login_of(None, db) is None, "a forged token names nobody")
check(W.login_of("tok", db, now=__import__("time").time() + W.LOGIN_S + 1) is None, "a login expires")
W.drop_login("tok", db)
check(W.login_of("tok", db) is None, "sign out ends the login")
print(f"{failed} FAILED" if failed else "ALL PASS (mock replies only, no real World ID call)")
sys.exit(1 if failed else 0)
