"""Checks arc_mirror.py on local anvil with chain id 5042002, the real contract, MockUSDC at Arc's USDC address and new throwaway keystores. No real Arc call.

check_arc.py [--port 5441]. It starts and stops its own anvil chains. It proves the flow and its failure paths, and says nothing about Arc's own EVM, gas or USDC.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anvil_mirror as A
import arc_mirror as M
import board_fix as X
import board_store as B
import budget

PY = sys.executable
PASSWORD = "local-check-password-not-a-secret"
PATCHED = "ab" * 32
failed = 0


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail else ''}", flush=True)


class Anvil:
    def __init__(self, port, chain_id):
        self.rpc = f"http://127.0.0.1:{port}"
        self.proc = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", str(port), "--chain-id", str(chain_id), "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if subprocess.run(["cast", "chain-id", "--rpc-url", self.rpc], capture_output=True).returncode == 0:
                return
            time.sleep(0.2)
        raise SystemExit("anvil did not start")

    def stop(self):
        self.proc.terminate()
        self.proc.wait(10)

    def rpc_call(self, *args):
        return subprocess.run(["cast", "rpc", "--rpc-url", self.rpc, *args], capture_output=True, text=True, check=True).stdout

    def fund_gas(self, address, wei=10**20):
        self.rpc_call("anvil_setBalance", address, hex(wei))

    def install_usdc(self):
        code = json.loads((A.CONTRACTS / "out" / "Mocks.sol" / "MockUSDC.json").read_text())["deployedBytecode"]["object"]
        self.rpc_call("anvil_setCode", M.USDC, code)
        self.rpc_call("anvil_setStorageAt", M.USDC, "0x0", "0x" + "6".zfill(64))

    def mint(self, keystore, address, amount):
        M.A.run("cast", "send", "--rpc-url", self.rpc, "--keystore", keystore, "--password-file", str(Path(keystore).parent / "password"), M.USDC, "mint(address,uint256)", address, str(amount))

    def skip(self, seconds):
        self.rpc_call("evm_increaseTime", str(seconds))
        self.rpc_call("evm_mine")


def make_wallets(folder):
    folder.mkdir(mode=0o700)
    (folder / "password").write_text(PASSWORD)
    (folder / "password").chmod(0o600)
    for role in M.ROLES:
        subprocess.run(["cast", "wallet", "new", str(folder), role, "--unsafe-password", PASSWORD], capture_output=True, check=True)
    return M.Wallets(folder)


def post_fix(root, bounty_id, pay=10, window=60, posted_by="company", n=1, patched=PATCHED, fund=True):
    folder = Path(root) / str(bounty_id)
    (folder / "fixes" / str(n)).mkdir(parents=True, exist_ok=True)
    fingerprint = X.fingerprint_of(bounty_id, patched)
    if fund:
        book = B.ledger_module.Ledger(folder / "ledger.json")
        book.fund("0x" + f"{bounty_id:064x}", pay, pay, window, B.COMPANY, B.RESOLVER, B.ARBITER)
        (folder / "pack.json").write_text(json.dumps({"id": bounty_id, "posted_by": posted_by, "title": "t", "pay": pay}))
        book.propose(B.tester_address("tester"), fingerprint, "0x" + "cd" * 32)
        payout = book.failures[fingerprint]
    else:  # A fix the local ledger holds no money for, so only the contract can refuse it.
        payout = {"status": "Pending", "result_hash": "0x" + "cd" * 32}
    row = {"n": n, "bounty_id": bounty_id, "tester": "tester", "state": "done", "result": {"accepted": True, "patched_sha256": patched}, "payout": {**payout, "fingerprint": fingerprint}}
    (folder / "fixes" / str(n) / "fix.json").write_text(json.dumps(row))
    return folder


def refuses(code, fn):
    try:
        fn()
    except M.ArcError as e:
        return e.code == code and bool(e.words)
    return False


def nonce(chain, who):
    return int(chain.run("cast", "nonce", chain.addresses[who], "--rpc-url", chain.rpc))


def silent_server():
    """Accepts a connection and never answers, like a hung RPC."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    threading.Thread(target=lambda: [server.accept() for _ in range(99)], daemon=True).start()
    return server.getsockname()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5441)
    a = ap.parse_args()
    temp = Path(tempfile.mkdtemp(prefix="check-arc-"))
    root = temp / "board"
    root.mkdir()
    chains = []
    os.environ["ARC_CAP_USDC"] = "25"
    for name in [k for k in os.environ if M.KEY_IN_ENV.search(k)]:
        del os.environ[name]
    try:
        M.A.run("forge", "build", "--root", str(A.CONTRACTS))
        node = Anvil(a.port, M.CHAIN_ID)
        chains.append(node)
        wallets = make_wallets(temp / "wallets")
        chain = M.ArcChain(node.rpc, wallets)
        for who in range(4):
            node.fund_gas(chain.addresses[who])
        node.install_usdc()
        node.mint(str(wallets.dir / "company"), chain.addresses[M.COMPANY], 100 * 10**6)

        print("-- labels and network refusals")
        check("the Arc label needs a real Arc testnet host", M.check_rpc("https://rpc.testnet.arc.io") is True and M.label_of(True) == "Arc testnet. Not real money." and M.check_rpc(node.rpc) is False and "Not Arc" in M.label_of(False))
        check("a local chain gets no explorer link", M.tx_link(chain, "0xaa") is None)
        check("a real host gets a link to the Arc testnet explorer", M.EXPLORER + "0xaa" == "https://explorer.testnet.arc.io/tx/0xaa")
        for url in ("https://rpc.mainnet.arc.io", "https://arc-mainnet.g.alchemy.com/v2/k", "http://rpc.testnet.arc.io", "https://evil.example/rpc.testnet.arc.io", "http://10.0.0.1:8545"):
            check(f"refused before any connection: {url}", refuses("wrong_network", lambda: M.check_rpc(url)))
        for port_add, wrong in ((1, 5042), (2, 1)):
            other = Anvil(a.port + port_add, wrong)
            chains.append(other)
            check(f"wrong network: chain {wrong} is refused", refuses("wrong_network", lambda: M.ArcChain(other.rpc, wallets)))

        print("-- keys")
        old = dict(os.environ)
        os.environ["ETH_PRIVATE_KEY"] = "0x" + "11" * 32
        check("a private key in env is refused", refuses("key_in_env", M.refuse_keys_in_env))
        os.environ.clear()
        os.environ.update(old)
        bad = temp / "default_wallets"
        shutil.copytree(wallets.dir, bad)
        (bad / "tester").unlink()
        subprocess.run(["cast", "wallet", "import", "tester", "--keystore-dir", str(bad), "--private-key", A.run("cast", "wallet", "private-key", A.MNEMONIC, "3"), "--unsafe-password", PASSWORD], capture_output=True, check=True)
        check("a default anvil key is refused on chain 5042002", refuses("default_key", lambda: M.ArcChain(node.rpc, M.Wallets(bad))))
        check("wallets inside the repo are refused", refuses("wallets_in_repo", lambda: M.Wallets(temp / "wallets", repo=temp)))
        (wallets.dir / "password").chmod(0o644)
        check("a password file others can read is refused", refuses("password_open", lambda: M.Wallets(wallets.dir)))
        (wallets.dir / "password").chmod(0o600)

        print("-- timeout")
        os.environ["ARC_RPC_TIMEOUT_S"] = "2"
        hung = f"http://127.0.0.1:{silent_server()}"
        check("a hung RPC gives a plain timeout", refuses("timeout", lambda: M.ArcChain(hung, wallets)))
        del os.environ["ARC_RPC_TIMEOUT_S"]

        print("-- deploy")
        before = nonce(chain, M.COMPANY)
        M.deploy(chain, root, yes=False)
        check("deploy with no --yes sends nothing", nonce(chain, M.COMPANY) == before and not (root / "arc.json").exists())
        M.deploy(chain, root, yes=True)
        contract = M.deployed(root)["contract"]
        check("deploy with --yes puts the contract on chain", nonce(chain, M.COMPANY) == before + 1 and len(chain.run("cast", "code", contract, "--rpc-url", chain.rpc)) > 100)
        check("a second deploy is refused", refuses("already_deployed", lambda: M.deploy(chain, root, yes=True)))
        check("deploy gets no link on a local chain, and a local label", M.deployed(root)["tx_link"] is None and "Not Arc" in M.deployed(root)["label"])

        print("-- budget: refused before any send")
        folder = post_fix(root, 1, pay=10)
        os.environ["ARC_CAP_USDC"] = "9"
        before = nonce(chain, M.COMPANY)
        record = M.sync(chain, root, 1, 1, contract)
        check("over ARC_CAP_USDC: no send and a plain message", nonce(chain, M.COMPANY) == before and "ARC_CAP_USDC" in record["message"] and not record["paid"] and not record["txs"], record["message"])
        os.environ["ARC_CAP_USDC"] = "not-a-number"
        record = M.sync(chain, root, 1, 1, contract)
        check("no cap set: no send", nonce(chain, M.COMPANY) == before and "ARC_CAP_USDC" in record["message"])
        os.environ["ARC_CAP_USDC"] = "25"
        agent = post_fix(root, 9, pay=5, posted_by="agent")
        record = M.sync(chain, root, 9, 1, contract)
        check("an agent bounty the budget does not hold: no send", nonce(chain, M.COMPANY) == before and "budget" in record["message"], record["message"])
        shutil.rmtree(agent)

        print("-- empty balance")
        rich = chain.read_int(M.USDC, "balanceOf(address)(uint256)", chain.addresses[M.COMPANY])
        M.A.run("cast", "send", "--rpc-url", chain.rpc, *wallets.signer(M.COMPANY), M.USDC, "transfer(address,uint256)", "0x" + "77" * 20, str(rich))
        before = nonce(chain, M.COMPANY)
        record = M.sync(chain, root, 1, 1, contract)
        check("company with no test USDC: no send and a plain message", nonce(chain, M.COMPANY) == before and "less test USDC" in record["message"] and not record["paid"], record["message"])
        node.mint(str(wallets.dir / "company"), chain.addresses[M.COMPANY], 100 * 10**6)
        node.fund_gas(chain.addresses[M.RESOLVER], 0)
        record = M.sync(chain, root, 1, 1, contract)
        check("resolver with no gas: propose is not sent, and the message names the wallet", "resolver wallet" in record["message"] and record["state"] == "None" and not record["paid"] and "propose" not in record["txs"], record["message"])
        node.fund_gas(chain.addresses[M.RESOLVER])

        print("-- happy path")
        record = M.sync(chain, root, 1, 1, contract)
        fingerprint, chain_bounty = record["fingerprint"], record["chain_bounty"]
        check("an accepted fix proposes on the contract", record["state"] == "Pending" and record["txs"].get("propose") and not record["paid"], record["state"])
        pay = chain.read_int(M.USDC, "balanceOf(address)(uint256)", contract)
        check("the contract holds exactly the pay", pay == 10 * 10**6, pay)
        record = M.sync(chain, root, 1, 1, contract)
        check("a pass inside the dispute window finalizes nothing", record["state"] == "Pending" and "finalize" not in record["txs"])
        spends = len(M.spend_rows(root))
        node.fund_gas(chain.addresses[M.TESTER], 0)
        node.skip(61)
        record = M.sync(chain, root, 1, 1, contract)
        check("tester with no gas: finalized, claim not sent, no payout marked", record["state"] == "Finalized" and "tester wallet" in record["message"] and not record["paid"] and "claim" not in record["txs"], record["message"])
        node.fund_gas(chain.addresses[M.TESTER])
        record = M.sync(chain, root, 1, 1, contract)
        tester_usdc = chain.read_int(M.USDC, "balanceOf(address)(uint256)", chain.addresses[M.TESTER])
        check("the tester claims, and holds the pay in USDC", record["state"] == "Claimed" and record["paid"] and tester_usdc == 10 * 10**6 and record["message"] is None, tester_usdc)
        again = M.sync(chain, root, 1, 1, contract)
        check("a pass after the claim sends nothing and pays nothing twice", chain.read_int(M.USDC, "balanceOf(address)(uint256)", chain.addresses[M.TESTER]) == tester_usdc and again["txs"] == record["txs"])
        check("a retried create funded no second bounty", chain.read_int(contract, "bountyCount()(uint256)") == 1 and len(M.spend_rows(root)) == spends)
        view = X._mirror_of(folder)
        check("the page view gets the local label, the hashes and no links", "Not Arc" in view["label"] and view["paid"] and view["tx_links"] == {} and view["txs"]["claim"].startswith("0x"))
        chain.real = True
        check("a real host's record would link each tx", M.tx_link(chain, view["txs"]["claim"]) == M.EXPLORER + view["txs"]["claim"] and M.label_of(chain.real) == "Arc testnet. Not real money.")
        chain.real = False

        print("-- reverted transactions")
        second = post_fix(root, 1, n=2, patched="ef" * 32, fund=False)
        record = M.sync(chain, root, 1, 2, contract)
        check("a second fix hits CapExceeded: a plain message and no payout", "already holds" in record["message"] and not record["paid"] and "propose" not in record["txs"], record["message"])
        check("the page keeps the paid txs and shows the newer fix's message", X._mirror_of(second)["message"] == record["message"] and X._mirror_of(second)["paid"])
        real_run = M.ArcChain.run
        M.ArcChain.run = staticmethod(lambda *cmd: json.dumps({"status": "0x0", "transactionHash": "0x00"}) if cmd[1] == "send" else real_run(*cmd))
        try:
            check("a mined tx with status 0 is a plain revert", refuses("reverted", lambda: chain.send("finalize", M.RESOLVER, contract, "finalize(uint256,bytes32)", chain_bounty, fingerprint)))
        finally:
            M.ArcChain.run = staticmethod(real_run)

        print("-- a local rejection")
        third = post_fix(root, 3, pay=5)
        record = M.sync(chain, root, 3, 1, contract)
        check("it starts pending on chain", record["state"] == "Pending")
        X.ledger_step(3, 1, "reject", root=root)
        record = M.sync(chain, root, 3, 1, contract)
        check("a local rejection goes to the arbiter's reject, inside the window", record["state"] == "Rejected" and record["txs"].get("reject") and not record["paid"], record["state"])
        node.skip(61)
        record = M.sync(chain, root, 3, 1, contract)
        check("after the window it never finalizes", record["state"] == "Rejected" and "finalize" not in record["txs"])
        fourth = post_fix(root, 4, pay=5)
        M.sync(chain, root, 4, 1, contract)
        X.ledger_step(4, 1, "reject", root=root)
        node.skip(61)
        record = M.sync(chain, root, 4, 1, contract)
        check("a rejection too late is said plainly, and the fix is not finalized", record["state"] == "Pending" and "dispute window has closed" in record["message"] and "finalize" not in record["txs"], record["message"])

        print("-- the cap across bounties")
        post_fix(root, 5, pay=6)
        record = M.sync(chain, root, 5, 1, contract)
        check("10 + 5 + 5 + 6 is above the cap of 25: refused", "ARC_CAP_USDC" in record["message"] and not record["txs"], record["message"])

        print("-- stop")
        os.environ["ARC_CAP_USDC"] = "100"
        budget.fund(50, 20, root)
        budget.stop(root)
        before = nonce(chain, M.COMPANY)
        record = M.sync(chain, root, 5, 1, contract)
        check("the company's stop stops new sends", nonce(chain, M.COMPANY) == before and "pressed stop" in record["message"], record["message"])

        print("-- the command line")
        env = {**os.environ, "ARC_RPC_URL": node.rpc, "ARC_WALLET_DIR": str(wallets.dir)}
        cli = lambda *args, **extra: subprocess.run([PY, str(HERE / "arc_mirror.py"), *args, "--root", str(root)], capture_output=True, text=True, env={**env, **extra})
        done = cli("deploy")
        check("the command prints the plan, and a second deploy is refused", done.returncode == 1 and "bytecode_sha256" in done.stdout and "already" in done.stdout)
        done = cli("sync", "--bounty", "1", "--fix", "1", ETH_PRIVATE_KEY="0x" + "11" * 32)
        check("the command refuses a key in env", done.returncode == 1 and "Refused" in done.stdout and "1111" not in done.stdout + done.stderr)
        done = cli("sync", "--bounty", "1", "--fix", "1", ARC_RPC_URL="https://rpc.mainnet.arc.io")
        check("the command refuses mainnet, and leaves the paid record alone", done.returncode == 1 and "not an Arc testnet RPC" in done.stdout and X._mirror_of(folder)["txs"])

        done = cli("sync", "--bounty", "1", "--fix", "1", ARC_RPC_URL="https://rpc.testnet.arc.io", ARC_RPC_TIMEOUT_S="1")
        check("a local deploy record cannot be used with another RPC (or the RPC call fails first)", done.returncode == 1 and "paid" not in done.stdout.split("No payout")[0].lower())

        print("-- no secret on disk or in output")
        saved = "".join(p.read_text() for p in root.rglob("*") if p.is_file())
        keys = [json.loads((wallets.dir / role).read_text())["crypto"]["ciphertext"] for role in M.ROLES]
        check("no password, keystore text or wallet path in the board's files", PASSWORD not in saved and str(wallets.dir) not in saved and not any(k in saved for k in keys))
        check("no password or path in the output of a failed send", all(word not in str(M.classify(f"error: {word}")) for word in (node.rpc, str(wallets.dir))))

        print("-- anvil_mirror still works on the shared code")
        record = A.mirror(root, 1, 1, a.port + 3)
        check("anvil_mirror's own checks pass", all(record["checks"].values()), record["checks"])
    finally:
        for c in chains:
            c.stop()
        shutil.rmtree(temp, ignore_errors=True)
    print(f"{'ALL PASS' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
