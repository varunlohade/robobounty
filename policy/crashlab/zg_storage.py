"""Puts a campaign's or a bounty's public evidence on 0G Storage testnet, and proves it comes back: zg_storage.py campaign|demo|bounty|recheck.

The bundle is one JSON file: public world files, results, judge reasons and hashes. Held-back worlds, and every world a bounty from this campaign keeps hidden, stay out, so an upload cannot leak them.
Keys: only policy/sponsors/zg/storage.mjs opens the wallet, from a keystore file. Results stay simulated: a root hash shows that a file exists, not that a robot would behave this way.
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
sys.path.insert(0, str(POLICY / "bounty"))
import board_fix as X
import board_store as B

HELPER = POLICY / "sponsors" / "zg" / "storage.mjs"
FILE = "zg_evidence.json"
SCHEMA = "crashlab.evidence.v1"
LABEL_REAL = "0G Storage testnet."
LABEL_MOCK = "Local stand-in for 0G Storage. Not on 0G."
TX_LINK = "https://chainscan-galileo.0g.ai/tx/"
UPLOAD_TIMEOUT_S = 300
DOWNLOAD_TIMEOUT_S = 120
RECHECK_TRIES = 5
RECHECK_WAIT_S = 10
HELPER_ENV = ("HOME", "PATH", "LANG", "TMPDIR", "ZG_STORAGE_RPC", "ZG_STORAGE_INDEXER", "ZG_STORAGE_SDK_MODULE", "ZG_ETHERS_MODULE", "ZG_MOCK_STORE", "ZG_MOCK_STORAGE", "ZG_MOCK_CHAIN", "ZG_MOCK_BALANCE")
WALLET_ENV = ("ZG_WALLET_KEYSTORE", "ZG_WALLET_PASSWORD_FILE")
ERROR_WORDS = {"sdk_not_installed": "The 0G SDK is not installed. Run npm --prefix policy/sponsors/zg ci.", "wrong_network": "Refused: this RPC is not 0G Galileo testnet. Nothing was uploaded.", "bad_keystore": "The 0G keystore or its password did not open. Nothing was uploaded.",
               "empty_balance": "The 0G wallet holds no test tokens. Get some at faucet.0g.ai. Nothing was uploaded.", "hash_failed": "The file's root hash could not be built. Nothing was uploaded.", "upload_failed": "The upload to 0G Storage failed. No root hash is shown.",
               "root_mismatch": "0G returned another root hash than this file's. No root hash is shown.", "download_failed": "The download from 0G Storage failed.", "timeout": "0G Storage did not answer in time. No root hash is shown.", "helper_failed": "The 0G helper stopped with an error. No root hash is shown."}


class StorageError(Exception):
    """A plain message. It never holds a key or SDK text."""


def _helper(request, timeout, wallet=False):
    keep = HELPER_ENV + (WALLET_ENV if wallet else ())
    env = {k: os.environ[k] for k in keep if k in os.environ}
    try:
        done = subprocess.run(["node", str(HELPER)], input=json.dumps(request).encode(), capture_output=True, timeout=timeout, env=env)
        reply = json.loads(done.stdout)
    except subprocess.TimeoutExpired:
        raise StorageError(ERROR_WORDS["timeout"]) from None
    except (OSError, ValueError):
        raise StorageError(ERROR_WORDS["helper_failed"]) from None
    if reply.get("error"):
        raise StorageError(ERROR_WORDS.get(reply["error"], ERROR_WORDS["helper_failed"]))
    return reply


def _read_maybe_gz(folder, name):
    plain, packed = folder / name, folder / f"{name}.gz"
    if plain.is_file():
        return json.loads(plain.read_text())
    with gzip.open(packed, "rt") as f:
        return json.load(f)


def hidden_worlds(session, cid, root):
    """The index of each world that a bounty from this campaign keeps hidden. Every hidden list counts, for an open bounty or any other."""
    hidden = set()
    for path in Path(root).glob("*/hidden.json"):
        saved = json.loads(path.read_text())
        if saved["source"][:2] == [session, cid]:
            for name in ("held_back", "passed_before", "other_failed"):
                hidden.update(w["index"] for w in saved[name])
    return hidden


def campaign_bundle(folder, session=None, root=B.ROOT):
    folder = Path(folder)
    plan = _read_maybe_gz(folder, "scenarios.json")
    if (folder / "grid.json").is_file():
        rows = json.loads((folder / "grid.json").read_text())["rows"]
        pack = json.loads((folder / "grid.json").read_text())["pack"]
    else:
        rows, pack = _read_maybe_gz(folder, "timeline.json")[-1]["rows"], folder.name
    rows = {r["index"]: r for r in rows} if rows and "index" in rows[0] else dict(enumerate(rows))
    hidden = hidden_worlds(session, folder.name, root) if session else set()
    public = []
    for w in plan["worlds"]:
        if w.get("held_back") or w["index"] in hidden:
            continue
        stored = X.F.latest_run5(folder, w["index"]) / "job_result.json"
        row = rows[w["index"]]
        public.append({**X._public_world(w, {"verdict": row.get("verdict"), "status": row["status"], "verdict_reason": row.get("verdict_reason")}, json.loads(stored.read_text()) if stored.is_file() else {}), "physics_sha256": w.get("hash")})
    return {"schema": SCHEMA, "kind": "campaign", "pack": pack, "sim_label": X.SIM_LABEL, "worlds": public, "withheld_worlds": len(plan["worlds"]) - len(public), "frozen_sha256": X.frozen_shas(pack) if pack in X.FROZEN_FILES else {}}


def bounty_bundle(bounty_id, root=B.ROOT):
    """Built only from what the public routes already serve."""
    folder = X.folder_of(bounty_id, root)
    info = json.loads((folder / "pack.json").read_text())
    money = json.loads((folder / "ledger.json").read_text())["bounty"]
    return {"schema": SCHEMA, "kind": "bounty", "bounty": bounty_id, "pack": info["pack"], "sim_label": X.SIM_LABEL, "title": info["title"], "group": info["group"], "worlds": info["public_worlds"], "withheld_worlds": sum(info["hidden_counts"].values()),
            "frozen_sha256": info["frozen"], "controller_sha256": info["controller"]["sha256"], "spec_hash": money["spec_hash"], "fixes": X.list_fixes(bounty_id, root)}


def encoded(bundle):
    return json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def recheck(root_hash, sha256):
    """Downloads the file with its Merkle proof on, and compares the hash of what came back. Returns True or False. It has no other way to say yes."""
    folder = Path(tempfile.mkdtemp(prefix="zg-recheck-"))
    try:
        _helper({"op": "download", "root_hash": root_hash, "out": str(folder / "back.json")}, DOWNLOAD_TIMEOUT_S)
        return hashlib.sha256((folder / "back.json").read_bytes()).hexdigest() == sha256
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def upload(bundle, target):
    """Uploads, records the root hash in target/zg_evidence.json, then rechecks. A failed recheck leaves the record saying so. The label needs the real SDK."""
    data = encoded(bundle)
    sha256 = hashlib.sha256(data).hexdigest()
    folder = Path(tempfile.mkdtemp(prefix="zg-upload-"))
    try:
        (folder / "evidence.json").write_bytes(data)
        reply = _helper({"op": "upload", "path": str(folder / "evidence.json")}, UPLOAD_TIMEOUT_S, wallet=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    real = not os.environ.get("ZG_STORAGE_SDK_MODULE")
    record = {"label": LABEL_REAL if real else LABEL_MOCK, "root_hash": reply["root_hash"], "tx": reply["tx"], "tx_link": TX_LINK + reply["tx"] if real else None, "sha256": sha256, "bytes": len(data), "at": time.time(), "rechecked": False, "public_worlds": len(bundle["worlds"]), "withheld_worlds": bundle["withheld_worlds"]}
    B.write_json(Path(target) / FILE, record)
    for attempt in range(RECHECK_TRIES):
        try:
            record["rechecked"] = recheck(reply["root_hash"], sha256)
            if not record["rechecked"]:
                record["message"] = "The file that came back has another hash."
            break
        except StorageError as e:
            record["message"] = f"Not checked yet: {e}"
            time.sleep(RECHECK_WAIT_S if attempt + 1 < RECHECK_TRIES else 0)
    if record["rechecked"]:
        record.pop("message", None)
    B.write_json(Path(target) / FILE, record)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("campaign", "demo", "bounty", "recheck"))
    ap.add_argument("--session")
    ap.add_argument("--campaign")
    ap.add_argument("--pack")
    ap.add_argument("--id", type=int)
    ap.add_argument("--root", default=str(B.ROOT))
    ap.add_argument("--runs", default=str(X.SERVER_RUNS))
    a = ap.parse_args()
    try:
        if a.command == "campaign":
            target = X._campaign(a.session, a.campaign, a.runs)
            bundle = campaign_bundle(target, a.session, a.root)
        elif a.command == "demo":
            target = POLICY / "runs" / "demo" / a.pack
            bundle = campaign_bundle(target)
        else:
            target = X.folder_of(a.id, a.root)
            if a.command == "recheck":
                saved = json.loads((target / FILE).read_text())
                same = recheck(saved["root_hash"], saved["sha256"])
                B.write_json(target / FILE, {**saved, "rechecked": same})
                print("The file came back and its hash matches." if same else "The file came back with another hash.")
                return 0 if same else 1
            bundle = bounty_bundle(a.id, a.root)
        record = upload(bundle, target)
    except (StorageError, B.BoardError) as e:
        print(e)
        return 1
    print(json.dumps(record, indent=1))
    return 0 if record["rechecked"] else 1


if __name__ == "__main__":
    sys.exit(main())
