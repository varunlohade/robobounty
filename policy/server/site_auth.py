"""Accounts and sessions for the site and the board. SQLite, in policy/runs/site/auth.sqlite, or CRASHLAB_AUTH_DB.

Roles: company (email and password), engineer (World ID), guest (no account). A session is a random token. Only its hash is stored, and only the cookie holds the token.
No email provider exists, so no email is verified. mark_email_verified is the seam for a provider later, and nothing calls it today.
The board runs on its own port, so the site issues it a short signed token. The board also checks that the session is still alive in this store, so a sign-out takes effect at once.
Run: site_auth.py seed-engineer NAME CREDENTIAL prints a session token for a check's engineer, because a check has no World App.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "runs" / "site" / "auth.sqlite"
SESSION_S = 12 * 3600
BOARD_TOKEN_S = 300
SCRYPT = {"n": 2**15, "r": 8, "p": 1}
SCRYPT_MEM = 64 * 1024 * 1024
HASHING = threading.BoundedSemaphore(4)
PASSWORD_MIN, PASSWORD_MAX = 12, 128
EMAIL_TRIES, IP_TRIES, IP_SIGNUPS, IP_GUESTS, IP_WORLD = 8, 40, 20, 60, 60
WINDOW_S = 900
COMMON = {"password1234", "123456789012", "qwertyuiopas", "passwordpassword", "letmeinletmein", "administrator", "iloveyou1234"}
EMAIL = re.compile(r"[a-z0-9._%+-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,24}")
NEXT_PAGE = re.compile(r"[a-z]+\.html(\?[\w\-./=&%]*)?")
EVM = re.compile(r"0x[0-9a-fA-F]{40}")
KEYLIKE = re.compile(r"(0x)?[0-9a-fA-F]{64}")
WRONG = "That email or password is wrong."
SIGNUP_REFUSED = "We could not create this account. Check the details, or sign in."
BUSY = "Too many tries. Wait a few minutes and try again."
VERIFICATION = {"email_not_verified": "Email not verified", "world_human": "Verified human", "world_device": "Verified device. Not proof of a unique human.", "demo": "Demo account. Seeded, not real.", "none": "Guest, not verified"}
DEMO = {"company": {"id": "demo-company", "label": "Demo company", "company": "Tower Services"}, "engineer": {"id": "demo-engineer", "label": "Demo engineer", "tester": "demo engineer"}}
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, role TEXT NOT NULL, label TEXT NOT NULL, email TEXT UNIQUE, password TEXT, company TEXT, world_id TEXT UNIQUE, tester TEXT UNIQUE, credential TEXT, payout TEXT, email_verified_at REAL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token_sha TEXT PRIMARY KEY, account_id TEXT, role TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tries (key TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
CREATE TABLE IF NOT EXISTS screen (account_id TEXT PRIMARY KEY, questions TEXT, started_at REAL, retry_at REAL);
"""
_DUMMY = None


class Refused(Exception):
    def __init__(self, status, code, words):
        super().__init__(code)
        self.status, self.code, self.words = status, code, words


def db_path():
    return Path(os.environ.get("CRASHLAB_AUTH_DB") or DEFAULT_DB)


def _open(db=None):
    path = Path(db or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    d = sqlite3.connect(path, timeout=10, isolation_level=None)
    if fresh:
        os.chmod(path, 0o600)
    d.executescript(SCHEMA)
    if not any(column[1] == "screened_at" for column in d.execute("PRAGMA table_info(accounts)")):
        d.execute("ALTER TABLE accounts ADD COLUMN screened_at REAL")
    if not any(column[1] == "payout_signed_at" for column in d.execute("PRAGMA table_info(accounts)")):
        d.execute("ALTER TABLE accounts ADD COLUMN payout_signed_at REAL")
    return d


def _key(db=None):
    path = Path(db or db_path()).with_suffix(".key")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):
            data = path.read_bytes()
            if data:
                return data
            time.sleep(0.02)
        raise
    data = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return data


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _scrypt(password, salt, n, r, p):
    with HASHING:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MEM, dklen=32)


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${_scrypt(password, salt, **SCRYPT).hex()}"


def password_ok(password, stored):
    _, n, r, p, salt, want = stored.split("$")
    return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p)).hex(), want)


def _dummy():
    global _DUMMY
    _DUMMY = _DUMMY or hash_password(secrets.token_urlsafe(16))
    return _DUMMY


def email_of(value):
    email = value.strip().lower() if isinstance(value, str) else ""
    if len(email) > 254 or not EMAIL.fullmatch(email):
        raise Refused(400, "bad_email", "Enter a valid email address.")
    return email


def check_new_password(password, email):
    if not isinstance(password, str) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise Refused(400, "bad_password", f"Use a password of {PASSWORD_MIN} to {PASSWORD_MAX} characters.")
    low = password.lower()
    if low in COMMON or len(set(low)) < 5 or email.split("@")[0] in low:
        raise Refused(400, "bad_password", "That password is too easy to guess. Use a longer phrase.")


def company_of(value):
    name = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(name) <= 60 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise Refused(400, "bad_company", "Enter a company name of 1 to 60 characters.")
    return name


def _take(d, key, most, now):
    """Counts one try before any slow work, so parallel tries cannot pass the limit. False means the limit is reached."""
    d.execute("BEGIN IMMEDIATE")
    try:
        row = d.execute("SELECT count, since FROM tries WHERE key=?", (key,)).fetchone()
        count = 0 if not row or now - row[1] > WINDOW_S else row[0]
        if count >= most:
            return False
        d.execute("INSERT OR REPLACE INTO tries VALUES (?,?,?)", (key, count + 1, row[1] if row and count else now))
        return True
    finally:
        d.execute("COMMIT")


def limit(kind, ip, most, db=None, now=None):
    """Raises when this address used up its tries of this kind."""
    with closing(_open(db)) as d:
        if not _take(d, f"{kind}:{ip}", most, time.time() if now is None else now):
            raise Refused(429, "too_many_tries", BUSY)


def sign_up(email, password, company, ip, db=None):
    email = email_of(email)
    check_new_password(password, email)
    company = company_of(company)
    limit("signup", ip, IP_SIGNUPS, db)
    stored = hash_password(password)  # Hashed before the look-up, so a taken email costs the same time.
    account = "co_" + secrets.token_hex(12)
    with closing(_open(db)) as d:
        try:
            d.execute("INSERT INTO accounts (id, role, label, email, password, company, created_at) VALUES (?,?,?,?,?,?,?)", (account, "company", company, email, stored, company, time.time()))
        except sqlite3.IntegrityError:
            raise Refused(409, "signup_refused", SIGNUP_REFUSED) from None
    return account


def sign_in(email, password, ip, db=None, now=None):
    """One reply for a wrong password and an unknown email. Each costs one scrypt."""
    now = time.time() if now is None else now
    try:
        email = email_of(email)
    except Refused:
        raise Refused(401, "wrong_login", WRONG) from None
    if not isinstance(password, str) or len(password) > PASSWORD_MAX:
        raise Refused(401, "wrong_login", WRONG)
    with closing(_open(db)) as d:
        by_mail, by_ip = f"email:{_sha(email)}", f"ip:{ip}"
        if not _take(d, by_ip, IP_TRIES, now) or not _take(d, by_mail, EMAIL_TRIES, now):
            raise Refused(429, "too_many_tries", BUSY)
        row = d.execute("SELECT id, password FROM accounts WHERE email=? AND role='company'", (email,)).fetchone()
    good = password_ok(password, row[1] if row else _dummy())
    if not (good and row):
        raise Refused(401, "wrong_login", WRONG)
    with closing(_open(db)) as d:
        d.execute("DELETE FROM tries WHERE key=?", (by_mail,))
        d.execute("UPDATE tries SET count=MAX(count-1,0) WHERE key=?", (by_ip,))
    return row[0]


def mark_email_verified(account_id, db=None):
    """For an email provider, when one exists. Nothing calls it today."""
    with closing(_open(db)) as d:
        d.execute("UPDATE accounts SET email_verified_at=? WHERE id=? AND role='company'", (time.time(), account_id))


def engineer_for_world(world_id, credential, db=None, tester=None):
    """One account per World ID. A returning person gets the same account."""
    with closing(_open(db)) as d:
        row = d.execute("SELECT id FROM accounts WHERE world_id=?", (world_id,)).fetchone()
        if row:
            return row[0]
        hashed = _sha(world_id)
        account = "en_" + hashed[:24]
        label = f"Engineer {world_id[:6]}…{world_id[-4:]}"
        d.execute("INSERT OR IGNORE INTO accounts (id, role, label, world_id, tester, credential, created_at) VALUES (?,?,?,?,?,?,?)", (account, "engineer", label, world_id, tester or f"eng-{hashed[:12]}", credential, time.time()))
    return account


def demo_account(role, db=None):
    """Only scripts/demo.sh --recorded reaches this, on its own throwaway store."""
    seed = DEMO[role]
    with closing(_open(db)) as d:
        d.execute("INSERT OR IGNORE INTO accounts (id, role, label, company, tester, credential, created_at, screened_at) VALUES (?,?,?,?,?,?,?,?)", (seed["id"], role, seed["label"], seed.get("company"), seed.get("tester"), "demo", time.time(), time.time() if role == "engineer" else None))
    return seed["id"]


def new_session(account_id, role, old_token=None, db=None, now=None):
    """A sign-in always makes a new token and ends the one this browser held, so a planted token never becomes a signed-in one."""
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with closing(_open(db)) as d:
        d.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        if old_token:
            d.execute("DELETE FROM sessions WHERE token_sha=?", (_sha(old_token),))
        d.execute("INSERT INTO sessions VALUES (?,?,?,?)", (_sha(token), account_id, role, now + SESSION_S))
    return token


def _session_row(sha, db, now):
    now = time.time() if now is None else now
    with closing(_open(db)) as d:
        row = d.execute("SELECT s.token_sha, s.role, s.expires_at, a.id, a.label, a.company, a.tester, a.credential, a.payout, a.email_verified_at, a.world_id, a.screened_at, a.payout_signed_at, a.email FROM sessions s LEFT JOIN accounts a ON a.id=s.account_id WHERE s.token_sha=? AND s.expires_at>=?", (sha, now)).fetchone()
    if not row:
        return None
    role, credential = row[1], row[7]
    level = "none" if role == "guest" else "demo" if credential == "demo" else "email_not_verified" if role == "company" and not row[9] else "email_verified" if role == "company" else f"world_{credential}"
    return {"sid": row[0], "role": role, "expires_at": row[2], "account_id": row[3], "label": row[4] or "Guest", "company": row[5], "tester": row[6], "credential": credential, "payout": row[8], "verification": level, "world_id": row[10], "screened": bool(row[11]), "payout_signed": bool(row[12]), "email": row[13]}


def session_of(token, db=None, now=None):
    return _session_row(_sha(token), db, now) if token else None


def drop_session(token, db=None):
    if token:
        with closing(_open(db)) as d:
            d.execute("DELETE FROM sessions WHERE token_sha=?", (_sha(token),))


def csrf_of(token, db=None):
    return hmac.new(_key(db), f"csrf|{_sha(token)}".encode(), hashlib.sha256).hexdigest()


def csrf_ok(token, sent, db=None):
    return isinstance(sent, str) and hmac.compare_digest(csrf_of(token, db), sent)


def public(s):
    """What /site-api/auth/me names, to the signed-in person. No token and no full payout address."""
    level = s["verification"]
    return {"signed_in": True, "role": s["role"], "label": s["label"], "verification": level, "verification_label": VERIFICATION.get(level, "Email verified"), "email": s.get("email"), "demo": level == "demo", "tester": s["tester"], "screened": s["screened"], "expires_at": s["expires_at"],
            "payout": {"set": bool(s["payout"]), "masked": mask(s["payout"]) if s["payout"] else None, "signed": bool(s.get("payout_signed"))}}


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def board_token(token, db=None, now=None):
    now = time.time() if now is None else now
    body = _b64(json.dumps({"sid": _sha(token), "exp": now + BOARD_TOKEN_S, "aud": "board"}).encode())
    return f"{body}.{hmac.new(_key(db), body.encode(), hashlib.sha256).hexdigest()}"


def board_session(value, db=None, now=None):
    """The session behind a board token, or None for a forged, old or signed-out one."""
    now = time.time() if now is None else now
    if not isinstance(value, str) or value.count(".") != 1:
        return None
    body, sign = value.split(".")
    if not hmac.compare_digest(hmac.new(_key(db), body.encode(), hashlib.sha256).hexdigest(), sign):
        return None
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if claims.get("aud") != "board" or claims.get("exp", 0) < now:
        return None
    return _session_row(claims.get("sid"), db, now)


def company_name(s):
    return f"{s['company']} ({'demo' if s['verification'] == 'demo' else 'email not verified' if s['verification'] == 'email_not_verified' else 'email verified'})"


def safe_next(value):
    """A page of this site, by a plain name. Everything else goes home."""
    return value if isinstance(value, str) and NEXT_PAGE.fullmatch(value) and not value.startswith("login.html") else "home.html"


def mask(address):
    return f"{address[:6]}…{address[-4:]}"


def save_payout(account_id, address, db=None):
    """An address only. A value shaped like a private key is refused and never stored."""
    if address is not None:
        text = address.strip() if isinstance(address, str) else ""
        if KEYLIKE.fullmatch(text) or len(text.split()) >= 12:
            raise Refused(400, "looks_like_key", "That looks like a private key or a recovery phrase. Never share it. Enter a public address.")
        if not EVM.fullmatch(text) or int(text, 16) == 0:
            raise Refused(400, "bad_address", "Enter a public address: 0x and 40 hex characters.")
        address = text
    with closing(_open(db)) as d:
        d.execute("UPDATE accounts SET payout=?, payout_signed_at=NULL WHERE id=? AND role='engineer'", (address, account_id))


def save_signed_wallet(account_id, address, db=None):
    """Only the board's Arc route calls this, after it has checked a signature from this address."""
    with closing(_open(db)) as d:
        d.execute("UPDATE accounts SET payout=?, payout_signed_at=? WHERE id=? AND role='engineer'", (address.lower(), time.time(), account_id))


def mark_screened(account_id, db=None):
    """For a check's seeded engineer. A real engineer gets this from screener.grade."""
    with closing(_open(db)) as d:
        d.execute("UPDATE accounts SET screened_at=? WHERE id=? AND role='engineer'", (time.time(), account_id))


_local_session = None


def local_token(db=None):
    """A guest token for a tool on this machine that drives the run server. Reading this store already takes this machine's files."""
    global _local_session
    _local_session = _local_session or new_session(None, "guest", db=db)
    return board_token(_local_session, db)


def main():
    if sys.argv[1:2] == ["seed-engineer"]:
        name, credential = sys.argv[2:4]
        print(new_session(engineer_for_world(f"mock-{name}", credential, tester=name), "engineer"))
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
