"""What each sponsor integration can do right now, read from env var names. Standard library only. It never returns a secret's value.

Web and LLM processes read this. So do resolver.py and gate.py callers. Nothing here opens a network connection.
"""
import os
import re
from pathlib import Path

WORLD_ACTION = "crashlab-tester-register"  # the one fixed action: threat model risk 12
LOCAL_LEDGER_LABEL = "Local ledger. Not on chain."
WORLD_OFF_LABEL = "World ID not connected"
ARC_TESTNET_CHAIN_ID = 5042002
ARC_USDC = "0x3600000000000000000000000000000000000000"

ZG_NEEDS = ("ZG_API_KEY", "ZG_MODEL")
WORLD_NEEDS = ("WORLD_APP_ID", "WORLD_RP_ID", "WORLD_RP_SIGNING_KEY", "WORLD_ENVIRONMENT")
ARC_NEEDS = ("ARC_RPC_URL", "ARC_BOUNTY_ADDRESS", "ARC_BOUNTY_ID", "ARC_USDC_ADDRESS", "ARC_TESTER_ADDRESS", "ARC_SPEC_DIR")
# These keys sign money movement. They live in .env.resolver and .env.tester, never in web or LLM processes.
SIGNER_VARS = ("ARC_RESOLVER_KEYSTORE", "ARC_RESOLVER_PASSWORD_FILE", "ARC_TESTER_KEYSTORE", "ARC_TESTER_PASSWORD_FILE",
               "ARC_ARBITER_KEYSTORE", "ARC_ARBITER_PASSWORD_FILE", "ARC_COMPANY_KEYSTORE", "ARC_COMPANY_PASSWORD_FILE")
SECRET_VARS = ("ZG_API_KEY", "WORLD_RP_SIGNING_KEY", *SIGNER_VARS)
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
LOOPBACK = re.compile(r"http://(127\.0\.0\.1|localhost)(:[0-9]+)?(/.*)?")


def allowed_url(url):
    """HTTPS, or plain HTTP to this machine for the mocks and anvil."""
    return url.startswith("https://") or bool(LOOPBACK.fullmatch(url))


def is_loopback(url):
    return bool(LOOPBACK.fullmatch(url))


def _missing(names, env):
    return [n for n in names if not env.get(n)]


def child_env(keep=(), env=None):
    """The environment for a child process. No secret passes unless the caller names it."""
    env = os.environ if env is None else env
    return {k: v for k, v in env.items() if k not in SECRET_VARS or k in keep}


def llm_status(env=None):
    """The backend that complete_json will really use. A 0G choice with a missing key falls back to Claude, and the label says so."""
    env = os.environ if env is None else env
    chosen = env.get("CRASHLAB_LLM", "claude")
    if chosen != "0g":
        return {"backend": chosen, "chosen": chosen, "zg_on": False, "label": "claude headless" if chosen == "claude" else chosen}
    missing = _missing(ZG_NEEDS, env)
    if missing:
        return {"backend": "claude", "chosen": "0g", "zg_on": False, "missing": missing, "label": f"claude headless. 0G is off: {', '.join(missing)} not set"}
    url = env.get("ZG_ROUTER_URL", "")
    where = " (local mock)" if url and is_loopback(url) else ""
    return {"backend": "0g", "chosen": "0g", "zg_on": True, "label": f"0G Private Computer{where}, {env['ZG_MODEL']}. fix.py still uses Claude"}


def world_status(env=None):
    env = os.environ if env is None else env
    missing = _missing(WORLD_NEEDS, env)
    if missing:
        return {"on": False, "label": WORLD_OFF_LABEL, "missing": missing}
    if env["WORLD_ENVIRONMENT"] not in ("staging", "production"):
        return {"on": False, "label": WORLD_OFF_LABEL, "missing": ["WORLD_ENVIRONMENT must be staging or production"]}
    url = env.get("WORLD_VERIFY_URL", "")
    if url and not allowed_url(url):
        return {"on": False, "label": WORLD_OFF_LABEL, "missing": ["WORLD_VERIFY_URL must be HTTPS"]}
    mock = bool(url) and is_loopback(url)
    return {"on": True, "mock": mock, "environment": env["WORLD_ENVIRONMENT"], "action": WORLD_ACTION,
            "label": "World ID: local mock, no real proof" if mock else f"World ID on, server check, {env['WORLD_ENVIRONMENT']}"}


def arc_status(env=None):
    """On only if every read value is set and no signing key reached this process. The chain label comes from chain.py, after it reads the chain id."""
    env = os.environ if env is None else env
    signers = [n for n in SIGNER_VARS if env.get(n)]
    if signers:
        return {"on": False, "label": LOCAL_LEDGER_LABEL, "refused": signers, "reason": f"Arc is off: {', '.join(signers)} must not be set in the web process"}
    missing = _missing(ARC_NEEDS, env)
    if missing:
        return {"on": False, "label": LOCAL_LEDGER_LABEL, "missing": missing}
    if not allowed_url(env["ARC_RPC_URL"]):
        return {"on": False, "label": LOCAL_LEDGER_LABEL, "missing": ["ARC_RPC_URL must be HTTPS"]}
    if not all(ADDRESS.fullmatch(env[n]) for n in ("ARC_BOUNTY_ADDRESS", "ARC_USDC_ADDRESS", "ARC_TESTER_ADDRESS")) or not env["ARC_BOUNTY_ID"].isdigit():
        return {"on": False, "label": LOCAL_LEDGER_LABEL, "missing": ["an ARC address or ARC_BOUNTY_ID has a bad format"]}
    if not (Path(env["ARC_SPEC_DIR"]) / "spec.json").is_file():
        return {"on": False, "label": LOCAL_LEDGER_LABEL, "missing": ["spec.json in ARC_SPEC_DIR"]}
    return {"on": True}


def world_db(env=None):
    env = os.environ if env is None else env
    return env.get("WORLD_DB") or str(Path(__file__).resolve().parent.parent / "runs" / "world_id" / "verified.sqlite")
