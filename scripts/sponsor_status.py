#!/usr/bin/env python3
"""Prints what is on and off for Arc, 0G and World ID: python3 scripts/sponsor_status.py [--env FILE]. It reads names, file modes and arc.json. It opens no network connection and prints no secret's value."""
import argparse
import json
import os
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROLES = ("company", "resolver", "arbiter", "tester")
WORLD = ("WORLD_APP_ID", "WORLD_ACTION", "WORLD_RP_ID", "WORLD_RP_SIGNING_KEY", "WORLD_ENVIRONMENT")


def read_env(path):
    """Real environment values win, as they do in site_data.py."""
    values = {}
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.removeprefix("export ").strip()] = value.strip().strip("\"'")
    return {**values, **{k: v for k, v in os.environ.items() if v}}


def line(name, on, detail):
    print(f"{'ON ' if on else 'OFF'} {name}: {detail}")


def arc(env, root):
    problems = []
    if not env.get("ARC_RPC_URL"):
        problems.append("ARC_RPC_URL not set")
    folder = Path(env["ARC_WALLET_DIR"]).expanduser() if env.get("ARC_WALLET_DIR") else None
    if not folder:
        problems.append("ARC_WALLET_DIR not set")
    else:
        problems += [f"wallet {role} missing" for role in ROLES if not (folder / role).is_file()]
        password = folder / "password"
        if not password.is_file():
            problems.append("password file missing")
        elif stat.S_IMODE(password.stat().st_mode) & 0o077:
            problems.append("password file is open to others")
        if folder.resolve().is_relative_to(REPO):
            problems.append("wallets sit inside the repo")
    if not env.get("ARC_CAP_USDC", "").isdigit():
        problems.append("ARC_CAP_USDC not set")
    saved = Path(root) / "arc.json"
    if not saved.is_file():
        problems.append("contract not deployed")
    if problems:
        return line("Arc testnet payouts", False, "; ".join(problems) + ". The local ledger is the source.")
    record = json.loads(saved.read_text())
    line("Arc testnet payouts", True, f"contract {record['contract']}, cap {env['ARC_CAP_USDC']} test USDC. {record['label']} It runs only while arc_mirror.py serve runs.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(REPO / ".env"))
    ap.add_argument("--root", default=str(REPO / "policy" / "runs" / "board"))
    a = ap.parse_args()
    env = read_env(a.env)
    arc(env, a.root)
    missing = [k for k in ("ZG_API_KEY", "ZG_MODEL") if not env.get(k)]
    if env.get("CRASHLAB_LLM") != "0g":
        line("0G AI", False, "CRASHLAB_LLM is not 0g. Claude answers.")
    elif missing:
        line("0G AI", False, f"{', '.join(missing)} not set. Each AI step fails with a plain line. It does not use Claude silently.")
    else:
        fallback = "Claude answers if 0G fails, and the chat says so" if env.get("ZG_FALLBACK_CLAUDE") == "1" else "no fallback: if 0G fails, the step fails"
        line("0G AI", True, f"model {env['ZG_MODEL']}, {fallback}. Fixes and generated models still use Claude.")
    sdk = (REPO / "policy" / "sponsors" / "zg" / "node_modules" / "@0gfoundation").is_dir()
    line("0G own signature check", sdk, "SDK installed." if sdk else "SDK not installed: run npm --prefix policy/sponsors/zg ci.")
    wallet = [k for k in ("ZG_WALLET_KEYSTORE", "ZG_WALLET_PASSWORD_FILE") if not env.get(k)]
    line("0G Storage testnet", not wallet and sdk, "keystore named." if not wallet else f"{', '.join(wallet)} not set.")
    world = [k for k in WORLD if not env.get(k)]
    line("World ID login", not world, "all five names set." if not world else f"{', '.join(world)} not set.")


if __name__ == "__main__":
    main()
