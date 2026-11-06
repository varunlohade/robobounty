"""Server-side World ID: signs one request, forwards the IDKit result to the verify endpoint, stores the nullifier. See docs/SWITCH-ON.md.

Each rejection has a fixed code. No text from the proof, the client or the upstream reply reaches a message.
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import sponsor_status as status
import world_store as store

HELPER = Path(__file__).resolve().parent / "world_helper.mjs"
VERIFY_URL = "https://developer.world.org/api/v4/verify/{rp_id}"
TIMEOUT_S = 30
MAX_REPLY_BYTES = 256 * 1024
HEX = re.compile(r"0x[0-9a-fA-F]{1,64}")
WORDS = {
    "not_configured": "World ID is not connected.",
    "bad_shape": "That World ID result has the wrong shape.",
    "wrong_action": "That World ID result is for a different action.",
    "legacy_proof_refused": "This app accepts World ID 4.0 proofs only.",
    "bad_nonce": "That World ID request expired or was already used. Start again.",
    "wrong_wallet": "That proof is not bound to this wallet.",
    "nullifier_replayed": "This World ID was already used here. One human registers once.",
    "wallet_taken": "This wallet already belongs to a verified human.",
    "proof_rejected": "World ID rejected this proof.",
    "wrong_environment": "The proof came from the wrong World ID environment.",
    "verify_unreachable": "The World ID check did not answer. Nothing was stored.",
}


class Rejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code, self.words = code, WORDS[code]


def _no_redirect():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_):
            return None
    return urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def _helper(request, env):
    keep = ("WORLD_RP_SIGNING_KEY",) if request["op"] == "sign" else ()
    done = subprocess.run(["node", str(HELPER)], input=json.dumps(request).encode(), capture_output=True, timeout=30, env=status.child_env(keep, env))
    if done.returncode != 0:
        raise Rejected("not_configured")
    return json.loads(done.stdout)


def _allow_legacy(env):
    return env.get("WORLD_ALLOW_LEGACY") == "1"


def signal_for(wallet):
    return wallet.lower()


def request_context(wallet, env=None):
    """What the browser needs to open IDKit. The signature is made here, and the key never leaves the server."""
    env = os.environ if env is None else env
    state = status.world_status(env)
    if not state["on"]:
        raise Rejected("not_configured")
    signed = _helper({"op": "sign", "action": status.WORLD_ACTION}, env)
    store.add_nonce(status.world_db(env), signed["nonce"], wallet.lower(), status.WORLD_ACTION, signed["expires_at"])
    ctx = {"app_id": env["WORLD_APP_ID"], "action": status.WORLD_ACTION, "signal": signal_for(wallet), "environment": env["WORLD_ENVIRONMENT"], "allow_legacy_proofs": _allow_legacy(env),
           "rp_context": {"rp_id": env["WORLD_RP_ID"], "nonce": signed["nonce"], "created_at": signed["created_at"], "expires_at": signed["expires_at"], "signature": signed["sig"]}}
    if state["mock"]:
        ctx["mock_world_app"] = env["WORLD_VERIFY_URL"].split("/api/")[0] + "/mock/world-app"
        ctx["mock_signal_hash"] = _helper({"op": "hash", "signal": ctx["signal"]}, env)["signal_hash"]
    return ctx


def _items(result, allow_legacy):
    if not isinstance(result, dict):
        raise Rejected("bad_shape")
    items = result.get("responses")
    if not isinstance(items, list) or not 1 <= len(items) <= 4 or not all(isinstance(i, dict) for i in items) or not isinstance(result.get("nonce"), str):
        raise Rejected("bad_shape")
    if result.get("action") != status.WORLD_ACTION:
        raise Rejected("wrong_action")
    # IDKit's own note: with legacy proofs on, one human can hold a v3 and a v4 nullifier, and we cannot link the two. That would pass UNIQUE(nullifier, action) twice.
    if result.get("protocol_version") != "4.0" and not allow_legacy:
        raise Rejected("legacy_proof_refused")
    return items


def _post_verify(result, env):
    url = (env.get("WORLD_VERIFY_URL") or VERIFY_URL).format(rp_id=env["WORLD_RP_ID"])
    # The docs: pin the environment here, so untrusted input cannot pick staging, which accepts test proofs.
    body = json.dumps({**result, "environment": env["WORLD_ENVIRONMENT"]}).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "User-Agent": "crashlab"})
    try:
        with _no_redirect().open(request, timeout=TIMEOUT_S) as reply:
            data = reply.read(MAX_REPLY_BYTES + 1)
            ok = True
    except urllib.error.HTTPError as e:
        data, ok = e.read(MAX_REPLY_BYTES + 1), False
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Rejected("verify_unreachable") from None
    if len(data) > MAX_REPLY_BYTES:
        raise Rejected("proof_rejected")
    try:
        parsed = json.loads(data)
    except ValueError:
        raise Rejected("proof_rejected") from None
    return ok, parsed if isinstance(parsed, dict) else {}


def verify(result, wallet, env=None):
    """Returns {"verified": True, "human_id": ...}, or raises Rejected. The wallet must come from the server, not from the proof."""
    env = os.environ if env is None else env
    if not status.world_status(env)["on"]:
        raise Rejected("not_configured")
    db, action = status.world_db(env), status.WORLD_ACTION
    items = _items(result, _allow_legacy(env))
    # The proof takes signal_hash as an input, so upstream checks the proof against it, and here we hold it to this wallet.
    expected = _helper({"op": "hash", "signal": signal_for(wallet)}, env)["signal_hash"]
    if any(i.get("signal_hash") != expected for i in items):
        raise Rejected("wrong_wallet")
    try:
        nullifiers = [store.nullifier_decimal(i.get("nullifier")) for i in items]
    except ValueError:
        raise Rejected("bad_shape") from None
    if any(store.seen(db, n, action) for n in nullifiers):
        raise Rejected("nullifier_replayed")
    if not store.take_nonce(db, result["nonce"], wallet.lower(), action):
        raise Rejected("bad_nonce")
    ok, reply = _post_verify(result, env)
    if not ok or reply.get("success") is not True:
        codes = {reply.get("code"), *(r.get("code") for r in reply.get("results") or [] if isinstance(r, dict))}
        raise Rejected("nullifier_replayed" if "nullifier_replayed" in codes or "max_verifications_reached" in codes else "proof_rejected")
    if reply.get("environment") != env["WORLD_ENVIRONMENT"]:
        raise Rejected("wrong_environment")
    passed = [r for r in reply.get("results") or [] if isinstance(r, dict) and r.get("success") is True]
    chosen = next((i for i in items if any(r.get("identifier") == i.get("identifier") for r in passed)), None)
    if chosen is None:
        raise Rejected("proof_rejected")
    nullifier = store.nullifier_decimal(chosen["nullifier"])
    try:
        store.add_verification(db, nullifier, action, wallet, env["WORLD_ENVIRONMENT"])
    except store.Replayed:
        raise Rejected("nullifier_replayed" if store.seen(db, nullifier, action) else "wallet_taken") from None
    return {"verified": True, "human_id": store.human_id(nullifier, action)}
