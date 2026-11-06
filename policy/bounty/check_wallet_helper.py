"""For src/board/tools/check_wallet.mjs only. check_wallet_helper.py ROOT BOUNTY WALLET places one accepted fix row with no gate, so the check can test a company rejection without a second proof. It is labelled in the row and never runs in the app."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix as X
import board_store as B

root, bounty_id, wallet = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
folder = X.folder_of(bounty_id, root)
patched = f"{bounty_id:02x}" * 32
fingerprint = X.fingerprint_of(bounty_id, patched)
with B.locked(folder / ".lock"):
    book = B._ledger(folder)
    book.propose(B.tester_address("demo engineer"), fingerprint, "0x" + "cd" * 32)
    payout = {**book.failures[fingerprint], "fingerprint": fingerprint}
(folder / "fixes" / "1").mkdir(parents=True, exist_ok=True)
result = {"accepted": True, "code": "accepted", "words": "Placed by the check, with no gate.", "stage": "done", "flags": [], "sets": None, "target": [], "patched_sha256": patched}
X.save_fix({"n": 1, "bounty_id": bounty_id, "tester": "demo engineer", "source_sha256": patched, "state": "done", "submitted_at": 0, "result": result, "payout": payout, "used_before": 0, "wallet": wallet.lower()}, root)
print(json.dumps({"fingerprint": fingerprint}))
