"""Local checks of the 0G, World ID and Arc switch-on code: check_sponsors.py [--only off|0g|world|arc] [--no-sim]. Exit 0 only if all pass.

ALL OF THIS IS LOCAL. 0G and World ID are mock servers in mocks/. The chain is anvil, a standard EVM, with MockUSDC placed at the Arc USDC address. No sponsor gets a call, and no real key, proof or money is involved.
The contract, Deploy script, resolver, gate, store and IDKit signing and hashing code are the real ones. The gate step runs the real sim unless --no-sim.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
ROOT = POLICY.parent
PYTHON = str(POLICY / ".venv" / "bin" / "python")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "mocks"))
import sponsor_status as status
import world_id
import world_store
import zg_receipts

failed = 0
MOCK_PORT, ANVIL_PORT = 8846, 8845
CLEAN = {k: v for k, v in os.environ.items() if not k.startswith(("ZG_", "WORLD_", "ARC_", "CRASHLAB_LLM"))}
MOCK_KEY = "mock-zg-key-not-a-secret"


def check(name, ok, detail=""):
    global failed
    failed += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def rejected(code, fn):
    try:
        fn()
    except world_id.Rejected as e:
        return e.code == code
    return False


class Mock:
    def __enter__(self):
        self.p = subprocess.Popen([PYTHON, str(HERE / "mocks" / "mock_sponsors.py"), "--port", str(MOCK_PORT)])
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{MOCK_PORT}/x", timeout=1)
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.1)
        return self

    def __exit__(self, *_):
        self.p.terminate()
        self.p.wait()


def llm_child(env, code="""
import json, sys
sys.path.insert(0, 'policy/crashlab')
import llm
try:
    print(json.dumps({'reply': llm.complete_json('p', {'type': 'object', 'properties': {'groups': {}}})}))
except llm.LLMError as e:
    print(json.dumps({'error': str(e)}))
"""):
    done = subprocess.run([PYTHON, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return json.loads(done.stdout.strip().splitlines()[-1]), done.stderr


def zg_env(receipts, model="mock-good", sdk=True):
    env = {**CLEAN, "CRASHLAB_LLM": "0g", "ZG_API_KEY": MOCK_KEY, "ZG_MODEL": model, "ZG_ROUTER_URL": f"http://127.0.0.1:{MOCK_PORT}/v1", "CRASHLAB_LLM_RECEIPTS": str(receipts)}
    if sdk:
        env.update(ZG_SDK_MODULE=str(HERE / "mocks" / "mock_zg_sdk.mjs"), ZG_ETHERS_MODULE=str(HERE / "mocks" / "mock_ethers.mjs"))
    return env


def check_off():
    print("-- no keys: every label says off")
    empty = {}
    check("LLM is plain Claude", status.llm_status(empty)["label"] == "claude headless")
    check("World ID label", status.world_status(empty)["label"] == "World ID not connected", ", ".join(status.world_status(empty)["missing"]))
    check("Arc is off, local ledger label", not status.arc_status(empty)["on"] and status.arc_status(empty)["label"] == "Local ledger. Not on chain.")
    half = status.llm_status({"CRASHLAB_LLM": "0g"})
    check("0G chosen with no key names the fallback and the missing names", half["backend"] == "claude" and "ZG_API_KEY" in half["label"] and "claude headless" in half["label"], half["label"])
    refused = status.arc_status({"ARC_RESOLVER_KEYSTORE": "/x"})
    check("Arc refuses when a signing key path reaches the web env", not refused["on"] and "ARC_RESOLVER_KEYSTORE" in refused["reason"], refused["reason"])
    scrubbed = status.child_env(env={"ZG_API_KEY": "a", "WORLD_RP_SIGNING_KEY": "b", "ARC_RESOLVER_KEYSTORE": "c", "PATH": "d"})
    check("children get no secrets by default", scrubbed == {"PATH": "d"})
    check("server and llm never read a signer var by name", all(not re.search(r"ARC_\w+_(KEYSTORE|PASSWORD_FILE)", (ROOT / f).read_text()) for f in ("policy/server/server.py", "policy/crashlab/llm.py", "policy/sponsors/chain.py")))
    check("resolver imports no LLM or web code", not re.search(r"^\s*(import|from)\s+(llm|server|plan_job)\b", (HERE / "resolver.py").read_text(), re.M))
    ignored = subprocess.run(["git", "check-ignore", ".env", ".env.resolver", ".env.tester"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    check(".env files are ignored by git", ignored == [".env", ".env.resolver", ".env.tester"])
    if (ROOT / ".env.example").exists():
        lines = [l for l in (ROOT / ".env.example").read_text().splitlines() if l and not l.startswith("#")]
        check(".env.example holds names only", lines and all(re.fullmatch(r"[A-Z0-9_]+=", l) for l in lines), f"{len(lines)} names")


def check_zg():
    print("-- 0G backend B. MOCK Router and MOCK SDK")
    with Mock(), tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "r.jsonl"
        out, _ = llm_child(zg_env(path))
        check("a good call returns the parsed object through complete_json", isinstance(out.get("reply"), dict), str(list(out.get("reply", out))[:3]))
        row = json.loads(path.read_text().splitlines()[-1])
        check("the receipt holds the request id, provider and processResponse true", row["backend"] == "0g" and len(row["request_id"]) == 32 and row["process_response"] is True and row["chat_id"].startswith("chat-"))
        check("the API key is not in the receipts", MOCK_KEY not in path.read_text())
        for model, code in (("mock-sig-bad", "tee_check_failed"), ("mock-router-false", "tee_check_failed"), ("mock-not-json", "not_json"), ("mock-duplicate-keys", "not_json"), ("mock-no-provider", "no_private_provider")):
            out, _ = llm_child(zg_env(path, model))
            check(f"{model} is refused with {code}", out.get("error") == code, str(out)[:80])
        path2 = Path(folder) / "null.jsonl"
        out, _ = llm_child(zg_env(path2, "mock-no-tee"))
        s = zg_receipts.summary(path2)
        check("processResponse null: the answer stands but it does not count as checked", "reply" in out and s["checked"] == 0 and s["not_checked"] == 1, s["line"])
        path3 = Path(folder) / "throw.jsonl"
        llm_child(zg_env(path3, "mock-check-throws"))
        check("a check that throws counts as not checked", zg_receipts.summary(path3)["checked"] == 0 and json.loads(path3.read_text())["process_response"] == "unavailable")
        path4 = Path(folder) / "nosdk.jsonl"
        env = zg_env(path4, sdk=False)
        env["ZG_SDK_MODULE"] = "/nonexistent/sdk.mjs"
        llm_child(env)
        check("no SDK installed counts as not checked, never as verified", json.loads(path4.read_text())["process_response"] == "unavailable")
        s = zg_receipts.summary(path)
        check("the status line counts a signature as checked only with no refusal", (s["checked"], s["failed"], s["not_checked"]) == (3, 2, 0), s["line"])
        check("the limits say what a receipt does not prove", "does not show that the signature covers the prompt" in s["limits"])
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        check("receipts form a hash chain", all(b["previous"] == a["hash"] for a, b in zip(rows, rows[1:])) and s["commit"] == rows[-1]["hash"])
        env = {**zg_env(path), "ZG_ROUTER_URL": "http://evil.example/v1"}
        out, _ = llm_child(env)
        check("the key is never sent over plain HTTP to another host", out.get("error") == "router_not_https")
        missing = {**CLEAN, "CRASHLAB_LLM": "0g", "CRASHLAB_LLM_RECEIPTS": str(Path(folder) / "m.jsonl")}
        code = """
import json, sys
sys.path.insert(0, 'policy/crashlab')
import llm
llm.BACKENDS['claude'] = lambda p, s: {'stub': 'no paid call'}
print(json.dumps({'reply': llm.complete_json('p', {})}))
"""
        out, err = llm_child(missing, code)
        row = json.loads((Path(folder) / "m.jsonl").read_text())
        check("missing key: falls back to Claude (stubbed here), says so on stderr, and the receipt names it", out["reply"] == {"stub": "no paid call"} and "0G is off" in err and row["backend"] == "claude", err.strip())


def world_env(db, cap="3"):
    return {**CLEAN, "WORLD_APP_ID": "app_staging_mock", "WORLD_RP_ID": "rp_mock", "WORLD_RP_SIGNING_KEY": "0x" + "ab" * 32, "WORLD_ENVIRONMENT": "staging", "WORLD_DB": str(db),
            "WORLD_VERIFY_URL": f"http://127.0.0.1:{MOCK_PORT}/api/v4/verify/{{rp_id}}", "WORLD_HUMAN_CAP": cap}


def phone(ctx, human="human-1", outcome="approve", signal_hash=None):
    body = {"outcome": outcome, "action": ctx["action"], "nonce": ctx["rp_context"]["nonce"], "environment": ctx["environment"], "signal_hash": signal_hash or ctx["mock_signal_hash"], "human": human}
    request = urllib.request.Request(ctx["mock_world_app"], data=json.dumps(body).encode(), method="POST")
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def check_world():
    print("-- World ID. MOCK verify endpoint and MOCK phone. REAL IDKit signing and hashing, REAL store")
    a, b = "0x" + "a1" * 20, "0x" + "b2" * 20
    with Mock(), tempfile.TemporaryDirectory() as folder:
        db = Path(folder) / "w.sqlite"
        env = world_env(db)
        vector = world_id._helper({"op": "hash", "signal": "test_signal"}, env)["signal_hash"]
        check("hashSignal matches the docs' test vector", vector == "0x00c1636e0a961a3045054c4d61374422c31a95846b8442f0927ad2ff1d6112ed")
        ctx = world_id.request_context(a, env)
        check("the server signs a 65-byte request for the one fixed action", ctx["action"] == "crashlab-tester-register" and len(ctx["rp_context"]["signature"]) == 132)
        check("the signing key is not in what the browser gets", env["WORLD_RP_SIGNING_KEY"][2:] not in json.dumps(ctx))
        check("the signal is the wallet", ctx["signal"] == a)
        result = phone(ctx)["result"]
        check("rejected in the phone: no proof, nothing stored", phone(ctx, outcome="reject")["success"] is False and not world_store.is_verified(db, a, ctx["action"]))
        done = world_id.verify(result, a, env)
        check("success path stores the human", done["verified"] and world_store.is_verified(db, a, ctx["action"]))
        check("replay of the same proof is rejected", rejected("nullifier_replayed", lambda: world_id.verify(result, a, env)))
        ctx2 = world_id.request_context(a, env)
        check("same human, fresh request: rejected by UNIQUE(nullifier, action)", rejected("nullifier_replayed", lambda: world_id.verify(phone(ctx2)["result"], a, env)))
        ctx3 = world_id.request_context(b, env)
        check("same human, new wallet: rejected, so one human gets one wallet", rejected("nullifier_replayed", lambda: world_id.verify(phone(ctx3)["result"], b, env)))
        ctx4 = world_id.request_context(a, env)
        check("new human, taken wallet: rejected", rejected("wallet_taken", lambda: world_id.verify(phone(ctx4, human="human-2")["result"], a, env)))
        ctx5 = world_id.request_context(b, env)
        wrong = phone(ctx5, human="human-3", signal_hash=ctx["mock_signal_hash"])["result"]
        check("a proof bound to another wallet is rejected", rejected("wrong_wallet", lambda: world_id.verify(wrong, b, env)))
        ok = phone(ctx5, human="human-3")["result"]
        forged = json.loads(json.dumps(ok))
        forged["responses"][0]["proof"] = ["0xbad"] * 5
        check("a proof the verify service refuses is rejected, and nothing stored", rejected("proof_rejected", lambda: world_id.verify(forged, b, env)) and not world_store.is_verified(db, b, ctx["action"]))
        check("the nonce was spent by that try, so a retry must start again", rejected("bad_nonce", lambda: world_id.verify(ok, b, env)))
        ctx6 = world_id.request_context(b, env)
        other_action = {**phone(ctx6, human="human-3")["result"], "action": "another-action"}
        check("a proof for another action is rejected", rejected("wrong_action", lambda: world_id.verify(other_action, b, env)))
        legacy = {**phone(ctx6, human="human-3")["result"], "protocol_version": "3.0"}
        check("a v3 proof is refused by default: one human could hold both a v3 and a v4 nullifier", rejected("legacy_proof_refused", lambda: world_id.verify(legacy, b, env)))
        huge = "0x" + "f" * 64
        check("a 256-bit nullifier is stored exact, not rounded", world_store.nullifier_decimal(huge) == str(2**256 - 1))
        check("verify refuses when off", rejected("not_configured", lambda: world_id.verify(ok, b, {})))
        ctx7 = world_id.request_context(b, env)
        picked = {**phone(ctx7, human="human-3")["result"], "environment": "production"}
        check("the client cannot pick the environment: the server pins it, and the mock echoes what it got", world_id.verify(picked, b, env)["verified"] is True)
        check("the label says mock while the verify URL is local", status.world_status(env)["label"] == "World ID: local mock, no real proof")
        check_gate_cap(db, a)


def check_gate_cap(db, wallet):
    print("-- gate.py human cap fed from the store. REAL gate up to the sim")
    fixtures = POLICY / "bounty" / "fixtures"
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        spec_dir = work / "spec"
        import arc_spec
        arc_spec.build(spec_dir)
        (work / "paid.json").write_text("[]")
        run = lambda submitter, cap, world="not_a_file.json", db_path=db: json.loads(subprocess.run(
            [PYTHON, str(POLICY / "bounty" / "gate.py"), "--world", str(fixtures / world), "--spec", str(spec_dir / "spec.json"), "--paid", str(work / "paid.json"), "--salt-file", str(spec_dir / "salt.hex"),
             "--submitter", submitter, "--seed", "1", "--out", str(work / "out"), "--world-db", str(db_path), "--human-cap", str(cap)], capture_output=True, text=True, cwd=ROOT, env=CLEAN).stdout)
        out = run("0x" + "c3" * 20, 3, "failing.json")
        check("a wallet with no verified human never reaches the sim", out["code"] == "no_verified_human", out["reason"])
        for k in range(2):
            world_store.reserve_submission(db, wallet, status.WORLD_ACTION, 1, f"0x{k}", 2)
        out = run(wallet, 2, "failing.json")
        check("at the cap, the gate rejects with human_cap and the store's count", out["code"] == "human_cap", out["reason"])
        verdict = json.loads(Path(out["verdict"]).read_text())
        check("the verdict says the store fed the cap, and shows no nullifier", verdict["human_cap"]["world_id_connected"] is True and verdict["human_cap"]["used"] == 2 and "nullifier" not in json.dumps(verdict["human_cap"]))
        check("reserve is atomic at the cap", world_store.reserve_submission(db, wallet, status.WORLD_ACTION, 1, "0xnew", 2) is False)
        check("the same submission does not count twice", world_store.reserve_submission(db, wallet, status.WORLD_ACTION, 1, "0x0", 2) is True)
        check("another bounty has its own count", world_store.reserve_submission(db, wallet, status.WORLD_ACTION, 2, "0x0", 2) is True)


def fmt(snap):
    return ", ".join(f"{k} {v / 10**6:g} USDC" for k, v in snap["balances"].items())


def wait_for(fn, what, seconds):
    for _ in range(int(seconds * 2)):
        value = fn()
        if value:
            return value
        time.sleep(0.5)
    check(f"waited for {what}", False)
    raise SystemExit(1)


def check_arc(with_sim):
    import chain as chain_module
    import resolver as resolver_module
    from mock_stack import Stack
    print("-- Arc. LOCAL anvil, standard EVM, MockUSDC at the Arc USDC address, MOCK World ID. REAL contract, Deploy script, resolver and cast")
    with Stack(ANVIL_PORT, MOCK_PORT, window=60) as stack:
        web = stack.env_web
        chain = chain_module.Chain(web)
        snap = chain.snapshot()
        check("deploy script funded the bounty at the docs' USDC address", chain.usdc == status.ARC_USDC and snap["bounty"]["available"] == 1000 * 10**6 and snap["balances"]["bounty contract"] == 1000 * 10**6, fmt(snap))
        check("four separate roles on chain", len({snap["bounty"]["company"].lower(), snap["bounty"]["resolver"].lower(), snap["bounty"]["arbiter"].lower(), stack.addresses["tester"].lower()}) == 4)
        check("the label reads the real chain id and never says Arc here", snap["label"].startswith("Local test chain 31337, not Arc"), snap["label"])
        check("web env holds no signer", not any(n in web for n in status.SIGNER_VARS) and status.arc_status(web)["on"])
        for name in ("ARC_RESOLVER_KEYSTORE",):
            check("resolver env holds a key path but no 0G or World key", name in stack.env_resolver and "ZG_API_KEY" not in stack.env_resolver and "WORLD_RP_SIGNING_KEY" not in stack.env_resolver)
        check("Arc fee floor is 20 Gwei", resolver_module.fee_flags(5042002, 1)[1] == str(20 * 10**9) and resolver_module.fee_flags(31337, 1) == [])
        tester = stack.addresses["tester"]

        # A verified human for the tester, through the real server code path and the mock phone.
        ctx = world_id.request_context(tester, web)
        world_id.verify(phone_at(ctx), tester, web)
        check("human verified on the mock", world_store.is_verified(web["WORLD_DB"], tester, status.WORLD_ACTION))
        replay_ctx = world_id.request_context(tester, web)
        check("a replayed World ID proof is rejected", rejected("nullifier_replayed", lambda: world_id.verify(phone_at(replay_ctx), tester, web)))

        ledger = chain_module.ChainLedger(chain, chain_module.resolver_dir(web) / "inbox")
        if with_sim:
            verdict = real_gate(stack, tester)
            check("the real gate accepted the fixture world", verdict["accepted"], verdict["reason"])
        else:
            verdict = synthetic_verdict(stack, tester)
        fingerprint = verdict["fingerprint"]

        # Refusals first: nothing may reach the chain from a bad verdict. Each goes through the running resolver.
        for name, change, code in (
            ("tampered result hash", lambda v: v["propose"]["named"].update(resultHash="0x" + "ee" * 32) or v.update(result_hash="0x" + "ee" * 32), "result_hash_mismatch"),
            ("another spec", lambda v: v.update(spec_hash="0x" + "dd" * 32), "spec_hash_differs_from_chain"),
            ("wallet with no verified human", lambda v: v["propose"]["named"].update(submitter="0x" + "c3" * 20) or v.update(submitter="0x" + "c3" * 20), "no_verified_human"),
            ("rejected verdict", lambda v: v.update(accepted=False), "not_an_accepted_verdict"),
        ):
            bad = json.loads(json.dumps(verdict))
            bad["fingerprint"] = "0x" + "9" * 63 + str(len(name) % 10)
            bad["propose"]["named"]["fingerprint"] = bad["fingerprint"]
            change(bad)
            ledger.request_propose(bad)
            wait_for(lambda: resolver_log(web, "propose_refused", bad["fingerprint"]), f"refusal of {name}", 20)
            row = resolver_log(web, "propose_refused", bad["fingerprint"])[-1]
            check(f"resolver refuses a {name}", row["code"] == code and chain.failure(bad["fingerprint"])["status"] == "None", row["code"])
            (chain_module.resolver_dir(web) / "failed" / f"{bad['fingerprint']}.json").unlink()
            (chain_module.resolver_dir(web) / "log.jsonl").write_text("".join(l + "\n" for l in (chain_module.resolver_dir(web) / "log.jsonl").read_text().splitlines() if bad["fingerprint"] not in l))

        # Arbiter reject path, on its own fingerprint, with the arbiter's key.
        other = json.loads(json.dumps(verdict))
        other["fingerprint"] = "0x" + "7" * 64
        other["propose"]["named"]["fingerprint"] = other["fingerprint"]
        ledger.request_propose(other)
        wait_for(lambda: chain.failure(other["fingerprint"])["status"] == "Pending", "second proposal", 20)
        tx = subprocess.run(["cast", "send", stack.bounty, "reject(uint256,bytes32,bytes32)", "1", other["fingerprint"], "0x" + "01" * 32, "--rpc-url", stack.rpc, "--keystore", stack.keystores["arbiter"], "--password-file", stack.password, "--json"], capture_output=True, text=True)
        check("the arbiter rejects in the window, and the money returns", tx.returncode == 0 and chain.failure(other["fingerprint"])["status"] == "Rejected" and chain.bounty()["available"] == 1000 * 10**6)
        check("a rejected fingerprint leaves the gate's duplicate list", other["fingerprint"] not in ledger.paid_list())

        # The main path.
        before = chain.snapshot()
        print(f"       balances before: {fmt(before)}")
        ledger.request_propose(verdict)
        wait_for(lambda: chain.failure(fingerprint)["status"] == "Pending", "propose", 20)
        row = chain.failure(fingerprint)
        check("the resolver proposed the gate's exact arguments", row["submitter"].lower() == tester.lower() and row["result_hash"] == verdict["result_hash"] and row["amount"] == 100 * 10**6)
        mid = chain.snapshot()
        check("the proposal reserves the money and pays nobody yet", mid["bounty"]["available"] == 900 * 10**6 and mid["balances"]["tester"] == 0, fmt(mid))
        check("the gate now sees this fingerprint as taken", fingerprint in ledger.paid_list())
        early = subprocess.run(["cast", "send", stack.bounty, "finalize(uint256,bytes32)", "1", fingerprint, "--rpc-url", stack.rpc, "--keystore", stack.keystores["tester"], "--password-file", stack.password, "--json"], capture_output=True, text=True)
        check("finalize inside the dispute window reverts", early.returncode != 0)
        early_claim = subprocess.run([PYTHON, str(HERE / "resolver.py"), "claim", "--fingerprint", fingerprint], env=stack.env_tester, capture_output=True, text=True)
        check("claim before finalize fails", early_claim.returncode != 0)
        t0 = time.time()
        print(f"       dispute window open, {row['dispute_ends_at'] - chain.now()} s left")
        wait_for(lambda: chain.failure(fingerprint)["status"] == "Finalized", "finalize after the window", 90)
        check("the resolver finalized only after the window", chain.now() >= row["dispute_ends_at"], f"waited {time.time() - t0:.0f} s")
        wrong = subprocess.run(["cast", "send", stack.bounty, "claim(uint256,bytes32)", "1", fingerprint, "--rpc-url", stack.rpc, "--keystore", stack.keystores["arbiter"], "--password-file", stack.password, "--json"], capture_output=True, text=True)
        check("another wallet cannot claim", wrong.returncode != 0)
        refused = subprocess.run([PYTHON, str(HERE / "resolver.py"), "claim", "--fingerprint", fingerprint], env={**stack.env_tester, "ARC_RESOLVER_KEYSTORE": "/x"}, capture_output=True, text=True)
        check("the claim command refuses a process that holds the resolver key", refused.returncode != 0 and "resolver key" in refused.stderr)
        claimed = subprocess.run([PYTHON, str(HERE / "resolver.py"), "claim", "--fingerprint", fingerprint], env=stack.env_tester, capture_output=True, text=True)
        print(f"       {claimed.stdout.strip()}")
        after = chain.snapshot()
        check("the tester claimed 100 USDC with the tester's key", claimed.returncode == 0 and after["balances"]["tester"] == 100 * 10**6 and after["failures"][fingerprint]["status"] == "Claimed", fmt(after))
        check("money adds up", after["balances"]["bounty contract"] + after["balances"]["tester"] == before["balances"]["bounty contract"] + before["balances"]["tester"])
        print(f"       balances after: {fmt(after)}")
        again = subprocess.run(["cast", "send", stack.bounty, "propose(uint256,address,bytes32,bytes32,bool)", "1", tester, fingerprint, verdict["result_hash"], "false", "--rpc-url", stack.rpc, "--keystore", stack.keystores["resolver"], "--password-file", stack.password, "--json"], capture_output=True, text=True)
        check("the same fingerprint cannot be proposed twice", again.returncode != 0)
        smoke = subprocess.run([PYTHON, str(HERE / "smoke.py"), "arc"], env=web, capture_output=True, text=True)
        check("smoke.py arc reads the bounty", smoke.returncode == 0 and "Claimed" in smoke.stdout)
        smoke = subprocess.run([PYTHON, str(HERE / "smoke.py"), "world"], env={**web}, capture_output=True, text=True)
        check("smoke.py world signs one request", smoke.returncode == 0 and "crashlab-tester-register" in smoke.stdout)


def phone_at(ctx):
    return phone(ctx)["result"]


def resolver_log(env, step, fingerprint):
    import chain as chain_module
    path = chain_module.resolver_dir(env) / "log.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    return [r for r in rows if r["step"] == step and r.get("fingerprint") == fingerprint]


def real_gate(stack, tester):
    fixtures = POLICY / "bounty" / "fixtures"
    meta = json.loads((fixtures / "meta.json").read_text())
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        (work / "paid.json").write_text("[]")
        t0 = time.time()
        done = subprocess.run([PYTHON, str(POLICY / "bounty" / "gate.py"), "--world", str(fixtures / "failing.json"), "--spec", str(stack.spec / "spec.json"), "--paid", str(work / "paid.json"), "--salt-file", str(stack.spec / "salt.hex"),
                               "--submitter", tester, "--seed", str(meta["failing_seed"]), "--out", str(work / "out"), "--world-db", stack.env_web["WORLD_DB"], "--human-cap", "3"], capture_output=True, text=True, cwd=ROOT, env=CLEAN)
        out = json.loads(done.stdout)
        print(f"       gate: {out['code']} in {time.time() - t0:.0f} s. {out['reason']}")
        return json.loads(Path(out["verdict"]).read_text())


def synthetic_verdict(stack, tester):
    """With --no-sim. The resolver's rules still apply, and the hash chain is real. No sim ran, so no check here says the gate accepted anything."""
    sys.path.insert(0, str(POLICY / "bounty"))
    from gate import PROPOSE, VERDICT_SCHEMA, canonical, result_hash_of, sha256_hex
    spec_hash = "0x" + sha256_hex(canonical(json.loads((stack.spec / "spec.json").read_text())))
    submission = "0x" + "5" * 64
    runs = [{"name": "claim", "seed": 1, "world_sha256": "0", "action_chain_head": "0", "label": "detach"}]
    result = result_hash_of(spec_hash, submission, runs)
    fingerprint = "0x" + "6" * 64
    return {"schema": VERDICT_SCHEMA, "accepted": True, "code": "accepted", "reason": "synthetic", "spec_hash": spec_hash, "submission_hash": submission, "runs": runs, "result_hash": result, "fingerprint": fingerprint, "submitter": tester,
            "repeat": {"same": 8, "need": 7}, "reference_check": {"passed": True}, "human_cap": {"world_id_connected": True},
            "propose": {"function": PROPOSE, "named": {"bountyId": 1, "submitter": tester, "fingerprint": fingerprint, "resultHash": result, "isTopPrize": False}}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("off", "0g", "world", "arc"))
    ap.add_argument("--no-sim", action="store_true")
    a = ap.parse_args()
    if a.only in (None, "off"):
        check_off()
    if a.only in (None, "0g"):
        check_zg()
    if a.only in (None, "world"):
        check_world()
    if a.only in (None, "arc"):
        check_arc(not a.no_sim)
    print("ALL PASS. Local mocks and anvil only." if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
