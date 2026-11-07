"""The wallet flow on Arc testnet: the company funds from its own wallet, the CrashLab agent proposes, finalizes and pays, and the engineer signs once to prove a wallet.

arc_wallet.py deploy [--yes] | check | serve | seed-campaign | record-proof --bounty ID --fix N. All take --root DIR. Steps: docs/ARC-DEMO.md.

Arc testnet only: chain 5042002 on its public RPC hosts, or loopback for the local check. arc_mirror.py's check_rpc and chain-id guard run before every send, so no mainnet path exists.
Keys: serve is the only process that opens a keystore, and it opens only resolver and arbiter from ARC_WALLET_DIR. The web server imports the read-only half of this file. It reads receipts and checks signatures.
The page shows a step only from a receipt or a contract read. Code decides from the gate's result, and no AI takes part. Results stay simulated: a payout says nothing about a real robot.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anvil_mirror as A
import arc_mirror as M
import board_fix as X
import board_store as B

ON_ENV = "CRASHLAB_ARC"
DEMO_ENV = "CRASHLAB_ARC_DEMO"
LABEL_ARC = "Arc testnet. Test USDC, not real money."
LABEL_LOCAL = "Local stand-in chain. Not Arc. Not real money."
RECORDED_LABEL = "The result comes from a recorded batch. The chain transactions are real."
AGENT_NAME = "CrashLab agent"
ROLES = ("resolver", "arbiter")
RESOLVER, ARBITER = range(2)
EVENT_CREATED = "BountyCreated(uint256,address,address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64)"
EVENT_CLAIMED = "FailureClaimed(uint256,bytes32,address,uint256)"
BOUNTY_READ = "bounties(uint256)(address,address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64,bool)"
TX = re.compile(r"0x[0-9a-fA-F]{64}")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
SIGNATURE = re.compile(r"0x[0-9a-fA-F]{130}")
CONFIG_TTL_S = 20
DEMO_FIX = HERE / "fixtures" / "fix5" / "good_match_fan.py"
DEMO_GROUP = "stalled"
DEMO_SESSION = "0000000000000000000000000a4c0001"
REJECT_LATE = "The company's signed rejection did not reach the chain in the dispute window, so the agent will not finalize or pay this fix. The contract still lets anyone finalize, and the engineer can then claim."


class Reader(M.ArcChain):
    """The chain with no wallet: receipts, contract reads and the chain-id check."""

    def __init__(self, rpc):
        self.real = M.check_rpc(rpc)
        self.rpc, self.txs, self.fee = rpc, {}, None
        self.guard()

    def receipt(self, tx):
        """The receipt, or None while the chain has no receipt for this hash."""
        if not (isinstance(tx, str) and TX.fullmatch(tx)):
            raise B.BoardError("bad_tx", "That is not a transaction hash.")
        return json.loads(self.run("cast", "rpc", "--rpc-url", self.rpc, "eth_getTransactionReceipt", tx))


class Agent(Reader):
    """Holds the resolver and arbiter keystores. Only serve and deploy make one."""

    def __init__(self, rpc, wallets):
        M.ArcChain.__init__(self, rpc, wallets)


def _rpc_url():
    return os.environ.get("ARC_RPC_URL", "")


def label_of(real):
    return LABEL_ARC if real else LABEL_LOCAL


def tx_link(real, tx):
    return M.EXPLORER + tx if real and tx else None


def deployment(root):
    path = Path(root) / "arc.json"
    if not path.is_file():
        raise M.ArcError("not_deployed", "Arc is off: the contract is not deployed. Run arc_wallet.py deploy.")
    saved = json.loads(path.read_text())
    if saved.get("chain_id") != M.CHAIN_ID or not saved.get("resolver"):
        raise M.ArcError("wrong_deploy", "Refused: arc.json was not written by arc_wallet.py deploy for this chain.")
    return saved


_config = {}


def config(root):
    """What the page needs, cached a few seconds, since every step asks. It holds nothing secret."""
    root = str(root)
    if os.environ.get(ON_ENV) != "1":  # The hosted site has no chain, but its recorded path still offers the stored campaign and the stored good fix.
        return {"on": False, "demo": True, "demo_session": DEMO_SESSION} if os.environ.get(DEMO_ENV) == "1" else {"on": False}
    held = _config.get(root)
    if held and held[0] > time.time():
        return held[1]
    try:
        M.refuse_keys_in_env()
        saved = deployment(root)
        reader = Reader(_rpc_url())
        M.cap_units()
        real = reader.real
        if saved["label"] != label_of(real):
            raise M.ArcError("wrong_network", "Refused: arc.json was written for another network than this RPC.")
        value = {"on": True, "label": label_of(real), "real": real, "chain_id": M.CHAIN_ID, "chain_hex": hex(M.CHAIN_ID), "rpc_url": _rpc_url(), "explorer": M.EXPLORER if real else None, "explorer_home": M.EXPLORER.removesuffix("/tx/") if real else None, "usdc": M.USDC, "contract": saved["contract"], "resolver": saved["resolver"], "arbiter": saved["arbiter"],
                 "agent_name": AGENT_NAME, "cap_usdc": M.cap_units() // A.TOKEN_UNIT, "demo": os.environ.get(DEMO_ENV) == "1", "demo_session": DEMO_SESSION, "recorded_label": RECORDED_LABEL, "deploy_tx": saved.get("tx")}
    except M.ArcError as e:
        value = {"on": False, "asked": True, "reason": e.words}
    _config[root] = (time.time() + CONFIG_TTL_S, value)
    return value


def need_on(root):
    value = config(root)
    if not value["on"]:
        raise B.BoardError("arc_off", value.get("reason") or "Arc is off on this board.")
    return value


def reader():
    return Reader(_rpc_url())


def balances(address, root):
    """The wallet's money, read from the chain now."""
    value = need_on(root)
    chain = reader()
    with ThreadPoolExecutor(3) as pool:  # Three chain reads at once, so the page does not wait for them in turn.
        usdc = pool.submit(chain.read_int, M.USDC, "balanceOf(address)(uint256)", address)
        gas = pool.submit(chain.run, "cast", "balance", address, "--rpc-url", chain.rpc)
        allowance = pool.submit(chain.read_int, M.USDC, "allowance(address,address)(uint256)", address, value["contract"])
    return {"address": address.lower(), "usdc_base_units": str(usdc.result()), "gas_wei": gas.result(), "allowance_base_units": str(allowance.result()), "read_at_block": int(chain.run("cast", "block-number", "--rpc-url", chain.rpc))}


def signer_ok(address, message, signature):
    """True only if this address signed this message. cast applies the personal_sign prefix."""
    if not (isinstance(signature, str) and SIGNATURE.fullmatch(signature) and ADDRESS.fullmatch(address)):
        return False
    return subprocess.run(["cast", "wallet", "verify", "--address", address, message, signature], capture_output=True, timeout=30).returncode == 0


def funding_of(folder):
    path = folder / "arc_funding.json"
    return json.loads(path.read_text()) if path.is_file() else None


def steps_path(folder, n):
    return folder / "fixes" / str(n) / "arc_steps.json"


def steps_of(folder, n):
    path = steps_path(folder, n)
    return json.loads(path.read_text()) if path.is_file() else {"txs": {}, "tx_links": {}, "state": None, "message": None}


def save_steps(folder, n, steps, real):
    steps["tx_links"] = {name: tx_link(real, tx) for name, tx in steps["txs"].items() if tx_link(real, tx)}
    B.write_json(steps_path(folder, n), steps)


def funded_total(root, leave_out=None):
    total = 0
    for path in Path(root).glob("*/arc_funding.json"):
        if path.parent.name != str(leave_out):
            total += json.loads(path.read_text())["cap_base_units"]
    return total


def check_cap(root, bounty_id, pay):
    """Refuses before any send. ARC_CAP_USDC bounds all money this board puts on chain, and the board's budget can stop it."""
    info = json.loads((X.folder_of(bounty_id, root) / "pack.json").read_text())
    M.check_budget(root, info, pay)
    if funded_total(root, bounty_id) + pay > M.cap_units():
        raise M.ArcError("over_cap", "This pay is above what is left of ARC_CAP_USDC, so nothing was sent." + M.NOT_PAID)


def plan_deadlines(folder):
    path = folder / "arc_plan.json"
    return json.loads(path.read_text())["deadlines"] if path.is_file() else []


def fund_plan(bounty_id, root):
    """The exact call the company's wallet sends. The server chooses every field, then checks the receipt against them."""
    value = need_on(root)
    folder = X.folder_of(bounty_id, root)
    if funding_of(folder):
        raise B.BoardError("already_funded", "This bounty is already funded on chain.")
    money = json.loads((folder / "ledger.json").read_text())["bounty"]
    pay = money["per_failure"] * A.TOKEN_UNIT
    check_cap(root, bounty_id, pay)
    chain = reader()
    deadline = chain.now() + A.DEADLINE_S
    with B.locked(folder / ".lock"):
        B.write_json(folder / "arc_plan.json", {"deadlines": plan_deadlines(folder) + [deadline]})
    # The approval covers this board's whole ARC_CAP_USDC, never more, so later bounties need one popup. The spender stays this board's contract. check_cap above has already bounded pay by the cap.
    return {"contract": value["contract"], "usdc": M.USDC, "resolver": value["resolver"], "arbiter": value["arbiter"], "spec_hash": money["spec_hash"], "cap": str(pay), "approve": str(M.cap_units()), "per_failure": str(pay), "top_prize": "0",
            "deadline": str(deadline), "grace": str(A.GRACE_S), "dispute_window": str(money["dispute_window_s"]), "fee_wei": str(chain.fee_wei()), "chain_hex": value["chain_hex"]}


def _word(data, i):
    return data[2:][64 * i:64 * (i + 1)]


def _address_word(word):
    return "0x" + word[-40:].lower()


def verify_funded(bounty_id, create_tx, approve_tx, root):
    """Stores the chain bounty only after its receipt and the contract both agree with this board's spec. Returns None while the chain has no receipt yet."""
    value = need_on(root)
    folder = X.folder_of(bounty_id, root)
    chain = reader()
    got = chain.receipt(create_tx)
    if got is None:
        return None
    if int(got["status"], 16) != 1:
        raise B.BoardError("tx_reverted", "That transaction reverted on chain, so this bounty is not funded.")
    money = json.loads((folder / "ledger.json").read_text())["bounty"]
    pay = money["per_failure"] * A.TOKEN_UNIT
    topic = chain.run("cast", "sig-event", EVENT_CREATED).lower()
    logs = [e for e in got["logs"] if e["address"].lower() == value["contract"].lower() and e["topics"][0].lower() == topic]
    if (got.get("to") or "").lower() != value["contract"].lower() or len(logs) != 1:
        raise B.BoardError("tx_not_funding", "That transaction did not create a bounty on this contract.")
    log = logs[0]
    chain_bounty, company = int(log["topics"][1], 16), _address_word(log["topics"][2])
    data = log["data"]
    deadline = int(_word(data, 6), 16)
    fields = {"resolver": _address_word(_word(data, 0)), "arbiter": _address_word(_word(data, 1)), "spec": "0x" + _word(data, 2), "cap": int(_word(data, 3), 16), "per": int(_word(data, 4), 16), "top": int(_word(data, 5), 16), "refund_opens": int(_word(data, 7), 16), "window": int(_word(data, 8), 16)}
    want = {"resolver": value["resolver"].lower(), "arbiter": value["arbiter"].lower(), "spec": money["spec_hash"].lower(), "cap": pay, "per": pay, "top": 0, "refund_opens": deadline + A.GRACE_S, "window": money["dispute_window_s"]}
    if fields != want or deadline not in plan_deadlines(folder):
        raise B.BoardError("tx_wrong_fields", "That bounty's roles, spec, amounts or times differ from this board's plan, so it does not fund this bounty.")
    row = chain.read(value["contract"], BOUNTY_READ, chain_bounty).split("\n")
    if row[0].lower() != company or row[3].lower() != money["spec_hash"].lower():
        raise B.BoardError("tx_wrong_fields", "The contract does not hold this bounty as the receipt says.")
    txs = {"create_bounty": create_tx}
    if approve_tx:
        seen = chain.receipt(approve_tx)
        if seen and int(seen["status"], 16) == 1 and (seen.get("to") or "").lower() == M.USDC.lower() and seen["from"].lower() == company:
            txs["approve"] = approve_tx
    with B.locked(folder / ".lock"):
        held = funding_of(folder)
        if held:
            if held["txs"]["create_bounty"] == create_tx:
                return held
            raise B.BoardError("already_funded", "This bounty is already funded on chain.")
        check_cap(root, bounty_id, pay)
        saved = {"label": value["label"], "chain_bounty": chain_bounty, "company": company, "contract": value["contract"], "cap_base_units": pay, "txs": txs, "tx_links": {k: tx_link(chain.real, v) for k, v in txs.items() if tx_link(chain.real, v)}, "at": time.time()}
        B.write_json(folder / "arc_funding.json", saved)
    return saved


def wallet_for_submit(bounty_id, session, root):
    """None when Arc is off, so the local path stays as it was. With Arc on, a fix needs money on chain and a wallet the engineer proved."""
    if not config(root)["on"]:
        return None
    if not funding_of(X.folder_of(bounty_id, root)):
        raise B.BoardError("not_funded", "The company has not funded this bounty on chain yet, so a fix cannot earn anything.")
    if not (session.get("payout") and session.get("payout_signed")):
        raise B.BoardError("no_wallet", "Save your wallet first: connect it and sign the message. The CrashLab agent pays only a wallet you proved.")
    return session["payout"].lower()


def reject_message(bounty_id, n, nonce):
    return f"CrashLab bounty board\nReject fix {n} of bounty {bounty_id} on the chain, during the dispute window.\nThis signature costs nothing and sends no transaction.\nNonce: {nonce}"


def wallet_message(tester, address, nonce):
    return f"CrashLab bounty board\nI own this wallet, and I want bounty pay sent to it.\nEngineer: {tester}\nWallet: {address.lower()}\nThis signature costs nothing and sends no transaction.\nNonce: {nonce}"


def request_reject(bounty_id, n, nonce, signature, root):
    """The company signs, and the agent's arbiter key sends, because the contract lets only the arbiter reject and the company cannot be its own arbiter."""
    need_on(root)
    folder = X.folder_of(bounty_id, root)
    funding = funding_of(folder)
    steps = steps_of(folder, n)
    if not funding or steps.get("state") != "Pending" or reader().now() >= (steps.get("dispute_ends_at") or 0):
        raise B.BoardError("wrong_state", "This fix is not in its dispute window on chain.")
    if not signer_ok(funding["company"], reject_message(bounty_id, n, nonce), signature):
        raise B.BoardError("bad_signature", "That signature is not from the wallet that funded this bounty. Connect that wallet and try again.")
    B.write_json(folder / "fixes" / str(n) / "arc_reject.json", {"nonce": nonce, "signature": signature, "at": time.time()})


def record_claim(bounty_id, n, tx, root):
    """The engineer's fallback, for a stuck agent. Saved only from a good receipt that holds this fix's claim event."""
    value = need_on(root)
    folder = X.folder_of(bounty_id, root)
    steps, funding = steps_of(folder, n), funding_of(folder)
    chain = reader()
    got = chain.receipt(tx)
    if got is None:
        return None
    if int(got["status"], 16) != 1:
        raise B.BoardError("tx_reverted", "That claim reverted on chain, so nothing was paid.")
    topic = chain.run("cast", "sig-event", EVENT_CLAIMED).lower()
    good = [e for e in got["logs"] if e["address"].lower() == value["contract"].lower() and e["topics"][0].lower() == topic and funding and int(e["topics"][1], 16) == funding["chain_bounty"] and e["topics"][2].lower() == (steps.get("fingerprint") or "").lower()]
    if not good:
        raise B.BoardError("tx_not_claim", "That transaction did not pay this fix.")
    steps["txs"]["claim"] = tx
    steps.update(state="Claimed", paid=True, paid_by="wallet", balance_after=chain.read_int(M.USDC, "balanceOf(address)(uint256)", steps["submitter"]))
    save_steps(folder, n, steps, chain.real)
    return steps


def advance(chain, root, bounty_id, n, contract):
    """One pass for one fix: read the chain, then make at most the one send its state allows. A crash or a retry cannot pay twice, because the contract holds the state."""
    folder = X.folder_of(bounty_id, root)
    funding = funding_of(folder)
    row = json.loads((folder / "fixes" / str(n) / "fix.json").read_text())
    numbers = A.fix_numbers(folder, n)
    if not (funding and numbers and row.get("wallet")):
        return False
    steps = steps_of(folder, n)
    chain.txs = steps["txs"]
    chain_bounty, wallet = funding["chain_bounty"], row["wallet"]
    fingerprint = A.fingerprint_on_chain(chain, chain_bounty, numbers["patched"])
    status, ends, submitter = chain.failure(chain_bounty, fingerprint, contract)
    steps.update(fix=n, chain_bounty=chain_bounty, fingerprint=fingerprint, submitter=wallet, amount_base_units=numbers["pay"], state=status if status != "None" else None, dispute_ends_at=ends or None, recorded=bool(row["result"].get("recorded")), message=None, chain_now=chain.now(), chain_read_at=time.time())
    moved = False
    request = folder / "fixes" / str(n) / "arc_reject.json"
    if status == "None":
        check_cap(root, bounty_id, numbers["pay"])
        on_chain = chain.read(contract, BOUNTY_READ, chain_bounty).split("\n")
        if on_chain[1].lower() != chain.addresses[RESOLVER] or on_chain[2].lower() != chain.addresses[ARBITER] or on_chain[3].lower() != numbers["spec_hash"].lower():
            raise M.ArcError("wrong_bounty", "The chain bounty names other roles or another spec, so the agent sent nothing." + M.NOT_PAID)
        steps["balance_before"] = chain.read_int(M.USDC, "balanceOf(address)(uint256)", wallet)
        chain.send("propose", RESOLVER, contract, "propose(uint256,address,bytes32,bytes32,bool)", chain_bounty, wallet, fingerprint, numbers["result_hash"], "false")
        moved = True
    elif status in ("Pending", "Finalized") and request.is_file() and (status == "Finalized" or chain.now() >= ends):
        steps["message"] = REJECT_LATE
    elif status == "Pending":
        if request.is_file():
            asked = json.loads(request.read_text())
            if not signer_ok(funding["company"], reject_message(bounty_id, n, asked["nonce"]), asked["signature"]):
                raise M.ArcError("bad_signature", "The reject request has no good signature from the company's wallet, so the arbiter sent nothing." + M.NOT_PAID)
            chain.send("reject", ARBITER, contract, "reject(uint256,bytes32,bytes32)", chain_bounty, fingerprint, numbers["result_hash"])
            moved = True
        elif chain.now() >= ends:
            chain.send("finalize", RESOLVER, contract, "finalize(uint256,bytes32)", chain_bounty, fingerprint)
            moved = True
    elif status == "Finalized":
        if submitter != wallet:
            raise M.ArcError("not_ours", "The contract names another wallet than this fix's, so the agent sent nothing." + M.NOT_PAID)
        chain.send("payout", RESOLVER, contract, "payout(uint256,bytes32)", chain_bounty, fingerprint)
        steps.update(paid_by="agent", balance_after=chain.read_int(M.USDC, "balanceOf(address)(uint256)", wallet))
        moved = True
    elif status == "Rejected" and not steps.get("ledger_rejected"):
        try:
            X.ledger_step(bounty_id, n, "chain_reject", root=root)
            steps["ledger_rejected"] = True
        except B.BoardError:
            steps["ledger_rejected"] = False
    if moved:
        status, ends, _ = chain.failure(chain_bounty, fingerprint, contract)
        steps.update(state=status, dispute_ends_at=ends or None)
    steps["paid"] = steps.get("state") == "Claimed"
    save_steps(folder, n, steps, chain.real)
    return moved


def sync_all(chain, root, contract):
    for pack in sorted(Path(root).glob("*/arc_funding.json"), key=lambda p: int(p.parent.name)):
        bounty_id = int(pack.parent.name)
        for fix in sorted((pack.parent / "fixes").glob("*/fix.json"), key=lambda p: int(p.parent.name)):
            n = int(fix.parent.name)
            try:
                while advance(chain, root, bounty_id, n, contract):
                    pass
            except M.ArcError as e:
                steps = steps_of(pack.parent, n)
                steps.update(message=e.words, stuck_at=steps.get("stuck_at") or time.time())
                save_steps(pack.parent, n, steps, chain.real)
                print(f"bounty {bounty_id} fix {n}: {e.words}", flush=True)


def agent_chain():
    M.refuse_keys_in_env()
    return Agent(_rpc_url(), M.Wallets(os.environ.get("ARC_WALLET_DIR"), roles=ROLES))


def deploy(root, yes):
    chain = agent_chain()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        A.run("forge", "build", "--root", str(A.CONTRACTS))
    except RuntimeError:
        raise M.ArcError("no_build", "forge build failed, so there is nothing to deploy. Nothing was sent.") from None
    code = json.loads((A.CONTRACTS / "out" / "FailureBounty.sol" / "FailureBounty.json").read_text())["bytecode"]["object"]
    plan = {"label": label_of(chain.real), "chain_id": M.CHAIN_ID, "rpc_host": urlsplit(chain.rpc).hostname, "contract": "FailureBounty", "bytecode_sha256": X.hashlib.sha256(code.encode()).hexdigest(), "token_usdc": M.USDC, "token_decimals": chain.read_int(M.USDC, "decimals()(uint8)"),
            "sender_resolver": chain.addresses[RESOLVER], "arbiter": chain.addresses[ARBITER], "balances_wei_native_view": {ROLES[i]: int(chain.run("cast", "balance", chain.addresses[i], "--rpc-url", chain.rpc)) for i in range(2)}, "already_deployed": (root / "arc.json").is_file(), "writes": str(root / "arc.json"),
            "moves": "Gas only. It funds no bounty."}
    print(json.dumps(plan, indent=1))
    if plan["already_deployed"]:
        raise M.ArcError("already_deployed", "Refused: arc.json already names a deployed contract here. Nothing was sent.")
    if plan["token_decimals"] != 6:
        raise M.ArcError("wrong_token", "Refused: the USDC address does not report 6 decimals. Nothing was sent.")
    if not yes:
        print("Nothing was sent. Add --yes after the owner approves this plan.")
        return
    chain.gas_ready(RESOLVER)
    try:
        contract = chain.deploy("deploy_failure_bounty", "FailureBounty.sol/FailureBounty.json", "f(address)", M.USDC)
    except RuntimeError:
        raise M.ArcError("reverted", "The deploy transaction reverted. Nothing is deployed.") from None
    tx = chain.txs["deploy_failure_bounty"]
    saved = {"label": label_of(chain.real), "chain_id": M.CHAIN_ID, "contract": contract, "token": M.USDC, "tx": tx, "tx_link": tx_link(chain.real, tx), "resolver": chain.addresses[RESOLVER], "arbiter": chain.addresses[ARBITER]}
    B.write_json(root / "arc.json", saved)
    print(json.dumps(saved, indent=1))


def seed_campaign():
    """The recorded window batch as one finished campaign, so a film can post a bounty without first playing the grid. It holds stored results and says so."""
    import types
    sys.path.insert(0, str(X.POLICY / "server"))
    import recorded_batch as R
    out = X.SERVER_RUNS / DEMO_SESSION
    if (out / "campaigns" / "c1" / "grid.json").is_file():
        return
    R.PLAY_S = 0
    quiet = lambda *a, **k: None  # noqa: E731
    s = types.SimpleNamespace(pack="window", dir=out, campaign_n=0, pending_campaign=None, pending_base=None, live_campaign=None, emit=quiet, say=quiet, working=quiet, set_grid=quiet)
    out.mkdir(parents=True, exist_ok=True)
    folder = X.POLICY / "runs" / "demo"
    R.list_scenarios(s, folder)
    R.run_campaign(s, folder)


def record_proof(root, bounty_id, n):
    """Keeps one real gate result for the film, with what it must match. It takes only a result that a real proof made here."""
    import board_fix_gate as G
    folder = X.folder_of(bounty_id, root)
    row = json.loads((folder / "fixes" / str(n) / "fix.json").read_text())
    if not row["result"] or row["result"]["code"] != "accepted" or row["result"].get("recorded"):
        raise SystemExit("Only a fix a real proof accepted can be stored.")
    if row["source_sha256"] != X.hashlib.sha256(DEMO_FIX.read_bytes()).hexdigest():
        raise SystemExit("Only the stored good fix can be stored.")
    info, hidden = json.loads((folder / "pack.json").read_text()), json.loads((folder / "hidden.json").read_text())
    G.STORED_PROOF.write_text(json.dumps({"note": "One real gate run of fixtures/fix5/good_match_fan.py on the recorded window batch. Simulated.", "key": G.proof_key(row, info, hidden), "wall_s": row.get("wall_s"), "result": row["result"]}, indent=1) + "\n")
    print(f"Saved {G.STORED_PROOF}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("deploy", "check", "serve", "seed-campaign", "record-proof"))
    ap.add_argument("--root", default=str(B.ROOT))
    ap.add_argument("--yes", action="store_true", help="deploy only: send after the owner approves the printed plan")
    ap.add_argument("--every", type=float, default=2)
    ap.add_argument("--bounty", type=int)
    ap.add_argument("--fix", type=int)
    a = ap.parse_args()
    root = Path(a.root).resolve()
    try:
        if a.command == "seed-campaign":
            seed_campaign()
            return 0
        if a.command == "record-proof":
            record_proof(root, a.bounty, a.fix)
            return 0
        if a.command == "deploy":
            deploy(root, a.yes)
            return 0
        chain = agent_chain()
        saved = deployment(root)
        M.cap_units()
        if saved["label"] != label_of(chain.real) or saved["resolver"] != chain.addresses[RESOLVER] or saved["arbiter"] != chain.addresses[ARBITER]:
            raise M.ArcError("wrong_deploy", "Refused: arc.json names another network or other wallets than ARC_RPC_URL and ARC_WALLET_DIR.")
        chain.gas_ready(ARBITER)
        if a.command == "check":
            print(f"{label_of(chain.real)} Ready. Contract {saved['contract']}. {AGENT_NAME}: {chain.addresses[RESOLVER]}.")
            return 0
    except M.ArcError as e:
        print(e.words)
        return 1
    print(f"{label_of(chain.real)} {AGENT_NAME} watches {root} every {a.every} s. Stop with Ctrl-C.", flush=True)
    while True:
        chain.fee = None
        try:
            sync_all(chain, root, saved["contract"])
        except M.ArcError as e:
            print(e.words, flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
