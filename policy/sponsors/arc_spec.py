"""Builds the bounty spec and its secret salt before the contract deploys, because createBounty fixes the spec hash: arc_spec.py --out DIR. Prints the value for ARC_SPEC_HASH.

The spec freezes the sim and gate code. Any later change to them makes the gate reject with code_mismatch, so build the spec last.
"""
import argparse
import json
import secrets
import subprocess
from pathlib import Path

POLICY = Path(__file__).resolve().parent.parent


def build(out, groups=(), schema_limits=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(32)
    (out / "salt.hex").write_text(salt)
    (out / "salt.hex").chmod(0o600)
    request = {"groups": list(groups), "salt": salt, "out": str(out / "spec.json"), "schema_limits": schema_limits}
    done = subprocess.run([str(POLICY / ".venv" / "bin" / "python"), str(POLICY / "server" / "bounty_job.py"), "spec"], input=json.dumps(request).encode(), capture_output=True, check=True)
    return json.loads(done.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--groups", help="A JSON list of scenario groups, each with ranges, to widen the moderate limits.")
    a = ap.parse_args()
    print(build(a.out, json.loads(Path(a.groups).read_text()) if a.groups else ())["spec_hash"])


if __name__ == "__main__":
    main()
