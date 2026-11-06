"""Mirrors one accepted fix on a local anvil chain: anvil_mirror.py --root DIR --bounty ID --fix N [--port 5298].

LOCAL TEST CHAIN. Chain id 31337 on 127.0.0.1 only, with a test token and anvil's public dev accounts from its public mnemonic. Each send first checks the chain id, so this code cannot reach a real network. No money moves, and no Solidity changes.
fingerprint = keccak256(abi.encode(bountyId, patched sha)), perFailure = pay, cap = pay, so a second fix hits CapExceeded. It proves the contract takes this fix's numbers. It says nothing about a real robot.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix as X

LABEL = "Local test chain."
CHAIN_ID = 31337
HOST = "127.0.0.1"
MNEMONIC = "test test test test test test test test test test test junk"  # anvil's default, public, and refused by Deploy.s.sol on Arc
CONTRACTS = X.POLICY.parent / "contracts"
TOKEN_UNIT = 10**6
GRACE_S = 3600
DEADLINE_S = 7 * 24 * 3600
CREATE_SIG = "createBounty(address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64)"


def run(*args):
    done = subprocess.run(list(args), capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"{args[0]} {args[1]}: {done.stderr.strip()[:400]}")
    return done.stdout.strip()


class Chain:
    def __init__(self, port):
        self.rpc = f"http://{HOST}:{port}"
        self.txs = {}
        self.keys = [run("cast", "wallet", "private-key", MNEMONIC, str(i)) for i in range(4)]
        self.addresses = [run("cast", "wallet", "address", key) for key in self.keys]

    run = staticmethod(run)

    def guard(self):
        chain = int(self.run("cast", "chain-id", "--rpc-url", self.rpc))
        if chain != CHAIN_ID or not self.rpc.startswith(f"http://{HOST}:"):
            raise SystemExit(f"Refused: chain {chain} at {self.rpc} is not the local test chain.")

    def signer(self, who):
        return ["--private-key", self.keys[who]]

    def send(self, name, who, to, sig, *args):
        self.guard()
        reply = json.loads(self.run("cast", "send", "--json", "--rpc-url", self.rpc, *self.signer(who), to, sig, *map(str, args)))
        if reply["status"] not in ("0x1", 1):
            raise RuntimeError(f"{name} reverted")
        self.txs[name] = reply["transactionHash"]
        return reply

    def deploy(self, name, artifact, ctor_sig=None, *args):
        self.guard()
        code = json.loads((CONTRACTS / "out" / artifact).read_text())["bytecode"]["object"]
        data = code + (self.run("cast", "abi-encode", ctor_sig, *map(str, args))[2:] if ctor_sig else "")
        reply = json.loads(self.run("cast", "send", "--json", "--rpc-url", self.rpc, *self.signer(0), "--create", data))
        if reply["status"] not in ("0x1", 1):
            raise RuntimeError(f"{name} reverted")
        self.txs[name] = reply["transactionHash"]
        return reply["contractAddress"]

    def read(self, to, sig, *args):
        return self.run("cast", "call", "--rpc-url", self.rpc, to, sig, *map(str, args))

    def refused(self, who, to, sig, *args):
        """A dry call that must revert. Returns the contract's error name or data."""
        self.guard()
        done = subprocess.run(["cast", "call", "--rpc-url", self.rpc, "--from", self.addresses[who], to, sig, *map(str, args)], capture_output=True, text=True, timeout=60)
        return None if done.returncode == 0 else done.stderr.strip()[-200:]


def selector(name):
    return run("cast", "sig", f"{name}()")[:10]


def fix_numbers(folder, n):
    """What the contract needs from one accepted fix with a ledger row, or None. Both mirrors read it here."""
    row = json.loads((folder / "fixes" / str(n) / "fix.json").read_text())
    if not row["result"] or not row["result"].get("accepted") or not row.get("payout") or "fingerprint" not in row["payout"]:
        return None
    money = json.loads((folder / "ledger.json").read_text())["bounty"]
    return {"pay": money["per_failure"] * TOKEN_UNIT, "window": money["dispute_window_s"], "spec_hash": money["spec_hash"], "result_hash": row["payout"]["result_hash"],
            "patched": "0x" + row["result"]["patched_sha256"], "local_status": row["payout"].get("status")}


def fingerprint_on_chain(chain, chain_bounty, patched):
    return chain.run("cast", "keccak", chain.run("cast", "abi-encode", "f(uint256,bytes32)", str(chain_bounty), patched))


def mirror(root, bounty_id, n, port):
    folder = X.folder_of(bounty_id, root)
    numbers = fix_numbers(folder, n)
    if not numbers:
        raise SystemExit("Only an accepted fix with a ledger row can be mirrored.")
    pay, window, spec_hash, result_hash, patched = (numbers[k] for k in ("pay", "window", "spec_hash", "result_hash", "patched"))

    run("forge", "build", "--root", str(CONTRACTS))
    anvil = subprocess.Popen(["anvil", "--host", HOST, "--port", str(port), "--chain-id", str(CHAIN_ID), "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        chain = Chain(port)
        for _ in range(50):
            try:
                chain.guard()
                break
            except RuntimeError:
                time.sleep(0.2)
        company, resolver, arbiter, tester = chain.addresses
        token = chain.deploy("deploy_test_token", "Mocks.sol/MockUSDC.json", "f(uint8)", 6)
        bounty = chain.deploy("deploy_failure_bounty", "FailureBounty.sol/FailureBounty.json", "f(address)", token)
        chain.send("mint_test_token", 0, token, "mint(address,uint256)", company, pay)
        chain.send("approve", 0, token, "approve(address,uint256)", bounty, pay)
        now = int(run("cast", "block", "latest", "--field", "timestamp", "--rpc-url", chain.rpc))
        chain.send("create_bounty", 0, bounty, CREATE_SIG, resolver, arbiter, spec_hash, pay, pay, 0, now + DEADLINE_S, GRACE_S, window)
        chain_id = 1
        fingerprint = fingerprint_on_chain(chain, chain_id, patched)
        other = run("cast", "keccak", run("cast", "abi-encode", "f(uint256,bytes32)", str(chain_id), "0x" + "11" * 32))
        before = {"company": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", company))), "bounty": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", bounty))), "tester": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", tester)))}
        chain.send("propose", 1, bounty, "propose(uint256,address,bytes32,bytes32,bool)", chain_id, tester, fingerprint, result_hash, "false")
        second_fix = chain.refused(1, bounty, "propose(uint256,address,bytes32,bytes32,bool)", chain_id, tester, other, result_hash, "false")
        early = chain.refused(0, bounty, "finalize(uint256,bytes32)", chain_id, fingerprint)
        chain.guard()
        run("cast", "rpc", "--rpc-url", chain.rpc, "evm_increaseTime", str(window + 1))
        run("cast", "rpc", "--rpc-url", chain.rpc, "evm_mine")
        chain.send("finalize", 2, bounty, "finalize(uint256,bytes32)", chain_id, fingerprint)
        wrong_claim = chain.refused(0, bounty, "claim(uint256,bytes32)", chain_id, fingerprint)
        chain.send("claim", 3, bounty, "claim(uint256,bytes32)", chain_id, fingerprint)
        after = {"company": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", company))), "bounty": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", bounty))), "tester": int(run("cast", "--to-dec", chain.read(token, "balanceOf(address)", tester)))}
        names = {name: selector(name) for name in ("CapExceeded", "DisputeWindowOpen", "NotSubmitter")}
        record = {"label": LABEL, "chain_id": CHAIN_ID, "bounty_local": bounty_id, "fix": n, "token": token, "contract": bounty, "fingerprint": fingerprint, "result_hash": result_hash, "pay_base_units": pay, "txs": chain.txs,
                  "balances_before_propose": before, "balances_after_claim": after, "reverts": {"second_fix": second_fix, "finalize_early": early, "claim_by_other": wrong_claim}, "error_selectors": names, "accounts": {"company": company, "resolver": resolver, "arbiter": arbiter, "tester": tester}}
        checks = {"second fix hits CapExceeded": bool(second_fix) and names["CapExceeded"] in second_fix.lower() or "CapExceeded" in (second_fix or ""),
                  "early finalize refused": bool(early) and (names["DisputeWindowOpen"] in early.lower() or "DisputeWindowOpen" in early),
                  "other account cannot claim": bool(wrong_claim) and (names["NotSubmitter"] in wrong_claim.lower() or "NotSubmitter" in wrong_claim),
                  "tester holds the pay": after["tester"] == pay and after["bounty"] == 0 and before["bounty"] == pay}
        record["checks"] = checks
        (folder / "chain_mirror.json").write_text(json.dumps(record, indent=1))
        return record
    finally:
        anvil.terminate()
        anvil.wait(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--bounty", type=int, required=True)
    ap.add_argument("--fix", type=int, required=True)
    ap.add_argument("--port", type=int, default=5298)
    a = ap.parse_args()
    record = mirror(Path(a.root), a.bounty, a.fix, a.port)
    print(json.dumps(record, indent=1))
    return 0 if all(record["checks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
