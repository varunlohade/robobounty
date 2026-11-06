"""0G call receipts: one JSON line per LLM call, each holding the hash of the line before. They record what happened, and threat model risk 16 limits what they mean.

What a checked receipt shows: the provider's TEE signer signed this response text.
What no receipt here shows: that the signature covers our prompt, that the app used the answer well, or that the TEE has no flaws.
"""
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

CLAIM_LIMITS = "A checked receipt shows that the provider's TEE signer signed the reply text. It does not show that the signature covers the prompt, that the app used the answer, or that the TEE has no flaws. Looking up a past call by request ID: unknown."
GENESIS = "0" * 64


def default_path():
    return Path(__file__).resolve().parent.parent / "runs" / "llm_receipts" / "receipts.jsonl"


def path_from_env():
    return Path(os.environ.get("CRASHLAB_LLM_RECEIPTS") or default_path())


def sha(text):
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode()).hexdigest()


def append(row, path=None):
    path = Path(path) if path else path_from_env()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        lines = f.read().splitlines()
        previous = json.loads(lines[-1])["hash"] if lines else GENESIS
        body = {"at": round(time.time(), 3), **row, "previous": previous}
        body["hash"] = sha(json.dumps(body, sort_keys=True, separators=(",", ":")))
        f.write(json.dumps(body, sort_keys=True) + "\n")
    return body


def summary(path):
    """Counts from the file. Only process_response true counts as checked. tee_verified is the Router's own word, and it never counts."""
    path = Path(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    if not rows:
        return None
    zg = [r for r in rows if r.get("backend") == "0g"]
    other = sorted({r.get("backend", "unknown") for r in rows} - {"0g"})
    refused = [r.get("process_response") is False or r.get("tee_verified") is False for r in zg]
    failed = sum(refused)
    checked = sum(r.get("process_response") is True and not bad for r, bad in zip(zg, refused))
    out = {"calls": len(rows), "zg_calls": len(zg), "other_backends": other, "checked": checked, "failed": failed, "not_checked": len(zg) - checked - failed,
           "request_ids": [r["request_id"] for r in zg if r.get("request_id")], "process_response": [r.get("process_response") for r in zg],
           "commit": rows[-1]["hash"], "limits": CLAIM_LIMITS, "file": str(path)}
    used = ", ".join(([f"0G {len(zg)}"] if zg else []) + [f"{name} {sum(r.get('backend') == name for r in rows)}" for name in other])
    line = f"LLM calls used: {used}."
    if zg:
        line += f" processResponse true on {checked}, false on {failed}, no check on {out['not_checked']}."
        if out["request_ids"]:
            line += f" Last request {out['request_ids'][-1][:18]}."
    out["line"] = line
    return out
