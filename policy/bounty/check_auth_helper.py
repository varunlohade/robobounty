"""For the board's checks only. A throwaway account store and real signed board tokens, so a check talks to the server the way a signed-in browser does.
A body's "tester" names which engineer sends it, and the field goes no further. Any other POST comes from one test company."""
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
os.environ["CRASHLAB_AUTH_DB"] = str(Path(tempfile.mkdtemp(prefix="check-board-auth-")) / "auth.sqlite")
import board_store as B
import site_auth as A

COMPANY = A.sign_up("check@company.example", "correct horse battery", "Check company", "check")
_sessions = {}


def _token(key, make):
    if key not in _sessions:
        _sessions[key] = make()
    return A.board_token(_sessions[key])


def company_token():
    return _token("company", lambda: A.new_session(COMPANY, "company"))


def engineer_token(name):
    key = B.tester_key(name)
    def make():
        account = A.engineer_for_world(f"mock-{key}", "device", tester=key)
        A.mark_screened(account)
        return A.new_session(account, "engineer")
    return _token(key, make)


def signed(body):
    """Returns (the body to send, the Authorization header's value). A body that is not sound goes on unchanged from an engineer, so the check still sees its refusal."""
    if isinstance(body, str):
        return body, f"Bearer {engineer_token('check engineer')}"
    if isinstance(body, dict) and "tester" in body:
        if not (isinstance(body["tester"], str) and re.fullmatch(B.TESTER, " ".join(body["tester"].lower().split()))):
            return body, f"Bearer {engineer_token('check engineer')}"
        rest = {k: v for k, v in body.items() if k != "tester"}
        return rest, f"Bearer {engineer_token(body['tester'])}"
    if isinstance(body, dict) and "company" in body:
        body = {k: v for k, v in body.items() if k != "company"}
    return body, f"Bearer {company_token()}"


def own_all(root):
    """Bounties a check made directly, with no session, belong to the test company."""
    for folder in Path(root).iterdir():
        if folder.name.isdigit() and not (folder / "owner.json").exists():
            B.set_owner(int(folder.name), COMPANY, root)
