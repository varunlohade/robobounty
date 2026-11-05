"""LOCAL LEDGER. NOT ON CHAIN. A JSON file with the same rules and states as contracts/src/FailureBounty.sol. It holds no money, key or wallet.

Funded -> proposed (Pending, dispute window open) -> Finalized -> Claimed, or Rejected while the window is open.
"""
import json
import re
import time
from pathlib import Path

LABEL = "Local ledger. Not on chain."
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "src" / "FailureBounty.sol"
MIN_DISPUTE_WINDOW = int(re.search(r"MIN_DISPUTE_WINDOW = (\d+)", CONTRACT.read_text())[1])


class LedgerError(Exception):
    """The message is the contract's error name."""


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.bounty = None
        self.failures = {}

    def _save(self):
        self.path.write_text(json.dumps({"label": LABEL, "bounty": self.bounty, "failures": self.failures}, indent=1))

    def fund(self, spec_hash, cap, per_failure, window, company, resolver, arbiter):
        if len({company, resolver, arbiter}) != 3:
            raise LedgerError("RolesNotSeparate")
        if per_failure <= 0 or per_failure > cap:
            raise LedgerError("BadAmounts")
        if window < MIN_DISPUTE_WINDOW:
            raise LedgerError("BadTimes")
        self.bounty = {"id": 1, "state": "funded", "spec_hash": spec_hash, "cap": cap, "per_failure": per_failure, "available": cap, "dispute_window_s": window,
                       "company": company, "resolver": resolver, "arbiter": arbiter}
        self._save()

    def propose(self, submitter, fingerprint, result_hash, now=None):
        if self.bounty is None:
            raise LedgerError("UnknownBounty")
        old = self.failures.get(fingerprint)
        if old and old["status"] != "Rejected":
            raise LedgerError("DuplicateFingerprint")
        if self.bounty["available"] < self.bounty["per_failure"]:
            raise LedgerError("CapExceeded")
        now = time.time() if now is None else now
        self.bounty["available"] -= self.bounty["per_failure"]
        self.failures[fingerprint] = {"submitter": submitter, "amount": self.bounty["per_failure"], "result_hash": result_hash,
                                      "dispute_ends_at": now + self.bounty["dispute_window_s"], "status": "Pending"}
        self._save()

    def _pending(self, fingerprint):
        row = self.failures.get(fingerprint)
        if not row or row["status"] != "Pending":
            raise LedgerError("WrongStatus")
        return row

    def reject(self, fingerprint, now=None):
        row = self._pending(fingerprint)
        if (time.time() if now is None else now) >= row["dispute_ends_at"]:
            raise LedgerError("DisputeWindowClosed")
        row["status"] = "Rejected"
        self.bounty["available"] += row["amount"]
        self._save()

    def finalize(self, fingerprint, now=None):
        row = self._pending(fingerprint)
        if (time.time() if now is None else now) < row["dispute_ends_at"]:
            raise LedgerError("DisputeWindowOpen")
        row["status"] = "Finalized"
        self._save()

    def claim(self, fingerprint, caller):
        row = self.failures.get(fingerprint)
        if not row or row["status"] != "Finalized":
            raise LedgerError("WrongStatus")
        if caller != row["submitter"]:
            raise LedgerError("NotSubmitter")
        row["status"] = "Claimed"
        self._save()

    def paid_list(self):
        """Fingerprints for the gate: pending and paid. A rejected proposal leaves the list."""
        return sorted(f for f, r in self.failures.items() if r["status"] != "Rejected")
