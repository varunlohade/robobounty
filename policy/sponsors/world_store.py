"""Verified World ID humans, in SQLite. UNIQUE(nullifier, action) stops a replayed proof. UNIQUE(wallet, action) ties one wallet to one human.

SQLite NUMERIC would round a 256-bit nullifier to a float, so the column is TEXT holding the exact decimal form: the same value as the docs' NUMERIC(78,0).
"""
import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS verifications (
  nullifier TEXT NOT NULL, action TEXT NOT NULL, wallet TEXT NOT NULL, environment TEXT NOT NULL, verified_at REAL NOT NULL,
  UNIQUE (nullifier, action), UNIQUE (wallet, action));
CREATE TABLE IF NOT EXISTS submissions (
  nullifier TEXT NOT NULL, action TEXT NOT NULL, bounty_id INTEGER NOT NULL, submission_hash TEXT NOT NULL, at REAL NOT NULL,
  UNIQUE (nullifier, action, bounty_id, submission_hash));
CREATE TABLE IF NOT EXISTS nonces (
  nonce TEXT PRIMARY KEY, wallet TEXT NOT NULL, action TEXT NOT NULL, expires_at INTEGER NOT NULL);
"""


class Replayed(Exception):
    """This human already verified this action, or this wallet already belongs to a human."""


def _open(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.executescript(SCHEMA)
    return db


def nullifier_decimal(value):
    """The docs: nullifiers come as 0x-prefixed hex for a 256-bit integer. Raises ValueError on anything else."""
    if not isinstance(value, str) or not value.startswith("0x") or len(value) > 66:
        raise ValueError("bad nullifier")
    number = int(value, 16)
    if number < 0 or number >= 2**256:
        raise ValueError("bad nullifier")
    return str(number)


def add_nonce(path, nonce, wallet, action, expires_at):
    with closing(_open(path)) as db:
        db.execute("INSERT OR REPLACE INTO nonces VALUES (?,?,?,?)", (nonce, wallet, action, expires_at))


def take_nonce(path, nonce, wallet, action, now=None):
    """One use only. A nonce works only for the wallet and action it was signed for, and only until it expires."""
    now = time.time() if now is None else now
    with closing(_open(path)) as db:
        cur = db.execute("DELETE FROM nonces WHERE nonce=? AND wallet=? AND action=? AND expires_at>=?", (nonce, wallet, action, now))
        return cur.rowcount == 1


def seen(path, nullifier, action):
    with closing(_open(path)) as db:
        return db.execute("SELECT 1 FROM verifications WHERE nullifier=? AND action=?", (nullifier, action)).fetchone() is not None


def add_verification(path, nullifier, action, wallet, environment, now=None):
    with closing(_open(path)) as db:
        try:
            db.execute("INSERT INTO verifications VALUES (?,?,?,?,?)", (nullifier, action, wallet.lower(), environment, time.time() if now is None else now))
        except sqlite3.IntegrityError:
            raise Replayed from None


def _row_of(db, wallet, action):
    return db.execute("SELECT nullifier FROM verifications WHERE wallet=? AND action=?", (wallet.lower(), action)).fetchone()


def is_verified(path, wallet, action):
    with closing(_open(path)) as db:
        return _row_of(db, wallet, action) is not None


def human_id(nullifier, action):
    """A verdict names the human by this hash, not by the nullifier."""
    return "0x" + hashlib.sha256(f"crashlab.human.v1|{action}|{nullifier}".encode()).hexdigest()


def human_of(path, wallet, action, bounty_id):
    """Returns (human id, submissions used in this bounty), or None for a wallet with no verified human."""
    with closing(_open(path)) as db:
        row = _row_of(db, wallet, action)
        if row is None:
            return None
        used = db.execute("SELECT COUNT(*) FROM submissions WHERE nullifier=? AND action=? AND bounty_id=?", (row[0], action, bounty_id)).fetchone()[0]
        return human_id(row[0], action), used


def reserve_submission(path, wallet, action, bounty_id, submission_hash, cap, now=None):
    """Counts one submission in one transaction. Returns False at the cap. The same submission counts once."""
    with closing(_open(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = _row_of(db, wallet, action)
            if row is None:
                return False
            if db.execute("SELECT 1 FROM submissions WHERE nullifier=? AND action=? AND bounty_id=? AND submission_hash=?", (row[0], action, bounty_id, submission_hash)).fetchone():
                return True
            used = db.execute("SELECT COUNT(*) FROM submissions WHERE nullifier=? AND action=? AND bounty_id=?", (row[0], action, bounty_id)).fetchone()[0]
            if used >= cap:
                return False
            db.execute("INSERT INTO submissions VALUES (?,?,?,?,?)", (row[0], action, bounty_id, submission_hash, time.time() if now is None else now))
            return True
        finally:
            db.execute("COMMIT")
