"""The resolver service: the only process that holds the resolver key. Keep it out of web and LLM processes (threat model risk 1).

resolver.py serve [--once]             propose from each gate verdict in the inbox, finalize after each dispute window. Needs ARC_RESOLVER_KEYSTORE and ARC_RESOLVER_PASSWORD_FILE.
resolver.py claim --fingerprint 0x..   the tester's own claim. The contract pays only if the named submitter calls, so this uses the tester's key and never the resolver's.

It checks a verdict but cannot prove one: anyone who can write to the inbox can build a verdict that passes these checks. The arbiter and the dispute window are the check on that.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chain as chain_module
import sponsor_status as status
import world_store

HASH32 = re.compile(r"0x[0-9a-f]{64}")
PROPOSE = "propose(uint256,address,bytes32,bytes32,bool)"
POLL_S = 2
SEND_TIMEOUT_S = 120
ARC_MIN_FEE_WEI = 20 * 10**9  # Arc docs: a lower maxFeePerGas gets silently dropped
ARC_TIP_WEI = 10**9
CONTRACT_ERRORS = ("NotResolver", "PastDeadline", "BadAddress", "BadHash", "DuplicateFingerprint", "TopPrizeUnavailable", "CapExceeded", "WrongStatus", "DisputeWindowOpen", "NotSubmitter", "UnknownBounty", "Reentrancy", "TokenTransferFailed")


class Refused(Exception):
    """The message is a fixed code. The resolver sends nothing."""


def fee_flags(chain_id, gas_price_wei):
    """Arc has a 20 Gwei floor. Local anvil needs no flags."""
    if chain_id != status.ARC_TESTNET_CHAIN_ID:
        return []
    return ["--gas-price", str(max(2 * gas_price_wei, ARC_MIN_FEE_WEI)), "--priority-gas-price", str(ARC_TIP_WEI)]


def verdict_problem(verdict, bounty_id, chain_spec_hash, wallet_verified, need_world_id=True):
    """Returns a fixed code, or None. Every value that goes on chain comes from this verdict, so each one is checked here."""
    sys.path.insert(0, str(HERE.parent / "bounty"))
    from gate import PROPOSE as GATE_PROPOSE, VERDICT_SCHEMA, result_hash_of
    if not isinstance(verdict, dict) or verdict.get("schema") != VERDICT_SCHEMA or verdict.get("accepted") is not True or verdict.get("code") != "accepted":
        return "not_an_accepted_verdict"
    propose = verdict.get("propose")
    named = propose.get("named") if isinstance(propose, dict) else None
    if not isinstance(named, dict) or propose.get("function") != GATE_PROPOSE or GATE_PROPOSE != PROPOSE:
        return "bad_propose_arguments"
    if named.get("bountyId") != bounty_id:
        return "wrong_bounty"
    if verdict.get("spec_hash") != chain_spec_hash:
        return "spec_hash_differs_from_chain"
    submitter, fingerprint, result_hash = named.get("submitter"), named.get("fingerprint"), named.get("resultHash")
    if not isinstance(submitter, str) or not status.ADDRESS.fullmatch(submitter) or int(submitter, 16) == 0 or submitter != verdict.get("submitter"):
        return "bad_submitter"
    if not all(isinstance(h, str) and HASH32.fullmatch(h) for h in (fingerprint, result_hash)) or fingerprint != verdict.get("fingerprint") or result_hash != verdict.get("result_hash"):
        return "bad_hash"
    if named.get("isTopPrize") is not False:
        return "top_prize_is_the_company_choice"
    repeat, reference = verdict.get("repeat"), verdict.get("reference_check")
    if not isinstance(repeat, dict) or not isinstance(repeat.get("same"), int) or repeat["same"] < repeat.get("need", 10**6) or not isinstance(reference, dict) or reference.get("passed") is not True:
        return "gate_rules_not_met"
    try:
        rebuilt = result_hash_of(verdict["spec_hash"], verdict["submission_hash"], verdict["runs"])
    except (KeyError, TypeError):
        return "bad_hash"
    if rebuilt != result_hash:
        return "result_hash_mismatch"
    if need_world_id and (not wallet_verified or (verdict.get("human_cap") or {}).get("world_id_connected") is not True):
        return "no_verified_human"
    return None


class Signer:
    def __init__(self, chain, keystore, password_file):
        self.chain, self.keystore, self.password_file = chain, keystore, password_file
        self.address = subprocess.run([chain.cast, "wallet", "address", "--keystore", keystore, "--password-file", password_file], capture_output=True, text=True, timeout=30, check=True).stdout.strip()

    def send(self, signature, *args):
        chain = self.chain
        price = int(chain._cast("gas-price", "--rpc-url", chain.rpc).strip())
        argv = [chain.cast, "send", chain.address, signature, *[str(a) for a in args], "--rpc-url", chain.rpc, "--keystore", self.keystore, "--password-file", self.password_file, "--json", *fee_flags(chain.chain_id(), price)]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=SEND_TIMEOUT_S)
        if done.returncode != 0:
            raise Refused(self._error_name(done.stdout + done.stderr))
        value = json.loads(done.stdout)
        receipt = value["data"] if isinstance(value, dict) and "schema_version" in value else value
        if isinstance(receipt, list):
            receipt = receipt[0]
        if int(str(receipt.get("status", "0x0")), 0) != 1:
            raise Refused("transaction_reverted")
        return receipt["transactionHash"]

    def _error_name(self, text):
        for name in CONTRACT_ERRORS:
            if name in text:
                return name
            selector = subprocess.run([self.chain.cast, "sig", f"{name}()"], capture_output=True, text=True, timeout=30).stdout.strip()
            if selector and selector in text:
                return name
        return "transaction_refused"


class Resolver:
    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        for name in ("ZG_API_KEY", "WORLD_RP_SIGNING_KEY", "ARC_TESTER_KEYSTORE", "ARC_ARBITER_KEYSTORE", "ARC_COMPANY_KEYSTORE"):
            if self.env.get(name):
                raise SystemExit(f"Refused: {name} must not be set in the resolver process.")
        self.chain = chain_module.Chain(self.env)
        self.chain.chain_id()
        self.signer = Signer(self.chain, self.env["ARC_RESOLVER_KEYSTORE"], self.env["ARC_RESOLVER_PASSWORD_FILE"])
        if self.chain.chain_id() == status.ARC_TESTNET_CHAIN_ID and self.signer.address.lower() in FOUNDRY_DEFAULTS:
            raise SystemExit("Refused: a Foundry default account has a public key. Use a new wallet on Arc testnet.")
        self.root = chain_module.resolver_dir(self.env)
        self.inbox, self.done, self.failed = self.root / "inbox", self.root / "done", self.root / "failed"
        for folder in (self.inbox, self.done, self.failed):
            folder.mkdir(parents=True, exist_ok=True)
        self.need_world_id = self.env.get("ARC_REQUIRE_WORLD_ID", "1") != "0"
        self.db = status.world_db(self.env)

    def log(self, step, **fields):
        row = {"at": round(time.time(), 3), "step": step, **fields}
        with open(self.root / "log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def propose_one(self, path):
        fingerprint = path.stem
        try:
            verdict = json.loads(path.read_text())["verdict"]
            bounty = self.chain.bounty()
            if bounty["resolver"].lower() != self.signer.address.lower():
                raise Refused("not_the_named_resolver")
            named = (verdict.get("propose") or {}).get("named") or {}
            verified = isinstance(named.get("submitter"), str) and world_store.is_verified(self.db, named["submitter"], status.WORLD_ACTION)
            problem = verdict_problem(verdict, self.chain.bounty_id, bounty["spec_hash"], verified, self.need_world_id)
            if problem:
                raise Refused(problem)
            if fingerprint != named["fingerprint"]:
                raise Refused("bad_hash")
            current = self.chain.failure(fingerprint)["status"]
            if current in ("Pending", "Finalized", "Claimed"):  # a restart after a send: never send twice
                self.log("propose_skipped", fingerprint=fingerprint, on_chain=current)
            else:
                tx = self.signer.send(PROPOSE, self.chain.bounty_id, named["submitter"], fingerprint, named["resultHash"], "false")
                self.log("propose", fingerprint=fingerprint, submitter=named["submitter"], tx=tx)
            path.rename(self.done / path.name)
        except (Refused, ValueError, KeyError, TypeError) as e:
            code = str(e) if isinstance(e, Refused) else "bad_request_file"
            self.log("propose_refused", fingerprint=fingerprint, code=code)
            path.rename(self.failed / path.name)

    def finalize_due(self):
        now = self.chain.now()
        for log in self.chain.logs(chain_module.PROPOSED_EVENT):
            fingerprint = log["topics"][2]
            row = self.chain.failure(fingerprint)
            if row["status"] == "Pending" and now >= row["dispute_ends_at"]:
                try:
                    tx = self.signer.send("finalize(uint256,bytes32)", self.chain.bounty_id, fingerprint)
                    self.log("finalize", fingerprint=fingerprint, tx=tx)
                except Refused as e:
                    self.log("finalize_refused", fingerprint=fingerprint, code=str(e))

    def once(self):
        for path in sorted(self.inbox.glob("0x*.json")):
            self.propose_one(path)
        self.finalize_due()

    def serve(self):
        self.log("started", resolver=self.signer.address, chain_id=self.chain.chain_id(), label=chain_module.chain_label(self.chain.chain_id()))
        while True:
            try:
                self.once()
            except chain_module.ChainError as e:
                self.log("read_failed", code=str(e))
            time.sleep(POLL_S)


FOUNDRY_DEFAULTS = {a.lower() for a in (
    "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266", "0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65", "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc", "0x976EA74026E726554dB657fA54763abd0C3a0aa9", "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
    "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f", "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720")}


def claim(fingerprint, env=None):
    env = os.environ if env is None else env
    if env.get("ARC_RESOLVER_KEYSTORE"):
        raise SystemExit("Refused: the resolver key must not be set in the tester's process.")
    if not HASH32.fullmatch(fingerprint):
        raise SystemExit("The fingerprint must be a 0x-prefixed lowercase 32-byte hash.")
    chain = chain_module.Chain(env)
    chain.chain_id()
    signer = Signer(chain, env["ARC_TESTER_KEYSTORE"], env["ARC_TESTER_PASSWORD_FILE"])
    row = chain.failure(fingerprint)
    if row["submitter"].lower() != signer.address.lower():
        raise SystemExit("Refused: this wallet is not the named submitter.")
    before = chain.balance(signer.address)
    tx = signer.send("claim(uint256,bytes32)", chain.bounty_id, fingerprint)
    print(json.dumps({"step": "claim", "fingerprint": fingerprint, "tx": tx, "tester_balance_before": before, "tester_balance_after": chain.balance(signer.address), "decimals": 6}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--once", action="store_true")
    claim_parser = sub.add_parser("claim")
    claim_parser.add_argument("--fingerprint", required=True)
    a = ap.parse_args()
    if a.command == "claim":
        try:
            return claim(a.fingerprint)
        except Refused as e:
            raise SystemExit(f"Claim refused: {e}.") from None
    resolver = Resolver()
    if a.once:
        resolver.once()
    else:
        resolver.serve()


if __name__ == "__main__":
    main()
