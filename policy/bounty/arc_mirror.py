"""Mirrors accepted fixes on Arc testnet in test USDC: arc_mirror.py deploy|sync|serve. Steps and commands: docs/SWITCH-ON.md.

Arc testnet only: chain 5042002, on its four public RPC hosts or on loopback for the local checks. Each start and each send checks the chain id first, and each send signs for that chain id. There is no mainnet code path.
Keys: keystore files in ARC_WALLET_DIR, outside the repo, named company, resolver, arbiter and tester, plus a 0600 file named password. No private key goes in env, repo or logs. This process holds them, and the web process never does.
The chain decides the next step: each pass reads the contract, so a crash or a retry cannot pay twice. The local ledger stays as it was. A fix rejected there is rejected on chain, and is never finalized.
The label says Arc only when the RPC is a real Arc testnet host and the chain confirms its id. Results stay simulated: a payout says nothing about a real robot.
"""
import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anvil_mirror as A
import board_fix as X
import board_store as B
import budget

CHAIN_ID = 5042002
USDC = "0x3600000000000000000000000000000000000000"
RPC_HOSTS = {"rpc.testnet.arc.io", "rpc.blockdaemon.testnet.arc.io", "rpc.drpc.testnet.arc.io", "rpc.quicknode.testnet.arc.io"}
EXPLORER = "https://explorer.testnet.arc.io/tx/"
LABEL_ARC = "Arc testnet. Not real money."
LABEL_LOCAL = "Local stand-in chain. Not Arc. Not real money."
LABEL_OFF = "Not on chain."
ROLES = ("company", "resolver", "arbiter", "tester")
COMPANY, RESOLVER, ARBITER, TESTER = range(4)
# All ten dev accounts of the public test mnemonic. Anyone can derive their keys, and Arc testnet blocklists one of them.
DEFAULT_ACCOUNTS = {"0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266", "0x70997970c51812dc3a010c7d01b50e0d17dc79c8", "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc", "0x90f79bf6eb2c4f870365e785982e1f101e93b906",
                    "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65", "0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc", "0x976ea74026e726554db657fa54763abd0c3a0aa9", "0x14dc79964da2c08b23698b3d3cc7ca32193d9955",
                    "0x23618e81e3f5cdf7f54c3d65f7fbc0abf5b21e8f", "0xa0ee7a142d267c1f36714e4a8f75612f20a79720"}
KEY_IN_ENV = re.compile(r"PRIVATE_KEY|MNEMONIC")
CHILD_ENV = ("PATH", "HOME", "LANG", "TMPDIR")  # A smaller env, so cast finds no ETH_PRIVATE_KEY, ETH_RPC_URL or CAST_PASSWORD.
MIN_FEE_WEI = 40 * 10**9  # Arc's mempool silently drops anything under 20 Gwei: docs.arc.io, evm-differences.
MIN_GAS_WEI = 5 * 10**16  # 0.05 USDC in the 18-decimal native view.
STATUS = ("None", "Pending", "Rejected", "Finalized", "Claimed")
CONTRACT_WORDS = {"CapExceeded": "A fix already holds this bounty's money on the contract.", "DisputeWindowOpen": "The dispute window is still open.", "DisputeWindowClosed": "The dispute window has closed, so the arbiter can no longer reject.",
                  "NotSubmitter": "Only the named tester can claim.", "NotResolver": "This wallet is not the bounty's resolver.", "NotArbiter": "This wallet is not the bounty's arbiter.", "WrongStatus": "The contract is not at this step.",
                  "DuplicateFingerprint": "The contract already holds this fix.", "PastDeadline": "The bounty's deadline has passed.", "RolesNotSeparate": "Company, resolver and arbiter must be different wallets.",
                  "BadTimes": "The contract refused these times.", "BadAmounts": "The contract refused these amounts.", "TokenTransferFailed": "The USDC transfer failed. Arc may have blocked this address.", "WrongAmountReceived": "The contract received the wrong amount."}
NOT_PAID = " No payout is marked."


class ArcError(Exception):
    """A plain message for the page. It never holds a key, a password, a path or raw tool output."""

    def __init__(self, code, words):
        super().__init__(words)
        self.code, self.words = code, words


def timeout_s():
    return int(os.environ.get("ARC_RPC_TIMEOUT_S", "120"))


def check_rpc(url):
    """Returns True for a real Arc testnet host and False for loopback. Anything else is refused before any connection."""
    parts = urlsplit(url or "")
    if parts.scheme == "https" and parts.hostname in RPC_HOSTS:
        return True
    if parts.scheme == "http" and parts.hostname == "127.0.0.1":
        return False
    raise ArcError("wrong_network", "Refused: ARC_RPC_URL is not an Arc testnet RPC. Nothing was sent." + NOT_PAID)


def refuse_keys_in_env():
    found = sorted(k for k in os.environ if KEY_IN_ENV.search(k))
    if found:
        raise ArcError("key_in_env", f"Refused: {', '.join(found)} is set. Arc uses keystore files only. Unset it.")


def label_of(real):
    return LABEL_ARC if real else LABEL_LOCAL


class Wallets:
    def __init__(self, folder, repo=A.CONTRACTS.parent):
        if not folder:
            raise ArcError("no_wallets", "Arc is off: ARC_WALLET_DIR is not set.")
        self.dir = Path(folder).expanduser().resolve()
        if self.dir.is_relative_to(Path(repo).resolve()):
            raise ArcError("wallets_in_repo", "Refused: ARC_WALLET_DIR is inside the repo. Keep wallets outside it.")
        self.password = self.dir / "password"
        missing = [name for name in (*ROLES, "password") if not (self.dir / name).is_file()]
        if missing:
            raise ArcError("no_wallets", f"Arc is off: {', '.join(missing)} missing from ARC_WALLET_DIR.")
        if stat.S_IMODE(self.password.stat().st_mode) & 0o077:
            raise ArcError("password_open", "Refused: the password file must be readable by you only. Run chmod 600 on it.")

    def signer(self, who):
        return ["--keystore", str(self.dir / ROLES[who]), "--password-file", str(self.password)]


class ArcChain(A.Chain):
    """A.Chain's send, deploy and read, with keystores, the testnet checks and plain errors."""

    def __init__(self, rpc, wallets):
        self.real = check_rpc(rpc)
        self.rpc, self.wallets, self.txs = rpc, wallets, {}
        self.fee = None
        self.guard()
        self.addresses = [self.run("cast", "wallet", "address", *wallets.signer(who)).lower() for who in range(4)]
        default = [ROLES[i] for i, a in enumerate(self.addresses) if a in DEFAULT_ACCOUNTS]
        if default:
            raise ArcError("default_key", f"Refused: the {', '.join(default)} wallet is a public anvil dev account. Make new wallets with cast wallet new.")
        if len(set(self.addresses)) != 4:
            raise ArcError("roles_not_four", "Refused: the four roles must be four different wallets.")

    @staticmethod
    def run(*args):
        env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
        try:
            done = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout_s(), env=env)
        except subprocess.TimeoutExpired:
            raise ArcError("timeout", f"The Arc RPC did not answer in {timeout_s()} s. The next pass reads the chain again." + NOT_PAID) from None
        if done.returncode != 0:
            raise classify(done.stderr + done.stdout)  # With --json, cast prints its error on stdout.
        return done.stdout.strip()

    def guard(self):
        chain = int(self.run("cast", "chain-id", "--rpc-url", self.rpc))
        if chain != CHAIN_ID:
            raise ArcError("wrong_network", f"Refused: this RPC reports chain {chain}, not Arc testnet {CHAIN_ID}. Nothing was sent." + NOT_PAID)

    def signer(self, who):
        return [*self.wallets.signer(who), "--chain", str(CHAIN_ID), "--gas-price", str(self.fee_wei())]

    def fee_wei(self):
        if self.fee is None:
            self.fee = max(MIN_FEE_WEI, 2 * int(self.run("cast", "gas-price", "--rpc-url", self.rpc)))
        return self.fee

    def read_int(self, to, sig, *args):
        return int(self.read(to, sig, *args).split()[0], 0)

    def gas_ready(self, who):
        """Before a send: gas in the wallet, and no earlier send of this wallet still waiting, because a retry could then land twice."""
        address = self.addresses[who]
        if int(self.run("cast", "balance", address, "--rpc-url", self.rpc)) < MIN_GAS_WEI:
            raise ArcError("empty_balance", f"The {ROLES[who]} wallet has too little test USDC for gas. Get some at faucet.circle.com." + NOT_PAID)
        counts = {int(self.run("cast", "nonce", address, "--block", block, "--rpc-url", self.rpc)) for block in ("latest", "pending")}
        if len(counts) != 1:
            raise ArcError("tx_waiting", f"An earlier {ROLES[who]} transaction is still waiting, so nothing new was sent." + NOT_PAID)

    def send(self, name, who, to, sig, *args):
        self.gas_ready(who)
        try:
            return super().send(name, who, to, sig, *args)
        except RuntimeError:
            raise ArcError("reverted", f"The {name} transaction reverted." + NOT_PAID) from None

    def failure(self, chain_bounty, fingerprint, contract):
        """(status, end of dispute window, submitter) from the contract."""
        row = self.read(contract, "failures(uint256,bytes32)(address,uint256,bytes32,uint64,bool,uint8)", chain_bounty, fingerprint).split("\n")
        return STATUS[int(row[5].split()[0])], int(row[3].split()[0]), row[0].lower()

    def now(self):
        return int(self.run("cast", "block", "latest", "--field", "timestamp", "--rpc-url", self.rpc), 0)

    def find_bounty(self, contract, spec_hash):
        """The chain bounty that already holds this spec for this company. A crash after a create cannot fund a second one."""
        for chain_bounty in range(self.read_int(contract, "bountyCount()(uint256)"), 0, -1):
            row = self.read(contract, "bounties(uint256)(address,address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64,bool)", chain_bounty).split("\n")
            if row[0].lower() == self.addresses[COMPANY] and row[3].lower() == spec_hash.lower():
                return chain_bounty
        return None


def selector_words():
    return {A.run("cast", "sig", f"{name}()")[:10].lower(): (name, words) for name, words in CONTRACT_WORDS.items()}


SELECTORS = {}


def classify(output):
    """Maps a tool error to a plain message. It drops the tool's text, which can hold an RPC URL."""
    text = output.lower()
    if "insufficient funds" in text or "exceeds balance" in text or "insufficient balance" in text:
        return ArcError("empty_balance", "The sending wallet has too little test USDC. Get some at faucet.circle.com." + NOT_PAID)
    if "password" in text or "keystore" in text or "decrypt" in text:
        return ArcError("bad_keystore", "A keystore or its password did not open. Nothing was sent." + NOT_PAID)
    if not SELECTORS:
        SELECTORS.update(selector_words())
    for selector, (name, words) in SELECTORS.items():
        if selector in text or name.lower() in text:
            return ArcError("reverted", f"The contract refused this: {words}" + NOT_PAID)
    if "revert" in text:
        return ArcError("reverted", "The contract refused this transaction." + NOT_PAID)
    if any(word in text for word in ("timed out", "timeout", "connection", "connect", "dns", "unreachable", "error sending request", "http error")):
        return ArcError("rpc_down", "The Arc RPC did not answer. The next pass reads the chain again." + NOT_PAID)
    return ArcError("tool_failed", "A chain step failed. Nothing is marked as paid.")


def deployed(root):
    path = Path(root) / "arc.json"
    if not path.is_file():
        raise ArcError("not_deployed", "Arc is off: the contract is not deployed. Run arc_mirror.py deploy.")
    saved = json.loads(path.read_text())
    if saved["chain_id"] != CHAIN_ID:
        raise ArcError("wrong_network", "Refused: arc.json names another chain.")
    return saved


def plan_deploy(chain, root):
    """What deploy would do, read from the chain. It sends nothing."""
    try:
        A.run("forge", "build", "--root", str(A.CONTRACTS))
    except RuntimeError:
        raise ArcError("no_build", "forge build failed, so there is nothing to deploy. Nothing was sent.") from None
    code = json.loads((A.CONTRACTS / "out" / "FailureBounty.sol" / "FailureBounty.json").read_text())["bytecode"]["object"]
    return {"label": label_of(chain.real), "chain_id": CHAIN_ID, "rpc_host": urlsplit(chain.rpc).hostname, "contract": "FailureBounty", "bytecode_sha256": X.hashlib.sha256(code.encode()).hexdigest(), "token_usdc": USDC, "token_decimals": chain.read_int(USDC, "decimals()(uint8)"),
            "sender_company": chain.addresses[COMPANY], "balances_wei_native_view": {ROLES[i]: int(chain.run("cast", "balance", chain.addresses[i], "--rpc-url", chain.rpc)) for i in range(4)}, "already_deployed": (Path(root) / "arc.json").is_file(),
            "moves": "Gas only. It funds no bounty. Each bounty funds later, under ARC_CAP_USDC."}


def deploy(chain, root, yes):
    plan = plan_deploy(chain, root)
    print(json.dumps(plan, indent=1))
    if plan["already_deployed"]:
        raise ArcError("already_deployed", "Refused: arc.json already names a deployed contract. Nothing was sent.")
    if plan["token_decimals"] != 6:
        raise ArcError("wrong_token", "Refused: the USDC address does not report 6 decimals. Nothing was sent.")
    if not yes:
        print("Nothing was sent. Add --yes after the owner approves this plan.")
        return None
    chain.gas_ready(COMPANY)
    try:
        contract = chain.deploy("deploy_failure_bounty", "FailureBounty.sol/FailureBounty.json", "f(address)", USDC)
    except RuntimeError:
        raise ArcError("reverted", "The deploy transaction reverted. Nothing is deployed.") from None
    saved = {"label": label_of(chain.real), "chain_id": CHAIN_ID, "contract": contract, "token": USDC, "tx": chain.txs["deploy_failure_bounty"], "tx_link": tx_link(chain, chain.txs["deploy_failure_bounty"])}
    B.write_json(Path(root) / "arc.json", saved)
    print(json.dumps(saved, indent=1))
    return saved


def tx_link(chain, tx):
    return EXPLORER + tx if chain.real else None


SPEND_LOG = "arc_spend.jsonl"


def spend_rows(root):
    path = Path(root) / SPEND_LOG
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def cap_units():
    text = os.environ.get("ARC_CAP_USDC", "")
    if not text.isdigit() or int(text) < 1:
        raise ArcError("no_cap", "Arc will not fund anything: set ARC_CAP_USDC to a whole number of test USDC." + NOT_PAID)
    return int(text) * A.TOKEN_UNIT


def check_budget(root, info, pay):
    """Refuses before any send. The board's budget, when it has one, decides first: a stop stops the chain too."""
    saved = budget.view(root)
    if saved["funded"]:
        if saved["stopped"]:
            raise ArcError("budget_stopped", "The company pressed stop, so nothing new goes on chain." + NOT_PAID)
        if pay > saved["per_bounty_max"] * A.TOKEN_UNIT:
            raise ArcError("over_per_bounty", "This pay is above the budget's limit per bounty, so nothing was sent." + NOT_PAID)
    if info.get("posted_by") == "agent":
        held = (saved.get("by_bounty") or {}).get(str(info["id"]), {}).get("held", 0)
        if pay > held * A.TOKEN_UNIT:
            raise ArcError("budget_mismatch", "The budget does not hold this pay, so nothing was sent." + NOT_PAID)


def reserve(root, info, pay):
    """Counts this bounty against ARC_CAP_USDC in one lock, before the first send. A send that may have landed keeps its count."""
    cap = cap_units()
    with B.locked(Path(root) / ".arc.lock"):
        check_budget(root, info, pay)
        held = {}
        for row in spend_rows(root):
            held[row["bounty"]] = row["amount"] if row["kind"] == "reserve" else 0
        if held.get(info["id"]):
            return
        if sum(held.values()) + pay > cap:
            raise ArcError("over_cap", "This pay is above what is left of ARC_CAP_USDC, so nothing was sent." + NOT_PAID)
        _spend_row(root, "reserve", info["id"], pay)


def _spend_row(root, kind, bounty_id, amount):
    with open(Path(root) / SPEND_LOG, "a") as f:
        f.write(json.dumps({"at": time.time(), "kind": kind, "bounty": bounty_id, "amount": amount}) + "\n")


def create(chain, root, info, numbers, contract):
    pay, company = numbers["pay"], chain.addresses[COMPANY]
    if chain.read_int(USDC, "balanceOf(address)(uint256)", company) < pay:
        raise ArcError("empty_balance", "The company wallet holds less test USDC than this pay. Get some at faucet.circle.com." + NOT_PAID)
    reserve(root, info, pay)
    try:
        chain.send("approve", COMPANY, USDC, "approve(address,uint256)", contract, pay)
        chain.send("create_bounty", COMPANY, contract, A.CREATE_SIG, chain.addresses[RESOLVER], chain.addresses[ARBITER], numbers["spec_hash"], pay, pay, 0, chain.now() + A.DEADLINE_S, A.GRACE_S, numbers["window"])
    except ArcError as e:
        if e.code in ("reverted", "empty_balance", "bad_keystore"):
            _spend_row(root, "release", info["id"], pay)
        raise
    return chain.find_bounty(contract, numbers["spec_hash"])


def _budget_allows_new(root):
    saved = budget.view(root)
    if saved["funded"] and saved["stopped"]:
        raise ArcError("budget_stopped", "The company pressed stop, so nothing new goes on chain." + NOT_PAID)


def advance(chain, root, bounty_id, n, contract, record):
    """One pass for one fix: reads the chain, then makes at most the sends the chain state allows. A rejected local row never moves forward."""
    folder = X.folder_of(bounty_id, root)
    numbers = A.fix_numbers(folder, n)
    if not numbers:
        return False
    info = json.loads((folder / "pack.json").read_text())
    local = numbers["local_status"]
    rejected = local == "Rejected"
    record.update(fix=n, contract=contract, pay_base_units=numbers["pay"], result_hash=numbers["result_hash"], submitter=chain.addresses[TESTER])
    chain_bounty = chain.find_bounty(contract, numbers["spec_hash"])
    if chain_bounty is None:
        if rejected:
            return False
        chain_bounty = create(chain, root, info, numbers, contract)
        if chain_bounty is None:
            raise ArcError("create_missing", "The create went through, but the contract shows no such bounty." + NOT_PAID)
    fingerprint = A.fingerprint_on_chain(chain, chain_bounty, numbers["patched"])
    record.update(chain_bounty=chain_bounty, fingerprint=fingerprint)
    status, ends, submitter = chain.failure(chain_bounty, fingerprint, contract)
    record.update(state=status, dispute_ends_at=ends or None)
    moved = False
    if rejected:
        if status == "Pending":
            if chain.now() >= ends:
                raise ArcError("window_closed", "The local ledger rejected this fix, but the chain's dispute window has closed. It will not be finalized here." + NOT_PAID)
            chain.send("reject", ARBITER, contract, "reject(uint256,bytes32,bytes32)", chain_bounty, fingerprint, numbers["result_hash"])
            moved = True
    elif status == "None":
        _budget_allows_new(root)
        chain.send("propose", RESOLVER, contract, "propose(uint256,address,bytes32,bytes32,bool)", chain_bounty, chain.addresses[TESTER], fingerprint, numbers["result_hash"], "false")
        moved = True
    elif status == "Pending" and chain.now() >= ends:
        chain.send("finalize", RESOLVER, contract, "finalize(uint256,bytes32)", chain_bounty, fingerprint)
        moved = True
    elif status == "Finalized":
        if submitter != chain.addresses[TESTER]:
            raise ArcError("not_ours", "This payout names another tester wallet, so this process cannot claim it." + NOT_PAID)
        before = chain.read_int(USDC, "balanceOf(address)(uint256)", submitter)
        chain.send("claim", TESTER, contract, "claim(uint256,bytes32)", chain_bounty, fingerprint)
        record["paid_amount_seen"] = chain.read_int(USDC, "balanceOf(address)(uint256)", submitter) - before
        moved = True
    if moved:
        record["state"] = chain.failure(chain_bounty, fingerprint, contract)[0]
    record["paid"] = record["state"] == "Claimed"
    return moved


def sync(chain, root, bounty_id, n, contract):
    """Runs passes until the chain has nothing more to do now. It saves what happened in the fix's own file, and a failure saves a plain message with no payout.
    chain_mirror.json, which the page reads, follows the newest fix."""
    folder = X.folder_of(bounty_id, root)
    path = folder / "fixes" / str(n) / "chain.json"
    record = json.loads(path.read_text()) if path.is_file() else {}
    record.update(label=label_of(chain.real), chain_id=CHAIN_ID, txs=record.get("txs", {}), paid=record.get("paid", False), message=None)
    chain.txs = record["txs"]
    try:
        while advance(chain, root, bounty_id, n, contract, record):
            pass
    except ArcError as e:
        record["message"] = e.words
    record["tx_links"] = {name: tx_link(chain, tx) for name, tx in record["txs"].items() if tx_link(chain, tx)}
    B.write_json(path, record)
    shown = folder / "chain_mirror.json"
    saved = json.loads(shown.read_text()) if shown.is_file() else {}
    if saved.get("fix", n) <= n:  # A newer fix with no tx yet leaves the older txs on the page, with its own message.
        B.write_json(shown, {**saved, "message": record["message"]} if saved.get("txs") and not record["txs"] else record)
    return record


def accepted_fixes(root):
    """(bounty, n) for each accepted fix on the board, oldest first, so the newest record is what a page shows."""
    out = []
    for pack in sorted(Path(root).glob("*/pack.json"), key=lambda p: int(p.parent.name)):
        for fix in sorted((pack.parent / "fixes").glob("*/fix.json"), key=lambda p: int(p.parent.name)):
            if A.fix_numbers(pack.parent, int(fix.parent.name)):
                out.append((int(pack.parent.name), int(fix.parent.name)))
    return out


def fail_off_chain(root, bounty_id, words):
    """A failure before any chain read, such as a wrong network. The page says so, under a label that claims no chain."""
    folder = X.folder_of(bounty_id, root)
    path = folder / "chain_mirror.json"
    record = json.loads(path.read_text()) if path.is_file() else {"txs": {}, "tx_links": {}, "chain_id": None, "paid": False, "state": None}
    if not record["txs"]:
        record["label"] = LABEL_OFF
    B.write_json(path, {**record, "message": words})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("deploy", "sync", "serve"))
    ap.add_argument("--root", default=str(B.ROOT))
    ap.add_argument("--bounty", type=int)
    ap.add_argument("--fix", type=int)
    ap.add_argument("--yes", action="store_true", help="deploy only: send after the owner approves the printed plan")
    ap.add_argument("--every", type=float, default=10)
    a = ap.parse_args()
    root = Path(a.root)
    try:
        refuse_keys_in_env()
        chain = ArcChain(os.environ.get("ARC_RPC_URL", ""), Wallets(os.environ.get("ARC_WALLET_DIR")))
        if a.command == "deploy":
            deploy(chain, root, a.yes)
            return 0
        saved = deployed(root)
        if saved["label"] != label_of(chain.real):
            raise ArcError("wrong_network", "Refused: arc.json was written for another network than this RPC. Nothing was sent." + NOT_PAID)
        contract = saved["contract"]
    except ArcError as e:
        print(e.words)
        if a.bounty is not None:
            fail_off_chain(root, a.bounty, e.words)
        return 1
    if a.command == "sync":
        record = sync(chain, root, a.bounty, a.fix, contract)
        print(json.dumps({k: record.get(k) for k in ("label", "state", "paid", "message", "tx_links", "txs")}, indent=1))
        return 1 if record["message"] else 0
    print(f"{label_of(chain.real)} Watching {root}. It reads the chain every {a.every} s. Stop with Ctrl-C.", flush=True)
    while True:
        for bounty_id, n in accepted_fixes(root):
            try:
                record = sync(chain, root, bounty_id, n, contract)
            except ArcError as e:
                print(f"bounty {bounty_id} fix {n}: {e.words}", flush=True)
                continue
            print(f"bounty {bounty_id} fix {n}: {record['state']}. {record['message'] or ''}", flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
