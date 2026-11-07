"""Checks the 0G AI backend, the evidence upload and the status script on local mocks. No real 0G call, and it spends nothing.

policy/.venv/bin/python policy/crashlab/check_zg.py [--port 5451]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
REPO = POLICY.parent
sys.path[:0] = [str(HERE), str(POLICY / "bounty"), str(POLICY / "server")]
import board_fix as X
import llm
import zg_storage as Z

PY = sys.executable
MOCKS = POLICY / "sponsors" / "mocks"
KEY = "mock-zg-key-not-a-secret"
PASSWORD = "local-check-password-not-a-secret"
failed = 0


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail else ''}", flush=True)


def ask(model, **env):
    """One call through complete_json. Returns (answer or the error code, its row)."""
    saved = dict(os.environ)
    os.environ.update({"CRASHLAB_LLM": "0g", "ZG_MODEL": model, **env})
    llm.CALLS.clear()
    try:
        return llm.complete_json("the prompt", {"type": "object"}), llm.CALLS[-1] if llm.CALLS else None
    except llm.LLMError as e:
        return str(e), llm.CALLS[-1] if llm.CALLS else None
    finally:
        os.environ.clear()
        os.environ.update(saved)


def ai_checks(port):
    router = f"http://127.0.0.1:{port}/v1"
    mock = subprocess.Popen([PY, str(MOCKS / "mock_zg_router.py"), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ai_checks_on(router, port)
    finally:
        mock.terminate()
        mock.wait(5)


def ai_checks_on(router, port):
    for _ in range(50):
        try:
            import socket
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    os.environ.update({"ZG_API_KEY": KEY, "ZG_ROUTER_URL": router, "ZG_SDK_MODULE": str(MOCKS / "mock_zg_sdk.mjs"), "ZG_ETHERS_MODULE": str(MOCKS / "mock_ethers.mjs")})
    real_claude = llm._claude
    asked_claude = []
    llm._claude = lambda p, s: asked_claude.append(p) or {"calls": [], "say": "claude"}
    llm.BACKENDS["claude"] = llm._claude
    try:
        print("-- off by default")
        env_llm = os.environ.pop("CRASHLAB_LLM", None)
        llm.CALLS.clear()
        check("with nothing set, Claude answers and no 0G row exists", llm.complete_json("x", {}) == {"calls": [], "say": "claude"} and not llm.CALLS)
        llm.use_model("m")
        check("use_model keeps Claude when 0G is not chosen", os.environ["CRASHLAB_LLM"] == "claude" and os.environ["CRASHLAB_LLM_MODEL"] == "m")
        os.environ["CRASHLAB_LLM"] = "0g"
        llm.use_model("m")
        check("use_model keeps 0G when the owner chose it", os.environ["CRASHLAB_LLM"] == "0g")
        del os.environ["CRASHLAB_LLM"]
        if env_llm:
            os.environ["CRASHLAB_LLM"] = env_llm
        asked_claude.clear()

        print("-- what a good call records")
        answer, row = ask("mock-good")
        check("JSON comes back, with its request id and own check", answer == {"calls": [], "say": "mock"} and row["request_id"] and row["own_check"] is True and row["tee_verified"] is True and row["response_sha256"], row["request_id"])
        check("the Details line names the request and says what was checked", row["request_id"] in row["line"] and "ourselves" in row["line"] and "does not show that the signature covers the prompt" in row["line"], row["line"])
        check("the API key is in no row", KEY not in json.dumps(row))

        print("-- never claim a check that did not happen")
        answer, row = ask("mock-no-tee")
        check("no verification returned: the answer is usable, and the line says not verified", answer == {"calls": [], "say": "mock"} and row["own_check"] is None and "not verified" in row["line"] and "ourselves" not in row["line"], row["line"])
        answer, row = ask("mock-check-throws")
        check("own check unavailable: only the Router's word is claimed", row["own_check"] == "unavailable" and "Router reports" in row["line"] and "could not check" in row["line"], row["line"])

        print("-- failures say so, and Claude stays out")
        cases = {"mock-sig-bad": "zg_tee_check_failed", "mock-router-false": "zg_tee_check_failed", "mock-not-json": "zg_not_json", "mock-duplicate-keys": "zg_not_json", "mock-no-provider": "zg_no_private_provider"}
        for model, code in cases.items():
            answer, row = ask(model)
            check(f"{model}: {code}, with a plain line", answer == code and row["say"].startswith("0G did not answer this") and "fell_back" not in row, row["say"])
        answer, row = ask("mock-slow", ZG_TIMEOUT_S="2")
        check("slow: a plain timeout", answer == "zg_timeout" and "did not answer in time" in row["say"], row["say"])
        answer, row = ask("mock-good", ZG_API_KEY="wrong-key")
        check("a bad key: plain, and the key is in no row", answer == "zg_bad_key" and "wrong-key" not in json.dumps(row), row["say"])
        answer, row = ask("mock-good", ZG_API_KEY="")
        check("no key: it fails plainly", answer == "zg_no_key" and "not set" in row["say"], row["say"])
        answer, row = ask("mock-good", ZG_ROUTER_URL="http://router-api.0g.ai/v1")
        check("a router with no HTTPS: refused before the key leaves", answer == "zg_router_not_https")
        answer, row = ask("mock-good", ZG_ROUTER_URL="http://127.0.0.1:9/v1")
        check("a router that is down: plain", answer == "zg_timeout")
        check("no failure above called Claude", not asked_claude)

        print("-- fallback, only when asked, and only with a plain line")
        answer, row = ask("mock-no-provider", ZG_FALLBACK_CLAUDE="1")
        check("Claude answers, and the chat line says so", answer["say"] == "claude" and row["fell_back"] and "Claude answered instead" in row["say"] and "Claude answered instead" in row["line"], row["say"])
    finally:
        llm._claude = real_claude
        llm.BACKENDS["claude"] = real_claude

    print("-- the engine agent and the route, as child processes")
    env = {**os.environ, "CRASHLAB_LLM": "0g", "ZG_MODEL": "mock-good"}
    env.pop("CRASHLAB_RECORDED_REPLIES", None)
    done = subprocess.run([PY, str(POLICY / "server" / "plan_job.py"), "agent"], input=json.dumps({"text": "x", "round": 1, "prompt": "p", "schema": {"type": "object"}, "model": "opus"}).encode(), capture_output=True, env=env)
    reply = json.loads(done.stdout)
    check("the engine agent's call reaches 0G and returns its row", reply["ok"] and reply["llm_calls"][0]["request_id"], reply.get("rejection"))
    env_off = {k: v for k, v in env.items() if not k.startswith("CRASHLAB_LLM")}
    env_off["PATH"] = "/nonexistent"  # So a Claude call fails at once and spends nothing.
    done = subprocess.run([PY, str(POLICY / "server" / "plan_job.py"), "agent"], input=json.dumps({"text": "x", "round": 1, "prompt": "p", "schema": {"type": "object"}, "model": "opus"}).encode(), capture_output=True, env=env_off)
    check("with 0G off, the reply holds no row", done.returncode != 0 or "llm_calls" not in json.loads(done.stdout))

    print("-- the chat's three routes, as child processes")

    def routed(route, **extra):
        request = {"text": "x", "round": 1, "prompt": "p", "schema": {"type": "object"}, "model": "claude-opus-5-5", "llm_route": route}
        done = subprocess.run([PY, str(POLICY / "server" / "plan_job.py"), "agent"], input=json.dumps(request).encode(), capture_output=True, env={**env, "ZG_FAST_MODEL": "mock-fast", **extra})
        reply = json.loads(done.stdout)
        return reply, reply["llm_calls"][-1]
    reply, row = routed("fast")
    check("fast: no private header, no signature check, and the line says so", reply["ok"] and row["private"] is False and "own_check" not in row and "tee_verified" not in row and row["line"].startswith("0G Fast:") and "Not private and not verified" in row["line"], row["line"])
    check("fast: no word claims a TEE or a good check", "TEE" not in row["line"] and "ourselves" not in row["line"])
    reply, row = routed("fast", ZG_FAST_MODEL="mock-fast-503")
    check("fast: a failure says no word about a private provider", not reply["ok"] and "private" not in row["say"].lower() and row["say"].startswith("0G Fast did not answer"), row["say"])
    reply, row = routed("private")
    check("private: the signature check still runs", reply["ok"] and row["private"] is True and row["own_check"] is True and row["line"].startswith("0G Private:") and "ourselves" in row["line"], row["line"])
    reply, row = routed("private", ZG_MODEL="mock-sig-bad")
    check("private: a bad signature still throws the answer away", not reply["ok"] and row["error"] == "tee_check_failed", row.get("error"))
    with tempfile.TemporaryDirectory() as fake:
        script = Path(fake) / "claude"
        script.write_text(f'#!/bin/sh\necho "$*" > {fake}/args\necho \'{{"structured_output": {{"calls": [], "say": "c"}}}}\'\n')  # Spends nothing.
        script.chmod(0o755)
        reply, row = routed("claude", PATH=f"{fake}:/usr/bin:/bin:/usr/sbin:/sbin")
        check("claude: 0G gets no call, and the row names Claude and the pinned model", reply["ok"] and row["backend"] == "claude" and row["model"] == "claude-opus-5-5" and "--model claude-opus-5-5" in (Path(fake) / "args").read_text() and "request_id" not in row and row["line"].startswith("Claude:"), row["line"])

    print("-- the scenario agent, as a child process")
    with tempfile.TemporaryDirectory() as out:
        request = {"pack": "window", "world": json.loads((POLICY / "highrise" / "worlds" / "nominal.json").read_text()), "words": ["wind"], "out": out, "limit": 4, "limits": None}
        done = subprocess.run([PY, str(POLICY / "server" / "plan_job.py"), "scenarios_pack"], input=json.dumps(request).encode(), capture_output=True, env=env)
    reply = json.loads(done.stdout) if done.returncode == 0 else {}
    check("its call reaches 0G and returns its row", bool(reply.get("llm_calls")) and reply["llm_calls"][0]["request_id"], done.stderr[-300:] if done.returncode else "")

    print("-- the chat's Details row and the run folder")
    import server
    with tempfile.TemporaryDirectory() as folder:
        said, tools = [], []
        session = types.SimpleNamespace(llm_route=None, dir=Path(folder), tool=lambda *a: tools.append(a), say=lambda text, fail=False: said.append((text, fail)))
        real_job = server.job
        rows = [{"backend": "0g", "request_id": "abc", "line": "0G: request abc", "say": "0G did not answer this: it did not answer in time."}]
        server.job = lambda *_: {"ok": False, "rejection": "llm_zg_timeout", "llm_calls": rows}
        try:
            reply = server.Session.ai_job(session, {}, "agent")
            saved = (Path(folder) / "llm_calls.jsonl").read_text()
            check("the run folder holds the row", json.loads(saved)["request_id"] == "abc")
            check("the Details row shows it, and the chat says the failure", tools == [("details", "", ["0G: request abc"])] and said == [(rows[0]["say"], True)])
            check("the row does not reach the public reply", "llm_calls" not in reply)
            tools.clear()
            said.clear()
            recovered = [{"backend": "0g", "line": "0G: request none, failed: it did not answer in time. Claude answered instead.", "say": "0G did not answer this: it did not answer in time. Claude answered instead.", "fell_back": True}]
            server.job = lambda *_: {"ok": True, "reply": {}, "llm_calls": recovered}
            server.Session.ai_job(session, {}, "agent")
            check("a recovered failure: one quiet line in Details, and nothing in the chat", tools == [("details", "", [recovered[0]["line"]])] and not said)
            tools.clear()
            sent = []

            def capture(body, _timeout):
                sent.append(body)
                raise llm.LLMError("timeout")
            real_post, llm._zg_post = llm._zg_post, capture
            os.environ.update(ZG_API_KEY="x", ZG_MODEL="m")
            for private in (True, False):
                llm.zg_private = private
                llm.CALLS.append({})
                try:
                    llm._zerog("p", {}, 1)
                except llm.LLMError:
                    pass
            llm.zg_private, llm._zg_post = True, real_post
            check("private asks for low reasoning, and Fast sends no such field", sent[0]["reasoning_effort"] == "low" and "reasoning_effort" not in sent[1], str([b.get("reasoning_effort") for b in sent]))
            server.job = lambda *_: {"ok": True, "reply": {}}
            server.Session.ai_job(session, {}, "agent")
            check("with 0G off, no Details row and no line", not tools and not said)
        finally:
            server.job = real_job

    print("-- the picker's server action")
    saved_env, real_runs = dict(os.environ), server.RUNS
    os.environ.update(ZG_API_KEY=KEY, ZG_FAST_MODEL="mock-fast", ZG_MODEL="mock-good")
    try:
        with tempfile.TemporaryDirectory() as folder:
            server.RUNS = Path(folder)
            s = server.Session()
            s.pack, s.llm_route = "inspection", server.default_llm_route()
            check("a new chat starts on 0G Private", s.llm_route == "private")
            check("a free model name is refused", s.choose_llm_route("gpt-4.1-nano") == (400, {"error": "unknown_route"}) and s.choose_llm_route(["fast"])[0] == 400 and s.llm_route == "private")
            s.busy = True
            check("no change while busy", s.choose_llm_route("claude")[0] == 409 and s.llm_route == "private")
            s.busy = False
            check("an allowed route changes between messages", s.choose_llm_route("claude")[0] == 200 and s.llm_route == "claude")
            shown = [e for e in s.events if e["type"] == "llm_route"][-1]
            check("the label event names the route", shown["route"] == "claude" and shown["label"] == "Claude", shown["label"])
            restored = server.Session.load(s.id)
            check("a chat restored from disk keeps its choice", restored.llm_route == "claude")
            check("the fast label never says private without not", server.llm_route_label("fast") == "0G Fast, mock-fast. Not private, not verified", server.llm_route_label("fast"))
            check("a fallback label names Claude", server.llm_route_label("fast", {"fell_back": True}) == "Claude, because 0G Fast failed")
            os.environ.pop("ZG_API_KEY")
            check("with no key, the 0G routes are shut and a new chat starts on Claude", server.default_llm_route() == "claude" and s.choose_llm_route("fast")[0] == 409)
            server.RECORDED = "stored"
            check("a stored run has no route, so no picker", server.default_llm_route() is None)
            server.RECORDED = None
    finally:
        server.RUNS = real_runs
        os.environ.clear()
        os.environ.update(saved_env)


def make_campaign(runs, session, cid):
    """Marks each kind of world, so a leak is plain to see."""
    folder = runs / session / "campaigns" / cid
    folder.mkdir(parents=True)
    kinds = [("TARGETMARK", False, "failed", "stalled"), ("PASSEDMARK", False, "passed", None), ("HELDMARK", True, "held", None), ("OTHERMARK", False, "failed", "slipped")]
    worlds, rows = [], []
    for i, (mark, held, status, verdict) in enumerate(kinds):
        worlds.append({"index": i, "name": mark, "group": "g", "changes": [], "seed": i, "held_back": held, "hash": "0x" + "aa" * 32, "world": {"mark": mark}})
        rows.append({"index": i, "status": status, "verdict": verdict, "verdict_reason": f"reason {mark}", "held_back": held})
        if not held:
            (folder / f"w{i:03d}").mkdir()
            (folder / f"w{i:03d}" / "job_result.json").write_text(json.dumps({"numbers": {"n": i}, "events": [], "verdict": verdict}))
    (folder / "scenarios.json").write_text(json.dumps({"worlds": worlds}))
    (folder / "grid.json").write_text(json.dumps({"pack": "window", "rows": rows}))
    return folder


def storage_checks():
    temp = Path(tempfile.mkdtemp(prefix="check-zg-"))
    try:
        session = "a" * 32
        runs, board, store, wallet = temp / "runs", temp / "board", temp / "store", temp / "wallet"
        board.mkdir()
        store.mkdir()
        wallet.mkdir(mode=0o700)
        folder = make_campaign(runs, session, "c1")
        (wallet / "password").write_text(PASSWORD)
        subprocess.run(["cast", "wallet", "new", str(wallet), "zg", "--unsafe-password", PASSWORD], capture_output=True, check=True)
        os.environ.update({"ZG_STORAGE_SDK_MODULE": str(MOCKS / "mock_zg_storage_sdk.mjs"), "ZG_ETHERS_MODULE": str(MOCKS / "mock_ethers.mjs"), "ZG_MOCK_STORE": str(store), "ZG_WALLET_KEYSTORE": str(wallet / "zg"), "ZG_WALLET_PASSWORD_FILE": str(wallet / "password")})
        Z.RECHECK_WAIT_S = 0

        print("-- what a bundle holds")
        text = Z.encoded(Z.campaign_bundle(folder, session, board)).decode()
        check("a campaign bundle holds public worlds, results, reasons and hashes", all(w in text for w in ("TARGETMARK", "PASSEDMARK", "reason TARGETMARK", "aaaaaa", "judge5.py")))
        check("it never holds a held-back world", "HELDMARK" not in text)
        check("it says how many stay out", json.loads(text)["withheld_worlds"] == 1)
        (board / "1").mkdir()
        hidden = {"held_back": [{"index": 2, "world": {"mark": "HELDMARK"}}], "passed_before": [{"index": 1, "world": {"mark": "PASSEDMARK"}}], "other_failed": [{"index": 3, "world": {"mark": "OTHERMARK"}}], "source": [session, "c1", "stalled"]}
        (board / "1" / "hidden.json").write_text(json.dumps(hidden))
        text = Z.encoded(Z.campaign_bundle(folder, session, board)).decode()
        check("with a bounty posted, none of its hidden worlds are in the campaign bundle", all(m not in text for m in ("HELDMARK", "PASSEDMARK", "OTHERMARK")) and "TARGETMARK" in text)
        (board / "1" / "pack.json").write_text(json.dumps({"id": 1, "title": "t", "pack": "window", "group": "stalled", "public_worlds": [{"index": 0, "world": {"mark": "TARGETMARK"}}], "hidden_counts": {"held_back": 1, "passed_before": 1, "other_failed": 1}, "frozen": {"highrise5/judge5.py": "ab"}, "controller": {"sha256": "cd"}}))
        book = X.B.ledger_module.Ledger(board / "1" / "ledger.json")
        book.fund("0x" + "11" * 32, 5, 5, 60, X.B.COMPANY, X.B.RESOLVER, X.B.ARBITER)
        (board / "1" / "fixes").mkdir()
        text = Z.encoded(Z.bounty_bundle(1, board)).decode()
        check("a bounty's bundle holds only its public worlds", "TARGETMARK" in text and all(m not in text for m in ("HELDMARK", "PASSEDMARK", "OTHERMARK")) and json.loads(text)["withheld_worlds"] == 3)

        print("-- upload and re-download")
        record = Z.upload(Z.bounty_bundle(1, board), board / "1")
        check("the root hash comes back and the re-download matches", record["root_hash"].startswith("0x") and record["rechecked"] and "message" not in record, record["root_hash"])
        check("a mock is labelled a mock, with no link", record["label"] == Z.LABEL_MOCK and record["tx_link"] is None)
        check("the bounty's public view shows the root hash", X.view(1, board)["evidence"]["root_hash"] == record["root_hash"])
        check("the wallet path and the password are in no record", str(wallet) not in json.dumps(record) and PASSWORD not in json.dumps(record))
        same = subprocess.run([PY, str(HERE / "zg_storage.py"), "recheck", "--id", "1", "--root", str(board)], capture_output=True, text=True, env=os.environ)
        check("the recheck command downloads and compares", same.returncode == 0 and "matches" in same.stdout, same.stdout)
        os.environ["ZG_MOCK_STORAGE"] = "tamper"
        check("a changed file fails the compare", Z.recheck(record["root_hash"], record["sha256"]) is False)
        Z.RECHECK_TRIES = 1
        tampered = Z.upload(Z.campaign_bundle(folder), folder)
        check("after a tampered download the record says not checked", tampered["rechecked"] is False and "another hash" in tampered["message"], tampered["message"])
        del os.environ["ZG_MOCK_STORAGE"]
        (folder / "zg_evidence.json").unlink()
        record = Z.upload(Z.campaign_bundle(folder, session, board), folder)
        try:
            X.post(session, "c1", "stalled", "t", "c", 5, root=board, runs=runs)
            check("a published campaign cannot become a bounty with hidden worlds", False)
        except X.B.BoardError as e:
            check("a published campaign cannot become a bounty with hidden worlds", e.code == "campaign_published", str(e))

        print("-- failures, each plain, with no root hash")
        target = temp / "target"
        target.mkdir()
        bundle = Z.bounty_bundle(1, board)

        def fails(words, **env):
            saved = dict(os.environ)
            os.environ.update(env)
            try:
                Z.upload(bundle, target)
                return False
            except Z.StorageError as e:
                return words in str(e) and "secret detail" not in str(e) and not (target / Z.FILE).exists()
            finally:
                os.environ.clear()
                os.environ.update(saved)
        check("the network fails", fails("upload to 0G Storage failed", ZG_MOCK_STORAGE="fail"))
        check("wrong network: chain 16661 is refused", fails("not 0G Galileo testnet", ZG_MOCK_CHAIN="16661"))
        check("empty balance", fails("no test tokens", ZG_MOCK_BALANCE="0"))
        check("no keystore", fails("did not open", ZG_WALLET_KEYSTORE=str(wallet / "none")))
        Z.UPLOAD_TIMEOUT_S = 2
        check("it hangs: a plain timeout", fails("did not answer in time", ZG_MOCK_STORAGE="hang"))
        Z.UPLOAD_TIMEOUT_S = 300
        check("no SDK", fails("not installed", ZG_STORAGE_SDK_MODULE=str(temp / "none.mjs")))

        print("-- the real ethers opens a keystore from cast wallet new (no network)")
        zg = POLICY / "sponsors" / "zg"
        if (zg / "node_modules" / "ethers").is_dir():
            script = "import { Wallet } from 'ethers'; import { readFileSync as r } from 'node:fs'; const w = await Wallet.fromEncryptedJson(r(process.argv[1], 'utf8'), process.argv[2]); console.log(w.address.toLowerCase())"
            out = subprocess.run(["node", "--input-type=module", "-e", script, str(wallet / "zg"), PASSWORD], capture_output=True, text=True, cwd=zg)
            address = subprocess.run(["cast", "wallet", "address", "--keystore", str(wallet / "zg"), "--password-file", str(wallet / "password")], capture_output=True, text=True).stdout.strip().lower()
            check("the address matches", out.stdout.strip() == address and address.startswith("0x"), out.stderr[-200:])
        else:
            print("SKIP the SDK is not installed here")

        print("-- the status script")
        env_file = temp / "status.env"
        env_file.write_text(f"CRASHLAB_LLM=0g\nZG_API_KEY=SECRETVALUE1\nZG_MODEL=m\nARC_RPC_URL=https://rpc.testnet.arc.io/SECRETVALUE2\nARC_WALLET_DIR={wallet}\nARC_CAP_USDC=5\nWORLD_RP_SIGNING_KEY=SECRETVALUE3\n")
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("ZG_", "ARC_", "WORLD_", "CRASHLAB_"))}
        out = subprocess.run([PY, str(REPO / "scripts" / "sponsor_status.py"), "--env", str(env_file), "--root", str(board)], capture_output=True, text=True, env=clean).stdout
        check("it says what is on and off", "ON  0G AI" in out and "OFF Arc testnet payouts" in out and "OFF World ID login" in out and "contract not deployed" in out, out)
        check("it prints no secret", "SECRETVALUE" not in out and PASSWORD not in out)
        (temp / "empty.env").write_text("")
        out = subprocess.run([PY, str(REPO / "scripts" / "sponsor_status.py"), "--env", str(temp / "empty.env"), "--root", str(temp / "none")], capture_output=True, text=True, env=clean).stdout
        check("with nothing set, Arc and 0G say off", "OFF Arc testnet payouts" in out and "OFF 0G AI" in out and "OFF 0G Storage" in out and "ON  0G AI" not in out, out)
        out = subprocess.run([PY, str(REPO / "scripts" / "compare_0g.py")], capture_output=True, text=True, env={**clean, "ZG_API_KEY": "k", "ZG_MODEL": "m"}).stdout
        check("the compare script calls nothing without --yes", "Nothing was called" in out, out.splitlines()[-1])
        out = subprocess.run([PY, str(REPO / "scripts" / "compare_0g.py"), "--yes"], capture_output=True, text=True, env=clean).stdout
        check("the compare script needs credentials, even with --yes", "not set" in out and "Nothing was called" in out)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5451)
    a = ap.parse_args()
    ai_checks(a.port)
    storage_checks()
    print(f"{'ALL PASS' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
