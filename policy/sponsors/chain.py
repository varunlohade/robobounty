"""Reads FailureBounty and USDC through cast. No key reaches this file, so the web process can use it. It sends nothing.

The label comes from the chain id that the RPC reports, not from config. Only Arc testnet and a local anvil chain are allowed.
"""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import sponsor_status as status

LOCAL_CHAIN_ID = 31337
ALLOWED_CHAINS = (status.ARC_TESTNET_CHAIN_ID, LOCAL_CHAIN_ID)
STATUS = ("None", "Pending", "Rejected", "Finalized", "Claimed")
BOUNTY_SIG = "bounties(uint256)(address,address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64,bool)"
FAILURE_SIG = "failures(uint256,bytes32)(address,uint256,bytes32,uint64,bool,uint8)"
CREATED_EVENT = "BountyCreated(uint256 indexed bountyId, address indexed company, address resolver, address arbiter, bytes32 specHash, uint256 cap, uint256 perFailure, uint256 topPrize, uint64 deadline, uint64 refundOpensAt, uint64 disputeWindow)"
PROPOSED_EVENT = "FailureProposed(uint256 indexed bountyId, bytes32 indexed fingerprint, address indexed submitter, bytes32 resultHash, uint256 amount, bool isTopPrize, uint64 disputeEndsAt)"
TIMEOUT_S = 30


class ChainError(Exception):
    """The message is a fixed code."""


def resolver_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("ARC_RESOLVER_DIR") or Path(__file__).resolve().parent.parent / "runs" / "resolver")


def chain_label(chain_id):
    if chain_id == status.ARC_TESTNET_CHAIN_ID:
        return "Arc testnet. Test USDC, no real money."
    return f"Local test chain {chain_id}, not Arc. Mock USDC, no real money."


def plain_number(text):
    """cast prints '1000000 [1e6]' for big numbers."""
    return int(str(text).split()[0], 0)


class Chain:
    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        self.cast = self.env.get("ARC_CAST_BIN") or "cast"
        self.rpc = self.env["ARC_RPC_URL"]
        self.address = self.env["ARC_BOUNTY_ADDRESS"]
        self.bounty_id = int(self.env["ARC_BOUNTY_ID"])
        self.usdc = self.env["ARC_USDC_ADDRESS"]
        self.tester = self.env["ARC_TESTER_ADDRESS"]
        self.from_block = self.env.get("ARC_FROM_BLOCK") or "0"
        self._chain_id = None

    def _cast(self, *args):
        # A signing key is never in this list, and the child gets no secret from the environment.
        try:
            done = subprocess.run([self.cast, *args], capture_output=True, text=True, timeout=TIMEOUT_S, env=status.child_env(env=self.env))
        except (OSError, subprocess.TimeoutExpired):
            raise ChainError("cast_failed") from None
        if done.returncode != 0:
            raise ChainError("rpc_read_failed")
        return done.stdout

    def _json(self, *args):
        try:
            value = json.loads(self._cast(*args, "--json"))
        except ValueError:
            raise ChainError("rpc_read_failed") from None
        # Newer Foundry wraps its output in an envelope. Arc Foundry may not.
        return value["data"] if isinstance(value, dict) and "schema_version" in value else value

    def call(self, signature, *args):
        return self._json("call", self.address, signature, *[str(a) for a in args], "--rpc-url", self.rpc)

    def chain_id(self):
        if self._chain_id is None:
            self._chain_id = int(self._cast("chain-id", "--rpc-url", self.rpc).strip())
            if self._chain_id not in ALLOWED_CHAINS:
                raise ChainError("chain_not_allowed")
        return self._chain_id

    def now(self):
        return int(self._cast("block", "latest", "--field", "timestamp", "--rpc-url", self.rpc).strip().split()[0], 0)

    def balance(self, who):
        value = self._json("call", self.usdc, "balanceOf(address)(uint256)", who, "--rpc-url", self.rpc)
        return plain_number(value[0] if isinstance(value, list) else value)

    def logs(self, event):
        rows = self._json("logs", "--from-block", self.from_block, "--to-block", "latest", "--address", self.address, event, "--rpc-url", self.rpc)
        return [r for r in rows or [] if int(r["topics"][1], 16) == self.bounty_id]

    def bounty(self):
        row = self.call(BOUNTY_SIG, self.bounty_id)
        if int(row[0], 16) == 0:
            raise ChainError("no_such_bounty")
        return {"company": row[0], "resolver": row[1], "arbiter": row[2], "spec_hash": row[3], "per_failure": plain_number(row[4]), "top_prize": plain_number(row[5]), "available": plain_number(row[6]),
                "deadline": plain_number(row[7]), "refund_opens_at": plain_number(row[8]), "dispute_window_s": plain_number(row[9]), "top_prize_taken": row[10] in (True, "true")}

    def failure(self, fingerprint):
        row = self.call(FAILURE_SIG, self.bounty_id, fingerprint)
        return {"submitter": row[0], "amount": plain_number(row[1]), "result_hash": row[2], "dispute_ends_at": plain_number(row[3]), "is_top_prize": row[4] in (True, "true"), "status": STATUS[plain_number(row[5])]}

    def snapshot(self):
        chain_id = self.chain_id()
        bounty = self.bounty()
        created = self.logs(CREATED_EVENT)
        words = created[0]["data"][2:] if created else ""
        bounty["id"] = self.bounty_id
        bounty["cap"] = int(words[3 * 64:4 * 64], 16) if words else None
        failures = {}
        for log in self.logs(PROPOSED_EVENT):
            fingerprint = log["topics"][2]
            failures[fingerprint] = {**self.failure(fingerprint), "tx": log["transactionHash"]}
        balances = {"bounty contract": self.balance(self.address), "company": self.balance(bounty["company"]), "tester": self.balance(self.tester)}
        return {"chain_id": chain_id, "label": chain_label(chain_id), "address": self.address, "usdc": self.usdc, "decimals": 6, "bounty": bounty, "failures": failures, "balances": balances, "now": self.now()}


class ChainLedger:
    """Stands where ledger.Ledger stands in the run server. It reads the chain and leaves proposals for the resolver. It holds no key."""
    is_chain = True

    def __init__(self, chain, inbox):
        self.chain, self.inbox = chain, Path(inbox)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.snap = None
        self.refresh()

    def refresh(self):
        self.snap = self.chain.snapshot()
        self.bounty, self.failures = self.snap["bounty"], self.snap["failures"]
        return self.snap

    def waiting(self):
        return sorted(p.stem for p in self.inbox.glob("0x*.json"))

    def paid_list(self):
        """The gate's duplicate list: everything on chain but rejected ones, plus what waits for the resolver."""
        self.refresh()
        return sorted({f for f, r in self.failures.items() if r["status"] != "Rejected"} | set(self.waiting()))

    def request_propose(self, verdict):
        """A file for the resolver process. Written whole, so the resolver never reads half of it."""
        fingerprint = verdict["fingerprint"]
        temp = self.inbox / f".{uuid.uuid4().hex}.tmp"
        temp.write_text(json.dumps({"requested_at": time.time(), "verdict": verdict}))
        temp.rename(self.inbox / f"{fingerprint}.json")
