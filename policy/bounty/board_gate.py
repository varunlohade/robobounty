"""Runs one board submission through gate.py in its own process, and proposes on the local ledger when the gate accepts.

board_gate.py --bounty N --tester NAME --world FILE [--seed N] [--root DIR]. It sends nothing on chain.
World ID is not connected: the human id comes from the tester's name, and the count comes from this board.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_store as B
import gate as G

GATE = HERE / "gate.py"
GATE_TIMEOUT_S = 3600  # gate.py limits each sim batch on its own. This limit is a backstop.
EXPORT_TIMEOUT_S = 120
EXPORT = HERE.parent / "app_export.py"
VERDICT_KEYS = ("accepted", "code", "reason", "stage", "repeat", "fingerprint", "result_hash", "reference_check", "hardware_check", "duplicate_of", "human_cap", "limits_of_this_result", "not_checked", "claim_seed")
_live = set()
_live_lock = threading.Lock()


def stop_running():
    """Stops any gate this process started, with its pool. board_server.py calls this on shutdown."""
    with _live_lock:
        for p in _live:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def _process(argv, log_path, timeout=GATE_TIMEOUT_S):
    with open(log_path, "ab") as log:
        p = subprocess.Popen(["nice", "-n", "5", *argv], start_new_session=True, stdout=log, stderr=subprocess.STDOUT)
    with _live_lock:
        _live.add(p)
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        return None
    finally:
        with _live_lock:
            _live.discard(p)


def view_of(verdict):
    """What a person needs from the verdict. Local paths stay in verdict.json."""
    runs = verdict.get("runs") or []
    return {**{k: verdict.get(k) for k in VERDICT_KEYS}, "runs": len(runs), "check_passed": verdict.get("stage") in ("sim", "done"), "recorded_run_saved": bool(verdict.get("recorded_run"))}


def run(row, world_text, root=B.ROOT):
    """Runs one reserved submission. The gate lock keeps one gate at a time, across every process that uses this root."""
    root = Path(root)
    bounty_id, n = row["bounty_id"], row["n"]
    folder = root / str(bounty_id)
    sub = folder / "submissions" / str(n)
    t0 = time.time()
    with B.locked(root / ".gate.lock"):
        row = {**row, "state": "running", "started_at": t0}
        B.save_submission(row, root)
        (sub / "world.json").write_bytes(world_text.encode("utf-8", "replace"))
        with B.locked(folder / ".lock"):
            book = B.ledger_of(bounty_id, root)
        if book.bounty["available"] < book.bounty["per_failure"]:
            result = {"accepted": False, "code": "cap_reached", "reason": "The cap of this bounty is used up, so no gate ran.", "stage": "ledger", "runs": 0, "check_passed": False}
            row = {**row, "state": "done", "result": result, "wall_s": 0.0}
            B.save_submission(row, root)
            return row
        B.write_json(sub / "paid.json", book.paid_list())
        code = _process([sys.executable, str(GATE), "--world", str(sub / "world.json"), "--spec", str(folder / "spec.json"), "--paid", str(sub / "paid.json"), "--salt-file", str(folder / "salt.hex"),
                              "--submitter", B.tester_address(row["tester"]), "--seed", str(row["seed"]), "--out", str(sub / "gate"),
                              "--human-id", B.human_id(bounty_id, row["tester"]), "--human-used", str(row["used_before"]), "--human-cap", str(B.MAX_PER_TESTER)], sub / "gate.log")
        found = sorted((sub / "gate").glob("*/verdict.json"))
        if code not in (0, 1) or not found:
            result = {"accepted": False, "code": "gate_crashed", "reason": "The gate stopped with an error, so there is no verdict.", "stage": "gate", "runs": 0, "check_passed": False}
            row = {**row, "state": "done", "result": result, "wall_s": round(time.time() - t0, 1)}
            B.save_submission(row, root)
            return row
        verdict = json.loads(found[-1].read_text())
        payout = None
        if verdict["accepted"]:
            with B.locked(folder / ".lock"):
                book = B.ledger_of(bounty_id, root)
                try:
                    book.propose(verdict["submitter"], verdict["fingerprint"], verdict["result_hash"])
                    payout = {**book.failures[verdict["fingerprint"]], "unit": "test units", "ledger_label": B.LEDGER_LABEL}
                except B.ledger_module.LedgerError as e:
                    payout = {"status": "LedgerRefused", "error": str(e), "ledger_label": B.LEDGER_LABEL}
        row = {**row, "state": "done", "result": view_of(verdict), "payout": payout, "wall_s": round(time.time() - t0, 1)}
        B.save_submission(row, root)
        return row


def export_replay(bounty_id, n, root=B.ROOT):
    """Writes the browser replay of the recorded run once, and returns its folder. app_export.py refuses a run that no longer replays exactly."""
    run = B.recorded_run_of(bounty_id, n, root)
    if run is None:
        raise B.BoardError("no_recorded_run", "This submission has no recorded run to replay.")
    sub = Path(root) / str(bounty_id) / "submissions" / str(n)
    out = sub / "replay"
    if not (out / "manifest.json").is_file():
        tmp = sub / "replay.new"
        shutil.rmtree(tmp, ignore_errors=True)
        code = _process([sys.executable, str(EXPORT), "trial", str(run), f"board_{bounty_id}_{n}", f"Bounty {bounty_id}, submission {n}", "--out", str(tmp)], sub / "export.log", EXPORT_TIMEOUT_S)
        if code != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise B.BoardError("replay_refused", "The recorded run did not replay exactly, so there is no replay to show. The sim may have changed since it was recorded.")
        os.rename(tmp, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounty", type=int, required=True)
    ap.add_argument("--tester", required=True)
    ap.add_argument("--world", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--root", default=str(B.ROOT))
    a = ap.parse_args()
    world = Path(a.world).read_bytes()[:G.MAX_SUBMISSION_BYTES + 1].decode("utf-8", "replace")
    secret = B.new_claim_secret()
    print(json.dumps({**B.public_row(run(B.reserve(a.bounty, a.tester, a.seed, a.root, secret=secret), world, a.root)), "claim_secret": secret}, indent=1))


if __name__ == "__main__":
    main()
