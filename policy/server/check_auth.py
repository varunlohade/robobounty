#!/usr/bin/env python3
"""Attacks on the auth system, over real HTTP, against a real site server and a real board server on their own ports, with a throwaway store.
World ID's upstream reply is a MOCK (check_auth_server.py). No real scan runs. No real email is sent.
Run: policy/.venv/bin/python policy/server/check_auth.py
"""
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOUNTY = HERE.parent / "bounty"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BOUNTY))
SITE, DEVICE_SITE, BOARD, RUN, WEB = 7397, 7395, 7396, 7394, 7399
ORIGIN = f"http://localhost:{WEB}"
tmp = Path(tempfile.mkdtemp(prefix="check-auth-"))
DB = tmp / "auth.sqlite"
ROOT = tmp / "board"
ROOT.mkdir()
os.environ["CRASHLAB_AUTH_DB"] = str(DB)
import screener as Q
import site_auth as A
import site_world as W

ENV = {**os.environ, "CRASHLAB_WEB_PORT": str(WEB), "CRASHLAB_TRUST_PROXY": "1", "CHECK_WORLD_DB": str(tmp / "world.sqlite"), "WORLD_APP_ID": "app_mock", "WORLD_ACTION": "crashlab-site-login", "WORLD_RP_ID": "rp_mock", "WORLD_RP_SIGNING_KEY": "0x" + secrets.token_hex(32), "WORLD_ENVIRONMENT": "staging", "WORLD_CREDENTIAL": "human"}
failed = 0


def check(ok, what, detail=""):
    global failed
    failed += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}{f': {detail}' if detail and not ok else ''}", flush=True)


class Browser:
    """One browser: its own cookie jar, and the CSRF token /me gave it."""
    counter = 0

    def __init__(self, port=SITE):
        Browser.counter += 1
        self.jar, self.port, self.csrf, self.ip = {}, port, "", f"10.0.0.{Browser.counter}"

    def call(self, method, path, body=None, headers=None, origin=ORIGIN, marker=True, csrf=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": f"localhost:{WEB}", "X-Forwarded-For": self.ip}
        if origin:
            h["Origin"] = origin
        if marker and method == "POST":
            h["X-CrashLab-Request"] = "1"
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if self.jar:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c.request(method, path, data, h)
        r = c.getresponse()
        self.set_cookie = r.getheaders()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                name, _, rest = v.partition("=")
                value = rest.split(";")[0]
                if "Max-Age=0" in v:
                    self.jar.pop(name, None)
                else:
                    self.jar[name] = value
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, {}

    def me(self):
        s, m = self.call("GET", "/site-api/auth/me")
        self.csrf = m.get("csrf", "")
        return m

    def cookie_line(self):
        return next((v for k, v in self.set_cookie if k.lower() == "set-cookie" and v.startswith("crashlab_session=")), "")

    def signup(self, email, password="correct horse battery", company="Acme Robots"):
        return self.call("POST", "/site-api/auth/signup", {"email": email, "password": password, "company": company})

    def signin(self, email, password):
        return self.call("POST", "/site-api/auth/signin", {"email": email, "password": password})

    def board_token(self):
        self.me()
        return self.call("POST", "/site-api/auth/board-token")[1].get("token")


def board(method, path, body=None, token=None, origin=ORIGIN, port=None):
    c = http.client.HTTPConnection("127.0.0.1", port or BOARD, timeout=60)
    h = {"Content-Type": "application/json"}
    if origin:
        h["Origin"] = origin
    if token:
        h["Authorization"] = f"Bearer {token}"
    c.request(method, path, json.dumps(body) if body is not None else None, h)
    try:
        r = c.getresponse()
    except http.client.RemoteDisconnected:  # The stand-in fix bounty below has no ledger, so a request past the role check stops there.
        return 599, {}
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, {}


def wait_up(port, host_header):
    for _ in range(300):
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/site-api/health" if port not in (BOARD, RUN) else "/api/health", headers={"Host": host_header, "Origin": ORIGIN})
            if c.getresponse().status == 200:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise SystemExit(f"port {port} did not start")


LOG = open(tmp / "servers.log", "wb")
PY = sys.executable
procs = [subprocess.Popen([PY, str(HERE / "check_auth_server.py"), "--port", str(SITE)], env=ENV, stdout=LOG, stderr=LOG),
         subprocess.Popen([PY, str(HERE / "check_auth_server.py"), "--port", str(DEVICE_SITE)], env={**ENV, "WORLD_CREDENTIAL": "device"}, stdout=LOG, stderr=LOG),
         subprocess.Popen([PY, str(BOUNTY / "board_server.py"), "--root", str(ROOT), "--port", str(BOARD)], env=ENV, stdout=LOG, stderr=LOG),
         subprocess.Popen([PY, str(HERE / "server.py"), "--port", str(RUN)], env=ENV, stdout=LOG, stderr=LOG)]
PASSWORD = "correct horse battery"
try:
    wait_up(SITE, f"localhost:{WEB}")
    wait_up(DEVICE_SITE, f"localhost:{WEB}")
    wait_up(BOARD, f"127.0.0.1:{BOARD}")
    wait_up(RUN, f"127.0.0.1:{RUN}")

    # Sign-up and the cookie.
    a = Browser()
    check(a.me()["signed_in"] is False, "a new browser is signed out")
    s, r = a.signup("Founder@Acme.example")
    line = a.cookie_line()
    check(s == 200 and r["role"] == "company" and r["label"] == "Acme Robots", "sign-up makes a company session", str(r))
    check(r["verification_label"] == "Email not verified", "the session says Email not verified")
    check("HttpOnly" in line and "SameSite=Lax" in line and "Max-Age=" in line, "the cookie is HttpOnly, SameSite=Lax, with an expiry", line)
    m = a.me()
    check(m["role"] == "company" and m["verification"] == "email_not_verified" and m["verified"] is False, "/me is the source of role, label and level")
    token = a.jar["crashlab_session"]
    raw = __import__("sqlite3").connect(DB)
    stored = raw.execute("SELECT token_sha FROM sessions").fetchall()
    check(all(token not in row[0] for row in stored) and (A._sha(token),) in stored, "the store holds the token's hash and not the token")
    pw = raw.execute("SELECT password FROM accounts WHERE email='founder@acme.example'").fetchone()[0]
    check(pw.startswith("scrypt$32768$8$1$") and PASSWORD not in pw, "the password is scrypt with its own salt", pw[:20])
    b2 = Browser()
    b2.signup("second@acme.example")
    pw2 = raw.execute("SELECT password FROM accounts WHERE email='second@acme.example'").fetchone()[0]
    check(pw.split("$")[4] != pw2.split("$")[4] and pw.split("$")[5] != pw2.split("$")[5], "the same password gives another hash for another user")
    check((os.stat(DB).st_mode & 0o777) == 0o600 and (os.stat(DB.with_suffix(".key")).st_mode & 0o777) == 0o600, "the store and the key are readable by this user only")

    # Password and email rules, generic words.
    n = Browser()
    check(n.signup("short@acme.example", "short")[1].get("error") == "bad_password", "a short password is refused")
    check(n.signup("weak@acme.example", "aaaaaaaaaaaaaaaa")[1].get("error") == "bad_password", "a repeated password is refused")
    check(n.signup("mailpass@acme.example", "mailpass-mailpass-1")[1].get("error") == "bad_password", "a password holding the email name is refused")
    check(n.signup("not an email", PASSWORD)[1].get("error") == "bad_email", "a bad email is refused")
    s, taken = n.signup("founder@acme.example")
    check(s == 409 and "exists" not in taken["words"].lower() and "founder" not in json.dumps(taken), "a taken email gets generic words", str(taken))
    check(n.me()["signed_in"] is False, "a refused sign-up makes no session")

    # Sign-in, wrong password, unknown email.
    c = Browser()
    s1, wrong = c.signin("founder@acme.example", "wrong password here")
    s2, unknown = c.signin("nobody@acme.example", "wrong password here")
    check(s1 == s2 == 401 and wrong == unknown, "a wrong password and an unknown email get the same reply", f"{wrong} {unknown}")
    check(c.me()["signed_in"] is False, "a wrong password makes no session")
    s, r = c.signin("FOUNDER@acme.example", PASSWORD)
    check(s == 200 and r["role"] == "company", "the right password signs in, in any letter case")

    # Rate limit: per email, then per address. Parallel tries count too.
    from concurrent.futures import ThreadPoolExecutor
    v = Browser()
    v.signup("victim@acme.example")
    def guess(i):
        g = Browser()
        g.ip = f"10.9.{i}.1"
        return g.signin("victim@acme.example", f"wrong guess number {i}")[0]
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(guess, range(24)))
    check(codes.count(401) == A.EMAIL_TRIES and codes.count(429) == 24 - A.EMAIL_TRIES, "24 parallel guesses from 24 addresses: only the email limit passes", str(codes))
    late = Browser()
    check(late.signin("victim@acme.example", PASSWORD)[0] == 429, "at the limit, even the right password waits")
    f = Browser()
    codes = [f.signin(f"u{i}@acme.example", "wrong password here")[0] for i in range(A.IP_TRIES + 1)]
    check(codes[-1] == 429 and codes[:A.IP_TRIES].count(401) == A.IP_TRIES, "one address across many emails hits its own limit", str(codes[-3:]))
    with __import__("contextlib").closing(A._open(DB)) as d:
        check(not A._take(d, f"ip:{f.ip}", A.IP_TRIES, time.time()) and A._take(d, f"ip:{f.ip}", A.IP_TRIES, time.time() + A.WINDOW_S + 1), "the limit ends after its window")

    # Logout.
    old = dict(c.jar)
    c.me()
    check(c.call("POST", "/site-api/auth/logout", csrf=False)[0] == 403, "logout without the CSRF token is refused")
    check(c.call("POST", "/site-api/auth/logout")[1].get("ok") is True and "crashlab_session" not in c.jar, "logout clears the cookie")
    replay = Browser()
    replay.jar = old
    check(replay.me()["signed_in"] is False, "logout deletes the session: the old token is dead")

    # Expired session, forged cookie.
    e = Browser()
    e.signin("founder@acme.example", PASSWORD)
    with __import__("contextlib").closing(A._open(DB)) as d:
        d.execute("UPDATE sessions SET expires_at=? WHERE token_sha=?", (time.time() - 1, A._sha(e.jar["crashlab_session"])))
    m = e.me()
    check(m["signed_in"] is False and m["expired"] is True and "crashlab_session" not in e.jar, "an expired session reads as expired and clears its cookie, so no loop")
    check(e.me()["expired"] is False, "the next read is plain signed out")
    forged = Browser()
    forged.jar["crashlab_session"] = secrets.token_urlsafe(32)
    check(forged.me()["signed_in"] is False, "a forged cookie names nobody")
    forged.jar["crashlab_session"] = A._sha(a.jar["crashlab_session"])
    check(forged.me()["signed_in"] is False, "a stolen hash from the store is not a token")

    # Session fixation.
    fix = Browser()
    planted = secrets.token_urlsafe(32)
    fix.jar["crashlab_session"] = planted
    fix.signin("founder@acme.example", PASSWORD)
    check(fix.jar["crashlab_session"] != planted, "sign-in ignores a planted token")
    attacker = Browser()
    attacker.jar["crashlab_session"] = planted
    check(attacker.me()["signed_in"] is False, "the planted token stays dead")
    g = Browser()
    g.call("POST", "/site-api/auth/guest")
    guest_token = g.jar["crashlab_session"]
    g.signin("founder@acme.example", PASSWORD)
    after = Browser()
    after.jar["crashlab_session"] = guest_token
    check(g.jar["crashlab_session"] != guest_token and after.me()["signed_in"] is False, "sign-in rotates: the guest token before it is dead")

    # CSRF and origins on the site.
    t = Browser()
    t.signin("founder@acme.example", PASSWORD)
    t.me()
    check(t.call("POST", "/site-api/auth/signin", {"email": "a@b.example", "password": "x"}, origin="https://evil.example")[0] == 403, "a foreign Origin is refused")
    check(t.call("POST", "/site-api/auth/signin", {"email": "a@b.example", "password": "x"}, origin=None)[0] == 403, "no Origin is refused")
    check(t.call("POST", "/site-api/auth/signin", {"email": "a@b.example", "password": "x"}, marker=False)[1].get("error") == "csrf_refused", "sign-in without the request header is refused, so a form cannot do it")
    check(t.call("POST", "/site-api/auth/board-token", csrf=False)[1].get("error") == "csrf_refused", "a board token needs the CSRF token")
    check(t.call("POST", "/site-api/auth/board-token", headers={"X-CSRF-Token": "0" * 64})[1].get("error") == "csrf_refused", "a wrong CSRF token is refused")
    check(t.call("POST", "/site-api/auth/signin", {"email": "a"}, headers={"Host": "evil.example"})[0] == 403, "a foreign Host is refused")

    # Guest.
    guest = Browser()
    s, r = guest.call("POST", "/site-api/auth/guest")
    check(s == 200 and r["role"] == "guest" and r["verification_label"] == "Guest, not verified", "a guest is explicit and labelled")
    check(guest.me()["verified"] is False, "a guest is never verified")
    check(guest.call("POST", "/site-api/auth/demo", {"role": "company"})[0] == 404, "the demo accounts do not exist outside demo.sh --recorded")

    # World ID, human mode, MOCK replies. Sign in, sign out, sign in again.
    def enrol(browser, nullifier, session):
        s, ctx = browser.call("POST", "/site-api/auth/world/context")
        return ctx, browser.call("POST", "/site-api/auth/world/verify", {"protocol_version": "4.0", "nonce": ctx["rp_context"]["nonce"], "action": ctx["action"], "session_id": session, "environment": "staging", "responses": [{"identifier": "proof_of_human", "nullifier": nullifier, "proof": ["0x1"]}]})

    def prove(browser, session, sn):
        s, ctx = browser.call("POST", "/site-api/auth/world/context")
        return ctx, browser.call("POST", "/site-api/auth/world/verify", {"protocol_version": "4.0", "nonce": ctx["rp_context"]["nonce"], "session_id": session, "environment": "staging", "responses": [{"identifier": "proof_of_human", "session_nullifier": [sn, "0x1"], "proof": ["0x1"]}]})

    w = Browser()
    _, (s, r) = enrol(w, "0x" + "ab" * 16, "session_human1")
    check(s == 200 and r["role"] == "engineer" and r["verification_label"] == "Verified human" and r["verified"] is True, "MOCK World ID: first scan makes an engineer", str(r))
    first_tester, first_id = r["tester"], r["human_id"]
    check("ab" * 16 not in json.dumps(r), "MOCK World ID: the nullifier stays hidden")
    w.me()
    w.call("POST", "/site-api/auth/logout")
    check(w.me()["signed_in"] is False, "MOCK World ID: sign-out ends the session")
    ctx, (s, r) = prove(w, "session_human1", "0x71")
    check(ctx["mode"] == "prove" and s == 200 and r["tester"] == first_tester, "MOCK World ID: the same browser signs in again to the same account, without a refusal", str(r))
    ctx, (s, r) = prove(w, "session_human1", "0x71")
    check(s == 409 and r["code"] == "replayed", "MOCK World ID: a replayed session proof is refused")
    w2 = Browser()
    _, (s, r) = enrol(w2, "0x" + "ab" * 16, "session_human2")
    check(s == 200 and r["tester"] == first_tester and r["human_id"] == first_id, "MOCK World ID: a new browser reaches the same account, never a second one", str(r))
    count = raw.execute("SELECT COUNT(*) FROM accounts WHERE role='engineer' AND tester=?", (first_tester,)).fetchone()[0]
    check(count == 1, "MOCK World ID: one engineer row for this person")
    thief = Browser()
    thief.jar["crashlab_world"] = "session_human1"
    ctx, (s, r) = prove(thief, "session_other", "0x72")
    check(s == 409 and r["code"] == "wrong_session", "MOCK World ID: a session the browser does not hold is refused")

    # Device mode: honest label, and sign in again.
    def device_scan(browser):
        s, ctx = browser.call("POST", "/site-api/auth/world/context")
        nonce = ctx["rp_context"]["nonce"]
        return browser.call("POST", "/site-api/auth/world/verify", {"protocol_version": "3.0", "nonce": nonce, "action": ctx["action"], "environment": "staging", "responses": [{"identifier": "device", "nullifier": "0x" + "cd" * 16, "merkle_root": "0x1", "proof": "0x1", "signal_hash": W._signal_hash(nonce, ENV)}]})

    dv = Browser(DEVICE_SITE)
    s, r = device_scan(dv)
    check(s == 200 and r["verification_label"] == "Verified device. Not proof of a unique human." and r["credential"] == "device", "MOCK device mode: the label stays honest", str(r))
    device_tester = r["tester"]
    dv.me()
    dv.call("POST", "/site-api/auth/logout")
    s, r = device_scan(dv)
    check(s == 200 and r["tester"] == device_tester, "MOCK device mode: sign-out and sign-in again reach the same account", str(r))
    dv.port = SITE
    check(dv.me()["signed_in"] is False, "a device session counts as signed out on a human-mode server")

    # Wallet.
    w.me()
    bad = [("0x" + "1" * 39, "bad_address"), ("0x" + "0" * 40, "bad_address"), ("hello", "bad_address"), ("0x" + "a" * 64, "looks_like_key"), ("a" * 64, "looks_like_key"), (" ".join(["word"] * 12), "looks_like_key")]
    for value, code in bad:
        s, r = w.call("POST", "/site-api/auth/wallet", {"address": value})
        check(s == 400 and r["error"] == code and value not in json.dumps(r), f"payout refuses {code}: {value[:8]}")
    check(raw.execute("SELECT COUNT(*) FROM accounts WHERE payout IS NOT NULL").fetchone()[0] == 0, "a refused value is not stored")
    addr = "0x" + "12ab" * 10
    s, r = w.call("POST", "/site-api/auth/wallet", {"address": addr})
    check(s == 200 and r["payout"]["masked"] == "0x12ab…12ab" and addr not in json.dumps(w.me()), "a payout address saves, and shows masked")
    check(a.call("POST", "/site-api/auth/wallet", {"address": addr}, csrf=False)[0] in (403,) , "a company has no payout address")

    # Open redirect.
    for bad_next in ("https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "login.html", "home.html/../../x", "http:evil", "home.html?x=<script>", " home.html", "home.html\n"):
        check(A.safe_next(bad_next) == "home.html", f"next refuses {bad_next!r}")
    check(A.safe_next("bounties.html?post=a/c1/slip_distance") == "bounties.html?post=a/c1/slip_distance", "next keeps a page of this site with its query")

    # The board: tokens.
    co = Browser()
    co.signin("founder@acme.example", PASSWORD)
    co2 = Browser()
    co2.signin("second@acme.example", PASSWORD)
    company, other, engineer = co.board_token(), co2.board_token(), w.board_token()
    guest_tok = guest.board_token()

    # The screener. The server grades, and the answers stay on the server.
    made_for_quiz = board("POST", "/api/bounties", {"title": "Quiz", "scenarios": [], "cap": 20, "per_failure": 10, "limits": {}}, company)[1]["id"]
    s, r = board("POST", f"/api/bounties/{made_for_quiz}/submit", {"world": "{}", "seed": 1}, engineer)
    check(s == 403 and r["error"] == "not_screened", "an unscreened engineer cannot submit", str(r))
    check(board("GET", f"/api/bounties/{made_for_quiz}", token=engineer)[0] == 200, "an unscreened engineer can still browse")
    check(co.call("POST", "/site-api/auth/screener/start", headers={"X-CSRF-Token": co.me()["csrf"]})[0] == 403, "the quiz is for engineers")
    check(w.call("POST", "/site-api/auth/screener/start", csrf=False)[1].get("error") == "csrf_refused", "the quiz needs the CSRF token")
    s, quiz = w.call("POST", "/site-api/auth/screener/start")
    ids = [q["id"] for q in quiz["questions"]]
    text = json.dumps(quiz)
    check(len(ids) == 6 == len(set(ids)) and len(Q.BANK) >= 20, "six different questions from a bank of 20")
    check("answer" not in text and "right" not in {k for q in quiz["questions"] for k in q} and all(set(c) == {"n", "text"} for q in quiz["questions"] for c in q["choices"]), "the reply holds no answers")
    check(w.call("POST", "/site-api/auth/screener/start")[1]["questions"] == quiz["questions"], "asking again gives the same questions, so nobody fishes for easy ones")
    right = {q: Q.BY_ID[q][3] for q in ids}
    check(w.call("POST", "/site-api/auth/screener/grade", {"answers": {ids[0]: 0}})[0] == 400, "a partial answer sheet is refused")
    wrong = {**right, ids[0]: 3, ids[1]: 3}
    s, r = w.call("POST", "/site-api/auth/screener/grade", {"answers": wrong})
    check(s == 200 and r["passed"] is False and r["score"] == 4 and ids[0] not in json.dumps(r), "4 of 6 fails, in plain words, naming no question", str(r))
    check(w.call("POST", "/site-api/auth/screener/grade", {"answers": right})[0] == 400, "a graded sheet cannot be sent again")
    check(w.call("POST", "/site-api/auth/screener/start")[1].get("error") == "screener_wait", "a fail waits")
    with __import__("contextlib").closing(A._open(DB)) as d:
        d.execute("UPDATE screen SET retry_at=0")
    s, again = w.call("POST", "/site-api/auth/screener/start")
    ids = [q["id"] for q in again["questions"]]
    answers = {q: Q.BY_ID[q][3] for q in ids}
    answers[ids[0]] = 3
    s, r = w.call("POST", "/site-api/auth/screener/grade", {"answers": answers})
    check(r["passed"] is True and r["score"] == 5 and "not proof of skill" in r["words"], "5 of 6 passes, with an honest label", str(r))
    check(w.me()["screened"] is True, "the account says screened")
    w2.me()
    check(w2.me()["screened"] is True, "the same person in another browser is screened too")

    # Simulation is for a company or a guest, on the run server too.
    for path, payload in (("/api/sessions", {}), ("/api/sessions/nope/message", {"text": "x"})):
        status = {who: board("POST", path, payload, tok, port=RUN)[0] for who, tok in (("engineer", engineer), ("company", company), ("guest", guest_tok))}
        status["nobody"] = board("POST", path, payload, port=RUN)[0]
        status["forged"] = board("POST", path, payload, company[:-4] + "0000", port=RUN)[0]
        check(status["nobody"] == 401 and status["forged"] == 401 and status["engineer"] == 403 and status["company"] not in (401, 403) and status["guest"] not in (401, 403), f"run server {path}: company and guest pass, engineer and nobody refused", str(status))
    e_site = w.call("GET", "/site-api/data")[0]
    check(e_site == 403 and co.call("GET", "/site-api/recent")[0] == 200, "stored runs are for a company, and refused to an engineer", str(e_site))
    body = {"title": "Test", "scenarios": [], "cap": 20, "per_failure": 10, "limits": {}}
    fp = "0x" + "0" * 64
    s, made = board("POST", "/api/bounties", {**body, "company": "Typed name"}, company)
    check(s == 400, "the board refuses a typed company", str(made))
    s, made = board("POST", "/api/bounties", body, company)
    check(s == 201 and made["company"] == "Acme Robots (email not verified)" and made["mine"] is True, "a company posts, under its own name, labelled", str(made))
    bid = made["id"]
    fix_id = 900
    (ROOT / str(fix_id)).mkdir()
    (ROOT / str(fix_id) / "pack.json").write_text("{}")
    (ROOT / str(fix_id) / "owner.json").write_text(json.dumps({"account": A.session_of(co.jar["crashlab_session"])["account_id"]}))
    posts = {"company": [("/api/bounties", body), ("/api/bounties/fix", {"session": "x", "campaign": "c1", "group": "stalled", "title": "T", "pay": 1}), ("/api/budget/stop", {})],
             "engineer": [(f"/api/bounties/{bid}/submit", {"world": "{}", "seed": 1}), (f"/api/bounties/{fix_id}/fix", {"source": "x"}), (f"/api/bounties/{bid}/failures/{fp}/claim", {"secret": "s"}), (f"/api/bounties/{fix_id}/fixes/1/claim", {"secret": "s"})],
             "owner": [(f"/api/bounties/{bid}/failures/{fp}/finalize", {}), (f"/api/bounties/{bid}/failures/{fp}/reject", {}), (f"/api/bounties/{fix_id}/fixes/1/finalize", {}), (f"/api/bounties/{fix_id}/fixes/1/reject", {}), (f"/api/bounties/{fix_id}/fixes/1/approve", {}), (f"/api/bounties/{fix_id}/fixes/1/decline", {})],
             "any": [(f"/api/bounties/{bid}/submissions/1/replay", {})]}
    tokens = {"company": company, "engineer": engineer, "guest": guest_tok}
    for kind, routes in posts.items():
        for path, payload in routes:
            status = {who: board("POST", path, payload, tok)[0] for who, tok in tokens.items()}
            status["nobody"] = board("POST", path, payload)[0]
            status["forged"] = board("POST", path, payload, company[:-4] + "0000")[0]
            status["bad origin"] = board("POST", path, payload, company, origin="https://evil.example")[0]
            status["other company"] = board("POST", path, payload, other)[0]
            check(status["nobody"] == 401 and status["forged"] == 401 and status["guest"] == 403 and status["bad origin"] == 403, f"{path}: nobody, forged and guest are refused", str(status))
            if kind == "company":
                check(status["engineer"] == 403 and status["company"] not in (401, 403), f"{path}: only a company", str(status))
            elif kind == "engineer":
                check(status["company"] == 403 and status["engineer"] not in (401, 403), f"{path}: only an engineer", str(status))
            elif kind == "owner":
                check(status["engineer"] == 403 and status["other company"] == 403 and status["company"] not in (401, 403), f"{path}: only this bounty's company", str(status))
            else:
                check(status["company"] not in (401, 403) and status["engineer"] not in (401, 403), f"{path}: a company or an engineer", str(status))
    s, r = board("POST", "/api/bounties", body, guest_tok)
    check(r.get("error") == "guest_refused" and "guest" in r["reason"].lower(), "a guest gets a plain refusal", str(r))
    s, r = board("POST", f"/api/bounties/{bid}/submit", {"tester": "typed", "world": "{}", "seed": 1}, engineer)
    check(s == 400, "the board refuses a typed tester name", str(r))
    shutil.rmtree(ROOT / str(fix_id))
    check(board("GET", f"/api/bounties/{bid}", token=company)[1].get("mine") is True and board("GET", f"/api/bounties/{bid}", token=other)[1].get("mine") is False, "a read says if the bounty is yours")

    # Board token life.
    outdated = A.board_token(co.jar["crashlab_session"], DB, now=time.time() - A.BOARD_TOKEN_S - 1)
    check(board("POST", "/api/budget/stop", {}, outdated)[0] == 401, "an old board token is refused")
    other_key = company.split(".")[0] + "." + "0" * 64
    check(board("POST", "/api/budget/stop", {}, other_key)[0] == 401, "a board token with a forged signature is refused")
    co.me()
    co.call("POST", "/site-api/auth/logout")
    check(board("POST", "/api/bounties", body, company)[0] == 401, "after sign-out the board token dies at once")
    check(co.call("POST", "/site-api/auth/board-token")[0] == 401, "a signed-out browser gets no board token")

    # Nothing secret in the logs.
    LOG.flush()
    log = (tmp / "servers.log").read_bytes()
    check(PASSWORD.encode() not in log and b"wrong guess" not in log, "no password in the server logs")
    check(PASSWORD.encode() not in DB.read_bytes(), "no password in the store")
finally:
    for p in procs:
        p.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
print(f"{failed} FAILED" if failed else "ALL PASS (World ID replies are mock, no real scan, no email sent)")
sys.exit(1 if failed else 0)
