"""World ID sign-in for the site. The server signs each request and checks each proof, and only this file can mark a person verified.

First visit: one uniqueness proof that also creates a World ID session. Later visits: a proof of that saved session. World ID 4.0 uniqueness proofs are one-time per action, so a second uniqueness login would fail.
Adapted from policy/sponsors/world_id.py on sponsors-switch-on. Each rejection has a fixed code. No text from the proof or the upstream reply reaches a message.
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE / "site_world_helper.mjs"
DB = HERE.parent / "runs" / "site" / "world.sqlite"
VERIFY_URL = "https://developer.world.org/api/v4/verify/{rp_id}"
NEEDS = ("WORLD_APP_ID", "WORLD_ACTION", "WORLD_RP_ID", "WORLD_RP_SIGNING_KEY", "WORLD_ENVIRONMENT")
TIMEOUT_S = 30
MAX_REPLY_BYTES = 256 * 1024
LOGIN_S = 12 * 3600
SESSION = re.compile(r"session_[0-9a-zA-Z]{1,200}")
WORDS = {
    "not_configured": "World ID is not set up on this server yet.",
    "bad_shape": "That World ID result has the wrong shape.",
    "wrong_action": "That World ID result is for a different action.",
    "bad_nonce": "That World ID request expired or was already used. Start again.",
    "already_enrolled": "This World ID already signed up from another browser. Sign in from that browser.",
    "wrong_session": "That proof is for a different World ID session.",
    "replayed": "That proof was already used. Start again.",
    "proof_rejected": "World ID rejected this proof.",
    "wrong_environment": "The proof came from the wrong World ID environment.",
    "verify_unreachable": "The World ID check did not answer. You are not signed in.",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS humans (nullifier TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL, human_id TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS proofs (session_nullifier TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, browser TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS logins (token_sha TEXT PRIMARY KEY, human_id TEXT NOT NULL, environment TEXT NOT NULL, expires_at REAL NOT NULL);
"""


class Rejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code, self.words = code, WORDS[code]


def _open(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.executescript(SCHEMA)
    return db


def status(env=None):
    """Names of what is missing, never a value."""
    env = os.environ if env is None else env
    missing = [n for n in NEEDS if not env.get(n)]
    if not missing and env["WORLD_ENVIRONMENT"] not in ("staging", "production"):
        missing = ["WORLD_ENVIRONMENT must be staging or production"]
    return {"on": not missing, "missing": missing, "environment": env.get("WORLD_ENVIRONMENT") if not missing else None}


def _sign(action, env):
    child = {k: v for k, v in env.items() if k in ("PATH", "HOME", "WORLD_RP_SIGNING_KEY")}
    done = subprocess.run(["node", str(HELPER)], input=json.dumps({"action": action}).encode(), capture_output=True, timeout=30, env=child, cwd=HERE)
    if done.returncode != 0:
        raise Rejected("not_configured")
    return json.loads(done.stdout)


def request_context(browser, saved_session, env=None, db=DB):
    """What the browser needs to open IDKit. The signature is made here, and the key never leaves the server."""
    env = os.environ if env is None else env
    if not status(env)["on"]:
        raise Rejected("not_configured")
    with closing(_open(db)) as d:
        known = saved_session and d.execute("SELECT 1 FROM humans WHERE session_id=?", (saved_session,)).fetchone()
    action = None if known else env["WORLD_ACTION"]
    signed = _sign(action, env)
    with closing(_open(db)) as d:
        d.execute("INSERT OR REPLACE INTO nonces VALUES (?,?,?)", (signed["nonce"], browser, signed["expires_at"]))
    ctx = {"app_id": env["WORLD_APP_ID"], "environment": env["WORLD_ENVIRONMENT"],
           "rp_context": {"rp_id": env["WORLD_RP_ID"], "nonce": signed["nonce"], "created_at": signed["created_at"], "expires_at": signed["expires_at"], "signature": signed["sig"]}}
    return {**ctx, "mode": "prove", "session_id": saved_session} if known else {**ctx, "mode": "enrol", "action": action}


def _no_redirect():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_):
            return None
    return urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def post_verify(result, env):
    # The docs: pin the environment here, so untrusted input cannot pick staging, which accepts test proofs.
    body = json.dumps({**result, "environment": env["WORLD_ENVIRONMENT"]}).encode()
    request = urllib.request.Request(VERIFY_URL.format(rp_id=env["WORLD_RP_ID"]), data=body, method="POST", headers={"Content-Type": "application/json", "User-Agent": "crashlab"})
    try:
        with _no_redirect().open(request, timeout=TIMEOUT_S) as reply:
            data, ok = reply.read(MAX_REPLY_BYTES + 1), True
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


def _nullifier(value):
    if not isinstance(value, str) or not value.startswith("0x") or len(value) > 66:
        raise Rejected("bad_shape")
    try:
        return str(int(value, 16))
    except ValueError:
        raise Rejected("bad_shape") from None


def _human_id(nullifier, action):
    return "0x" + hashlib.sha256(f"crashlab.site.human.v1|{action}|{nullifier}".encode()).hexdigest()


def verify(result, browser, saved_session, env=None, db=DB, post=post_verify):
    """Returns {"verified": True, ...} or raises Rejected. `post` is replaced only by the labelled mock tests."""
    env = os.environ if env is None else env
    if not status(env)["on"]:
        raise Rejected("not_configured")
    if not isinstance(result, dict) or not isinstance(result.get("nonce"), str) or result.get("protocol_version") != "4.0":
        raise Rejected("bad_shape")
    items = result.get("responses")
    session = result.get("session_id")
    if not isinstance(items, list) or not 1 <= len(items) <= 4 or not all(isinstance(i, dict) for i in items) or not isinstance(session, str) or not SESSION.fullmatch(session):
        raise Rejected("bad_shape")
    enrol = "action" in result
    with closing(_open(db)) as d:
        if enrol:
            if result["action"] != env["WORLD_ACTION"]:
                raise Rejected("wrong_action")
            nullifiers = [_nullifier(i.get("nullifier")) for i in items]
            if any(d.execute("SELECT 1 FROM humans WHERE nullifier=?", (n,)).fetchone() for n in nullifiers):
                raise Rejected("already_enrolled")
        else:
            row = d.execute("SELECT human_id FROM humans WHERE session_id=?", (session,)).fetchone()
            if row is None or session != saved_session:
                raise Rejected("wrong_session")
            pairs = [i.get("session_nullifier") for i in items]
            if not all(isinstance(p, list) and p and isinstance(p[0], str) for p in pairs):
                raise Rejected("bad_shape")
            if any(d.execute("SELECT 1 FROM proofs WHERE session_nullifier=?", (p[0],)).fetchone() for p in pairs):
                raise Rejected("replayed")
        taken = d.execute("DELETE FROM nonces WHERE nonce=? AND browser=? AND expires_at>=?", (result["nonce"], browser, time.time())).rowcount
    if taken != 1:
        raise Rejected("bad_nonce")
    ok, reply = post(result, env)
    if not ok or reply.get("success") is not True:
        raise Rejected("proof_rejected")
    if reply.get("environment") != env["WORLD_ENVIRONMENT"]:
        raise Rejected("wrong_environment")
    passed = [r for r in reply.get("results") or [] if isinstance(r, dict) and r.get("success") is True]
    chosen = next((i for i in items if any(r.get("identifier") == i.get("identifier") for r in passed)), None)
    if chosen is None:
        raise Rejected("proof_rejected")
    with closing(_open(db)) as d:
        try:
            if enrol:
                nullifier = _nullifier(chosen.get("nullifier"))
                human = _human_id(nullifier, env["WORLD_ACTION"])
                d.execute("INSERT INTO humans VALUES (?,?,?,?)", (nullifier, session, human, time.time()))
            else:
                human = row[0]
                d.execute("INSERT INTO proofs VALUES (?)", (chosen["session_nullifier"][0],))
        except sqlite3.IntegrityError:
            raise Rejected("already_enrolled" if enrol else "replayed") from None
    return {"verified": True, "human_id": human, "session_id": session, "environment": env["WORLD_ENVIRONMENT"]}


def _token_sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def add_login(token, human_id, environment, db=DB, now=None):
    now = time.time() if now is None else now
    with closing(_open(db)) as d:
        d.execute("DELETE FROM logins WHERE expires_at<?", (now,))
        d.execute("INSERT OR REPLACE INTO logins VALUES (?,?,?,?)", (_token_sha(token), human_id, environment, now + LOGIN_S))


def login_of(token, db=DB, now=None):
    if not token:
        return None
    now = time.time() if now is None else now
    with closing(_open(db)) as d:
        row = d.execute("SELECT human_id, environment FROM logins WHERE token_sha=? AND expires_at>=?", (_token_sha(token), now)).fetchone()
    return {"human_id": row[0], "environment": row[1]} if row else None


def drop_login(token, db=DB):
    if token:
        with closing(_open(db)) as d:
            d.execute("DELETE FROM logins WHERE token_sha=?", (_token_sha(token),))
