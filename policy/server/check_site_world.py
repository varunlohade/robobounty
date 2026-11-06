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

W.add_login("tok", done["human_id"], "staging", "human", db)
check(W.login_of("tok", db)["human_id"] == done["human_id"], "a login names its human")
check(W.login_of("tok", db)["credential"] == "human", "a human login says human")
check(W.login_of("forged", db) is None and W.login_of(None, db) is None, "a forged token names nobody")
check(W.login_of("tok", db, now=__import__("time").time() + W.LOGIN_S + 1) is None, "a login expires")
W.drop_login("tok", db)
check(W.login_of("tok", db) is None, "sign out ends the login")

# Device mode. Mock replies again: these prove what the server does with a 3.0 reply, not that a real World App proof passes.
DEV = {**ENV, "WORLD_CREDENTIAL": "device"}
DEV_GOOD = {"success": True, "environment": "staging", "protocol_version": "3.0", "results": [{"identifier": "device", "success": True}]}
sent = []


def dev_upstream(result, env):
    sent.append(env)
    return True, DEV_GOOD


def dev_ctx(browser="d1", saved=None):
    return W.request_context(browser, saved, DEV, db)


def dev_result(ctx, **item):
    nonce = ctx["rp_context"]["nonce"]
    return {"protocol_version": "3.0", "nonce": nonce, "action": DEV["WORLD_ACTION"], "environment": "production",
            "responses": [{"identifier": "device", "nullifier": "0x" + "cd" * 16, "merkle_root": "0x1", "proof": "0x1", "signal_hash": W._signal_hash(nonce, DEV), **item}]}


def dev_verify(result, browser="d1", post=dev_upstream):
    return lambda: W.verify(result, browser, None, DEV, db, post)


check(W.credential_of(ENV) == "human" and W.status(ENV)["credential"] == "human", "no WORLD_CREDENTIAL means human")
check(not W.status({**ENV, "WORLD_CREDENTIAL": "orb"})["on"], "an unknown WORLD_CREDENTIAL turns World ID off")
ctx = fresh()
check(ctx["credential"] == "human" and "signal" not in ctx, "human mode asks for no device signal")
ctx = fresh()
check(code_of(lambda: W.verify(dev_result(ctx), "b1", None, ENV, db, upstream(True, DEV_GOOD))) == "bad_shape", "human mode refuses a device proof")

ctx = dev_ctx()
check(ctx["credential"] == "device" and ctx["mode"] == "enrol" and ctx["signal"] == ctx["rp_context"]["nonce"], "device mode puts the nonce in the signal")
check(dev_ctx("d1", SESSION)["mode"] == "enrol", "device mode ignores a saved session, because 3.0 has none")
check(code_of(dev_verify(enrol_result(ctx["rp_context"]["nonce"]))) == "wrong_credential", "device mode refuses a 4.0 human proof")
check(code_of(dev_verify(dev_result(ctx, identifier="orb"))) == "wrong_credential", "device mode refuses a legacy orb proof")
check(code_of(dev_verify(dev_result(ctx, identifier="selfie"))) == "wrong_credential", "device mode refuses a selfie proof")
check(code_of(dev_verify({**dev_result(ctx), "action": "other"})) == "wrong_action", "device mode refuses another action")
check(code_of(dev_verify(dev_result(ctx, signal_hash="0x1234"))) == "bad_nonce", "device mode refuses a proof made for another request")
other = dev_result(ctx)
other["responses"][0].pop("signal_hash")
check(code_of(dev_verify(other)) == "bad_nonce", "device mode refuses a proof with no signal hash")
check(code_of(dev_verify(dev_result(ctx), "someone-else")) == "bad_nonce", "a device nonce from another browser is refused")

ctx = dev_ctx()
check(code_of(dev_verify(dev_result(ctx), post=upstream(False, {"code": "invalid_proof"}))) == "proof_rejected", "an upstream refusal of a device proof is refused")
ctx = dev_ctx()
check(code_of(dev_verify(dev_result(ctx), post=upstream(True, {**DEV_GOOD, "environment": "production"}))) == "wrong_environment", "a device proof from the wrong environment is refused")
ctx = dev_ctx()
check(code_of(dev_verify(dev_result(ctx), post=upstream(True, {**DEV_GOOD, "results": [{"identifier": "orb", "success": True}]}))) == "proof_rejected", "upstream passing another credential is refused")
ctx = dev_ctx()
check(code_of(dev_verify(dev_result(ctx), post=upstream(True, {**DEV_GOOD, "protocol_version": "4.0"}))) == "wrong_credential", "upstream naming protocol 4.0 is refused")

ctx = dev_ctx()
replay = dev_result(ctx)
device = W.verify(replay, "d1", None, DEV, db, dev_upstream)
check(device["verified"] is True and device["credential"] == "device" and device["session_id"] is None, "a good device reply signs in, labelled device, with no session")
check("cd" * 16 not in device["human_id"], "the device id hides the nullifier")
check(sent[-1]["WORLD_ENVIRONMENT"] == "staging", "the server's environment goes to the verify call")
check(code_of(dev_verify(replay)) == "bad_nonce", "a replayed device proof is refused")
ctx2 = dev_ctx()
check(code_of(dev_verify({**replay, "nonce": ctx2["rp_context"]["nonce"]})) == "bad_nonce", "an old device proof under a fresh nonce is refused")
again = W.verify(dev_result(dev_ctx()), "d1", None, DEV, db, dev_upstream)
check(again["human_id"] == device["human_id"], "the same device signs in again with a new proof and the same id")
W.add_login("dtok", device["human_id"], "staging", device["credential"], db)
check(W.login_of("dtok", db)["credential"] == "device", "a device login still says device")
ctx = fresh()
check(W.login_of("dtok", db)["credential"] == "device" and ctx["credential"] == "human", "switching back to human mode does not relabel a device login")
W.drop_login("dtok", db)
print(f"{failed} FAILED" if failed else "ALL PASS (mock replies only, no real World ID call)")
sys.exit(1 if failed else 0)
