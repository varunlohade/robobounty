"""Each security finding of the fix gate as an attack: check_security.py [--fast] [--port N]. Exit 0 only if every attack fails and honest work still passes. Results are simulated.

--fast leaves out the real sim runs. The full run takes about 20 minutes. Everything lives in a new folder under policy/runs/board/, named check_sec_<time>. The board server runs on its own port.
"""
import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix as X
import board_fix_gate as FG
import board_fix_run  # noqa: F401 turns the LLM off, and turns the inspection re-judge on
import anvil_mirror as AM
import arc_mirror as M
import arc_wallet as W
import board_store as B
import check_auth_helper as H
import budget

F = X.F
ORIGIN = "http://localhost:5199"
SESSION = "ab" * 16
WINDOW_CAMPAIGN = "5a8d63e3648b469a8142af56c0824119/c1"
INSPECTION = F.PACK5["inspection"]["file"].read_text()
WINDOW = F.PACK5["window"]["file"].read_text()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def new_root():
    root = X.POLICY / "runs" / "board" / f"check_sec_{time.strftime('%Y%m%d_%H%M%S')}"
    root.mkdir(parents=True)
    return root


# F1: a repeated top-level name.
def f1():
    speed = "SPEED_MPS = __import__('pathlib').Path('/tmp/x').write_text('owned')\n"
    attacks = {
        "a repeated constant that runs at import": (speed + INSPECTION, False),
        "the same, as a constant-only fix": (speed + INSPECTION, True),
        "a repeat def _closest_on_leg": (INSPECTION.replace("class RouteFollower:", "def _closest_on_leg(p, a, b):\n    return (0.0, 1.0)\n\n\nclass RouteFollower:", 1), False),
        "a repeat class RouteFollower": (INSPECTION + "\nclass RouteFollower:\n    pass\n", False),
        "a second import of math": (INSPECTION.replace("import math\n", "import math\nimport math\n", 1), False),
        "a second docstring": (INSPECTION + '\n"a second docstring"\n', False),
        "a function in place of a constant": (INSPECTION.replace("SPEED_MPS = 0.8", "def SPEED_MPS():\n    pass\n", 1), False),
        "a new base on RouteFollower": (INSPECTION.replace("class RouteFollower:", "class RouteFollower(print('x') or object):", 1), False),
        "a decorator on RouteFollower": (INSPECTION.replace("class RouteFollower:", "@print\nclass RouteFollower:", 1), False),
        "an infinite constant": (INSPECTION.replace("SPEED_MPS = 0.8", "SPEED_MPS = 1e999", 1), False),
    }
    for name, (source, constants_only) in attacks.items():
        reasons = F.validate5("inspection", source, constants_only=constants_only)
        check(f"F1: refused, {name}", bool(reasons), reasons[0][:90] if reasons else "it validated")
    legal = INSPECTION.replace("SPEED_MPS = 0.8", "SPEED_MPS = 1.0", 1)
    check("F1: a legal constant change still passes", F.validate5("inspection", legal, constants_only=True) == [])
    check("F1: the outside judge takes numbers only from a clean file", F.route_constants(legal)["SPEED_MPS"] == 1.0 and F.route_constants(speed + INSPECTION) is None and F.route_constants(INSPECTION.replace("return (SPEED_MPS, 0.0, turn)", "return (9.0, 0.0, turn)")) is None)


# F2: chains through allowed modules.
def reasons_for(source):
    return F.rule_problems([ast.parse(source)], set())[0]


def reachable_paths(root, name, most=30000, skip=()):
    """Breadth first over every public attribute, leaving out the names in skip. Returns {dotted path: object} for the first path to each object."""
    seen, paths, queue = {id(root)}, {}, [(root, name)]
    keep = []  # Keeps made objects alive, so an id stays one object.
    while queue and len(paths) < most:
        obj, path = queue.pop(0)
        for attr in dir(obj):
            if attr.startswith("_") or attr in skip:
                continue
            try:
                value = getattr(obj, attr)
            except Exception:  # noqa: BLE001 A lazy attribute may raise anything.
                continue
            keep.append(value)
            if id(value) in seen:
                continue
            seen.add(id(value))
            paths[f"{path}.{attr}"] = value
            queue.append((value, f"{path}.{attr}"))
    return paths


def f2():
    attacks = {
        "the chain to open": "import numpy\nx = numpy.ma.extras.ma.inspect.dis.io.open\n",
        "BitGenerator.ctypes": "import numpy as np\nx = np.random.BitGenerator.ctypes\n",
        "np.testing": "import numpy as np\nx = np.testing\n",
        "an alias by assignment": "import numpy as np\nq = np\nx = q.ma\n",
        "a module in a call": "import numpy as np\ndef f(m):\n    return m\nf(np)\n",
        "a module in a list": "import numpy as np\nx = [np][0]\n",
        "a part of a chain by assignment": "import numpy as np\nq = np.ma\n",
        "an import alias": "import numpy as q\nx = q.ma\n",
        "an alias named math": "import numpy as math\nx = math.ma\n",
        "a name bound to two modules": "import math as q\nimport numpy as q\nx = q.pi\n",
        "from numpy import a submodule": "from numpy import ma\n",
        "from numpy import with an alias": "from numpy import testing as sin\n",
        "an import inside a function": "def f():\n    import numpy as q\n    return q.ma\n",
        "an attribute past an allowed name": "import numpy as np\nx = np.array.mro\n",
        "an attribute past a from import": "from numpy import array as a\nx = a.real\n",
        "math.nextafter": "import math\nx = math.nextafter\n",
        "a module rebound": "import numpy as np\nnp = 1\n",
        "cffi on a generator": "x = y.bit_generator.cffi\n",
    }
    for name, source in attacks.items():
        reasons = reasons_for(source)
        check(f"F2: refused, {name}", bool(reasons), reasons[0][:90] if reasons else "it validated")
    route = INSPECTION.replace("along = max(", "wp.config.verify_fp = True\n    along = max(", 1)
    check("F2: the inspection file's own warp is out of reach", bool(F.validate5("inspection", route)))
    route = INSPECTION.replace("self.next = 1 ", "WalkPolicy.targets = None\n        self.next = 1 ", 1)
    check("F2: the frozen WalkPolicy is out of reach", bool(F.validate5("inspection", route)))

    paths = {**reachable_paths(np, "numpy"), **reachable_paths(math, "math")}
    to_open = [p for p, v in paths.items() if v is open]
    let_through = [p for p in paths if p not in F.ALLOWED_ATTRS and not reasons_for(f"import numpy\nimport math\nx = {p}\n")]
    check("F2: nothing reachable outside the allowlist validates", len(paths) > 2000 and to_open and not let_through, f"{len(paths)} paths tried, {len(to_open)} reach open, {len(let_through)} let through: {let_through[:5]}")
    allowed = [p for p in sorted(F.ALLOWED_ATTRS) if reasons_for(f"import numpy\nimport math\nx = {p}\n")]
    check("F2: every allowlisted name validates", not allowed, str(allowed))

    # Past the allowlist, code holds plain values. No public attribute of those values, under the rule for values, leads to a module or to open.
    values = {"zeros": np.zeros(1), "float32": np.float32(1.0), "array": np.array, "sqrt": math.sqrt, "text": "", "list": [], "dict": {}, "tuple": (), "int": 1, "float": 1.0}
    bad = []
    tried = 0
    for name, value in values.items():
        for path, obj in reachable_paths(value, name, 3000, F.BANNED_ATTRS).items():
            tried += 1
            if isinstance(obj, type(os)) or obj is open:
                bad.append(path)
    check("F2: no public chain from an allowed value reaches a module or open", tried > 100 and not bad, f"{tried} paths, found {bad[:5]}")

    for name, text in (("controller.py", F.BASE.read_text()), ("controller5.py", WINDOW), ("the stored good fix", (HERE / "fixtures" / "fix5" / "good_match_fan.py").read_text())):
        reasons = F.validate_source(text, F.PACK5["window"]["file"] if name != "controller.py" else None)
        check(f"F2: a legal file still passes, {name}", reasons == [], str(reasons[:2]))
    numeric = "import numpy as np\nimport math\nx = np.cross(np.array([1.0, 0.0, 0.0]), np.zeros(3))\ny = np.concatenate([x, x]).astype(np.float32)\nz = math.atan2(1.0, 2.0)\n"
    check("F2: a legal use of the allowed names passes", reasons_for(numeric) == [])
    check("F2: the inspection controller still passes", F.validate5("inspection", INSPECTION) == [])


# F3 and the claim secret. No sim here: the ledger, the budget and the rows are real.
def small_campaign(runs, target, held_back, passed):
    """A real campaign folder, from rows of (name, world, seed, verdict). Writes each row's stored result, like the lab does."""
    folder = runs / SESSION / "campaigns" / "c1"
    folder.mkdir(parents=True)
    worlds, rows = [], []
    for held, group in ((False, target), (True, held_back), (False, passed)):
        for name, world, seed, result in group:
            index = len(worlds) + 1
            worlds.append({"index": index, "name": name, "group": "check", "changes": [], "seed": seed, "world": world, "held_back": held, "hash": hashlib.sha256(json.dumps(world, sort_keys=True).encode()).hexdigest()})
            status = "passed" if result["passed"] else "failed"
            rows.append({"index": index, "verdict": result["verdict"], "status": status, "verdict_reason": result["reason"], "held_back": held})
            (folder / f"w{index:03d}").mkdir()
            (folder / f"w{index:03d}" / "job_result.json").write_text(json.dumps(result))
    (folder / "scenarios.json").write_text(json.dumps({"worlds": worlds}))
    (folder / "grid.json").write_text(json.dumps({"pack": "inspection", "running": False, "rows": rows}))


FAKE = {"verdict": "timed_out", "passed": False, "reason": "A test row, with no sim.", "numbers": {}, "events": [], "code_sha256": X.frozen_shas("inspection")}
FAKE_PASS = {**FAKE, "verdict": "passed", "passed": True}


def paid_fix(root, tester, secret, posted_by="company"):
    """A bounty and a fix that holds the pay, with a real ledger and no sim. Finalized, so a claim is the next step."""
    runs = root / "runs"
    small_campaign(runs, [("t", {}, 1, FAKE)], [("h", {}, 2, FAKE)], [("p", {}, 3, FAKE_PASS)])
    info = X.post(SESSION, "c1", "timed_out", "Security check", "Check company", 40, posted_by=posted_by, root=root, runs=runs)
    row = X.reserve(info["id"], tester, INSPECTION + "\n# a fix\n", root, secret=secret)
    folder = X.folder_of(info["id"], root)
    result = {"code": "accepted", "patched_sha256": row["source_sha256"], "sets": {}, "target": []}
    payout = FG.propose(row, result, folder, root)
    X.save_fix({**row, "state": "done", "result": result, "payout": payout}, root)
    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        book.finalize(payout["fingerprint"], now=time.time() + 10**6)
    return info["id"], folder, row["n"], payout["fingerprint"]


def refused(fn, code):
    try:
        fn()
    except B.BoardError as e:
        return e.code == code
    return False


def f3_and_secret(root):
    agent = root / "agent"
    budget.fund(100, 50, agent)
    bid, folder, n, fp = paid_fix(agent, "ana", "ana-secret", posted_by="agent")
    check("F3: a claim the budget cannot settle fails", refused(lambda: X.ledger_step(bid, n, "claim", "ana", agent, secret="ana-secret"), "budget_mismatch"))
    book = B._ledger(folder)
    fix = json.loads((folder / "fixes" / str(n) / "fix.json").read_text())
    check("F3: and nothing changed: the ledger stays Finalized, and the fix is not Claimed", book.failures[fp]["status"] == "Finalized" and fix["payout"]["status"] != "Claimed", f"ledger {book.failures[fp]['status']}, fix {fix['payout'].get('status')}")
    check("F3: the budget moved nothing", budget.view(agent)["spent"] == 0)
    budget.hold(bid, 40, "check", agent)
    row = X.ledger_step(bid, n, "claim", "ana", agent, secret="ana-secret")
    ok, built = budget.adds_up(agent)
    check("F3: with the hold there, the claim and the budget settle together", row["payout"]["status"] == "Claimed" and budget.view(agent)["spent"] == 40 and budget.view(agent)["held"] == 0 and ok, json.dumps(built))

    plain = root / "plain"
    plain.mkdir()
    bid, folder, n, fp = paid_fix(plain, "ana", "ana-secret")
    check("claim: another caller with the name and no secret is refused", refused(lambda: X.ledger_step(bid, n, "claim", "ana", plain), "bad_secret"))
    check("claim: the wrong secret is refused", refused(lambda: X.ledger_step(bid, n, "claim", "ana", plain, secret="guess"), "bad_secret"))
    check("claim: the right secret with another name is refused", refused(lambda: X.ledger_step(bid, n, "claim", "mallory", plain, secret="ana-secret"), "ledger_refused"))
    on_disk = b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file())
    check("claim: the secret is not on disk, and its hash is", b"ana-secret" not in on_disk and B.claim_hash("ana-secret").encode() in on_disk)
    check("claim: no public view holds the hash", B.claim_hash("ana-secret") not in json.dumps([X.list_fixes(bid, plain), X.get_fix(bid, n, plain), X.view(bid, plain)]))
    check("claim: the right name and secret are paid", X.ledger_step(bid, n, "claim", "ana", plain, secret="ana-secret")["payout"]["status"] == "Claimed")
    check("claim: the label stays", X.view(bid, plain)["world_id_label"] == B.WORLD_ID_LABEL)

    other = root / "no_secret"
    other.mkdir()
    bid, _, n, _ = paid_fix(other, "ana", None)
    check("claim: a row with no stored secret can never be claimed", refused(lambda: X.ledger_step(bid, n, "claim", "ana", other, secret=""), "bad_secret"))

    find = root / "find"
    made = B.post("Find", "Check company", [], 10, 10, {}, root=find)
    row = B.reserve(made["id"], "ana", 1, find, secret="find-secret")
    folder = find / str(made["id"])
    fp = "0x" + "a" * 64
    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        book.propose(B.tester_address("ana"), fp, "0x" + "b" * 64)
        book.finalize(fp, now=time.time() + 10**6)
        B.save_submission({**row, "state": "done", "payout": {**book.failures[fp], "unit": "test units"}}, find)
    check("find bounty: the name alone cannot claim", refused(lambda: B.ledger_step(made["id"], fp, "claim", "ana", find), "bad_secret"))
    check("find bounty: no public row holds the hash", "claim_sha256" not in json.dumps(B.list_submissions(made["id"], find)) and "claim_sha256" not in json.dumps(B.get_submission(made["id"], row["n"], find)))

    def no_budget(_):
        raise B.BoardError("budget_mismatch", "test")
    check("find bounty: a budget refusal fails the claim", refused(lambda: B.ledger_step(made["id"], fp, "claim", "ana", find, secret="find-secret", on_claim=no_budget), "budget_mismatch") and B._ledger(folder).failures[fp]["status"] == "Finalized")
    check("find bounty: the right secret is paid", B.ledger_step(made["id"], fp, "claim", "ana", find, secret="find-secret")["status"] == "Claimed")


class FakeChain:
    """Stands in for the RPC only. arc_wallet.advance runs as it is. The contract's two reject rules are here, so a late or failed send acts as on chain."""
    real = False
    addresses = ["0x" + "1" * 40, "0x" + "2" * 40]

    def __init__(self, wallet):
        self.wallet, self.status, self.ends, self.time, self.fail, self.sent, self.txs = wallet, "Pending", 1000, 500, False, [], {}

    def run(self, *args):
        return "0x" + "ab" * 32

    def read_int(self, *args):
        return 0

    def now(self):
        return self.time

    def failure(self, *args):
        return self.status, self.ends, self.wallet

    def send(self, name, *args):
        if name == "reject" and (self.fail or self.time >= self.ends):
            raise M.ArcError("reverted", "The reject transaction reverted." + M.NOT_PAID)
        self.sent.append(name)
        self.status = {"reject": "Rejected", "finalize": "Finalized", "payout": "Claimed"}[name]


def arc_agent(root):
    """A signed rejection never turns into a payout, and a chain rejection always reaches the ledger."""
    agent = root / "arc_agent"
    agent.mkdir()
    wallet = "0x" + "3" * 40
    runs = agent / "runs"
    small_campaign(runs, [("t", {}, 1, FAKE)], [("h", {}, 2, FAKE)], [("p", {}, 3, FAKE_PASS)])
    info = X.post(SESSION, "c1", "timed_out", "Arc check", "Check company", 40, root=agent, runs=runs)
    bid = info["id"]
    row = X.reserve(bid, "ana", INSPECTION + "\n# a fix\n", agent, secret="s")
    folder = X.folder_of(bid, agent)
    result = {"accepted": True, "code": "accepted", "patched_sha256": row["source_sha256"], "sets": {}, "target": []}
    payout = FG.propose(row, result, folder, agent)
    X.save_fix({**row, "state": "done", "result": result, "payout": payout, "wallet": wallet}, agent)
    B.write_json(folder / "arc_funding.json", {"chain_bounty": 1, "company": "0x" + "4" * 40, "cap_base_units": 40 * AM.TOKEN_UNIT})
    chain = FakeChain(wallet)
    n = row["n"]
    step = lambda: W.advance(chain, agent, bid, n, "0x" + "5" * 40)
    request = folder / "fixes" / str(n) / "arc_reject.json"
    saved = W.signer_ok, W.need_on, W.reader
    W.signer_ok, W.need_on, W.reader = (lambda *a: True), (lambda *a: {}), (lambda: chain)
    try:
        B.write_json(request, {"nonce": "n", "signature": "s"})
        chain.fail = True
        try:
            step()
            failed = False
        except M.ArcError:
            failed = True
        check("arc: an arbiter send that fails is said, and nothing else goes out", failed and not chain.sent)
        chain.fail, chain.time = False, 1000
        step()
        check("arc: a signed rejection past the window does not finalize", not chain.sent and chain.status == "Pending" and W.steps_of(folder, n)["message"] == W.REJECT_LATE, W.steps_of(folder, n)["message"])
        check("arc: and the company cannot sign one in past the window", refused(lambda: W.request_reject(bid, n, "n", "s", agent), "wrong_state"))
        chain.status = "Finalized"
        step()
        check("arc: a signed rejection stops the payout of a fix someone else finalized", not chain.sent and W.steps_of(folder, n)["message"] == W.REJECT_LATE)
        chain.status, chain.time = "Pending", 500
        step()
        check("arc: in the window, the signed rejection goes out", chain.sent == ["reject"] and chain.status == "Rejected", str(chain.sent))
        request.unlink()
        chain.status, chain.time, chain.sent = "Pending", 1000, []
        while step():
            pass
        check("arc: with no rejection, the agent still finalizes and pays", chain.sent == ["finalize", "payout"], str(chain.sent))
    finally:
        W.signer_ok, W.need_on, W.reader = saved

    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        book.failures[payout["fingerprint"]]["dispute_ends_at"] = time.time() - 1
        book._save()
    check("arc: the local button still keeps the local window", refused(lambda: X.ledger_step(bid, n, "reject", root=agent), "ledger_refused"))
    chain.status = "Rejected"
    step()
    held = B._ledger(folder).failures[payout["fingerprint"]]["status"]
    check("arc: a chain rejection after the local window wins over the ledger", held == "Rejected" and W.steps_of(folder, n)["ledger_rejected"] is True and X.get_fix(bid, n, agent)["payout"]["status"] == "Rejected", held)


def budget_owner(root):
    """Only the company that deposited a budget can stop it, on the real server."""
    owned, port = root / "budget_owned", ARGS.port + 1
    budget.fund(100, 50, owned, owner=H.COMPANY)
    orphan = root / "budget_orphan"
    budget.fund(100, 50, orphan)
    other = H.A.board_token(H.A.new_session(H.A.sign_up(f"other{time.time_ns()}@company.example", "correct horse battery", "Other company", "check"), "company"))
    check("budget: no public view holds the owner", "owner" not in budget.view(owned))
    for folder, name, codes in ((owned, "owned", {"other": 403, "owner": 200}), (orphan, "with no depositor", {"other": 403, "owner": 403})):
        log = open(folder / "server.log", "ab")
        server = subprocess.Popen([str(X.PYTHON), str(HERE / "board_server.py"), "--root", str(folder), "--port", str(port)], stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    http(port, "GET", "/api/health")
                    break
                except OSError:
                    time.sleep(0.2)
            status, reply = http(port, "POST", "/api/budget/stop", {}, token=other)
            check(f"budget {name}: another company cannot stop it", status == codes["other"] and reply.get("error") == "not_your_budget" and not budget.view(folder)["stopped"], f"{status} {reply}")
            status, reply = http(port, "POST", "/api/budget/stop", {})
            check(f"budget {name}: the depositing company gets {codes['owner']}", status == codes["owner"] and budget.view(folder)["stopped"] is (codes["owner"] == 200), f"{status}")
        finally:
            server.terminate()
            server.wait()
            log.close()


# The structural part, with real runs. Each hostile tail goes on the end of a controller file, as if the code rules had missed it.
JUDGE_PATCH = '''
import packs.inspection.pack as PACK
REAL_JUDGE = PACK.judge
def forged_judge(rec, world):
    r = REAL_JUDGE(rec, world)
    r.update(verdict="passed", passed=True, reason="The robot reached all waypoints.")
    return r
PACK.judge = forged_judge
'''
RECORD_FORGE = '''
import packs.inspection.pack as PACK
REAL_RUN = PACK.run
def forged_run(world, *, seed=0, out=None):
    rec, meta = REAL_RUN(world, seed=seed, out=None)
    stops = [(0.0, 0.0)] + [(p["x"], p["y"]) for p in world["route"]["waypoints"]] + [(11.0, 4.0)]
    n = len(rec["t"])
    for i in range(n):
        s = (len(stops) - 1) * min(1.0, 1.25 * i / n)
        k = min(int(s), len(stops) - 2)
        f = s - k
        rec["base_q"][i, 0] = stops[k][0] + f * (stops[k + 1][0] - stops[k][0])
        rec["base_q"][i, 1] = stops[k][1] + f * (stops[k + 1][1] - stops[k][1])
    np.savez_compressed(out, **rec)
    return rec, meta
PACK.run = forged_run
'''
WINDOW_SWAP = '''
import sys as SYS
TRIAL = SYS.modules["run_trial5"]
REAL_TRIAL = TRIAL.run
def easy_run(world, seed, out=None):
    with open(TRIAL.HERE.parent / "highrise" / "worlds" / "nominal.json", "rb") as f:
        return REAL_TRIAL(TRIAL.W.parse(f.read()), seed, out)
TRIAL.run = easy_run
'''
RULES_OFF_RUNNER = '''import sys
sys.path.insert(0, {bounty!r})
import board_fix_run
F = board_fix_run.F
F.validate5 = lambda *a, **k: []
F.validate_route_follower = lambda *a, **k: []
sys.exit(board_fix_run.main())
'''


def plant_world(limit):
    code = "import json, sys; sys.path.insert(0, '.'); from packs.inspection import plant as PL, world as W; w = W.build(*PL.PLANT); w['route']['time_limit_s'] = %s; print(json.dumps(w))" % limit
    return json.loads(subprocess.run([str(F.PACK5["inspection"]["python"]), "-c", code], cwd=X.POLICY, capture_output=True, text=True, check=True).stdout)


def base_run(root, name, world, seed):
    out = root / "base_runs" / name
    row = F.trial5("inspection", str(F.PACK5["inspection"]["file"]), {"index": 0, "name": name, "world": world, "seed": seed}, out, True)
    if not row["rejudged"] or row["verdict"] == "replay_mismatch":
        raise SystemExit(f"the honest base run did not match outside the sandbox: {row}")
    return (name, world, seed, json.loads((out / "job_result.json").read_text()))


def http(port, method, path, body=None, token=None):
    bearer = {}
    if method == "POST":
        body, value = H.signed(body)
        bearer = {"Authorization": f"Bearer {token}" if token else value}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Content-Type": "application/json", "Origin": ORIGIN, **bearer})
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def rejudge_attacks(root, world, seed):
    """Tampered records of one honest run, each through the real outside judge. Any cheap check stops these before a sim run."""
    honest = root / "base_runs" / "held"
    good = dict(np.load(honest / "record.npz", allow_pickle=False))
    tamper = {
        "a frame count past the time limit": lambda r: {**r, "t": np.arange(1, 90000, dtype=np.float32)},
        "a clock that is not the sim's": lambda r: {**r, "t": r["t"] * 0.5},
        "a NaN in the base pose": lambda r: {**r, "base_q": np.where(r["base_q"] == r["base_q"][0, 0], np.nan, r["base_q"])},
        "another seed": lambda r: {**r, "meta": np.array(json.dumps({**json.loads(str(r["meta"])), "seed": seed + 1}))},
        "a missing array": lambda r: {k: v for k, v in r.items() if k != "object_f"},
        "a pickle": lambda r: {**r, "t": np.array([{"x": 1}], dtype=object)},
    }
    for name, change in tamper.items():
        run = root / "tampered" / name.replace(" ", "_")
        run.mkdir(parents=True)
        np.savez_compressed(run / "record.npz", **change(good))
        got = F.rejudge5("inspection", F.PACK5["inspection"]["file"], world, seed, run)
        check(f"outside judge: refused, {name}", got is not None and (got.get("no_record") or got.get("matches") is False), json.dumps({k: got.get(k) for k in ("no_record", "matches", "why")}) if got else "no reply")
    linked = root / "tampered" / "link"
    linked.mkdir()
    os.symlink(honest / "record.npz", linked / "record.npz")
    got = F.rejudge5("inspection", F.PACK5["inspection"]["file"], world, seed, linked)
    check("outside judge: a record that is a link counts as no record", got == {"no_record": True}, str(got))
    secret_file = root / "tampered" / "not_for_the_sandbox.txt"
    secret_file.write_text("keep")
    trusted = root / "tampered" / "trusted_write"
    trusted.mkdir()
    os.symlink(secret_file, trusted / "job_result.json")
    F.write_trusted(trusted / "job_result.json", {"verdict": "x"})
    check("write_trusted never follows a link the sandbox left", secret_file.read_text() == "keep" and not (trusted / "job_result.json").is_symlink())


def full(root):
    t0 = time.time()
    fast_world, slow_world, normal = plant_world(18.0), plant_world(18.5), plant_world(30.0)
    target = base_run(root, "target", fast_world, 11)
    held = base_run(root, "held", slow_world, 12)
    passed = base_run(root, "passed", normal, 13)
    check("the frozen robot fails the tight worlds and passes the normal one, and each sandbox run equals the run outside it", target[3]["verdict"] == "timed_out" and held[3]["verdict"] == "timed_out" and passed[3]["passed"], f"{target[3]['verdict']}, {held[3]['verdict']}, {passed[3]['verdict']}, {time.time() - t0:.0f} s")
    rejudge_attacks(root, slow_world, 12)

    bounty_root = root / "board"
    runs = root / "runs_full"
    small_campaign(runs, [target], [held], [passed])
    info = X.post(SESSION, "c1", "timed_out", "Tight route", "Check company", 40, window=60, root=bounty_root, runs=runs)
    bid = info["id"]
    check("an inspection bounty now says it re-judges", info["replay_rejudge"] is True)
    fix_source = INSPECTION.replace("SPEED_MPS = 0.8", "SPEED_MPS = 1.0", 1)

    # Through the real gate, with the real code rules.
    row = FG.run(X.reserve(bid, "mallory", fix_source.replace("SPEED_MPS = 1.0", "SPEED_MPS = __import__('pathlib').Path('/tmp/x').write_text('owned')\nSPEED_MPS = 1.0", 1) + "\n", bounty_root), bounty_root)
    check("gate: the F1 forger gets refused by the code rules and never runs", row["result"]["code"] == "refused_source" and row["payout"] is None, row["result"]["words"][:90])
    row = FG.run(X.reserve(bid, "mallory", INSPECTION + JUDGE_PATCH, bounty_root), bounty_root)
    check("gate: a judge patch gets refused by the code rules", row["result"]["code"] == "refused_source" and row["payout"] is None, row["result"]["words"][:90])

    # The layer behind the rules: the whole gate again, with the code rules off in its child process, as if a new bypass existed.
    runner = root / "rules_off_runner.py"
    runner.write_text(RULES_OFF_RUNNER.format(bounty=str(HERE)))
    real_runner = X.RUNNER
    X.RUNNER = runner
    try:
        for name, source, tester in (("a controller that patches the judge in its own process", INSPECTION + JUDGE_PATCH + "# rules off\n", "patcher"), ("a controller that writes a forged record of a walked route", INSPECTION + RECORD_FORGE, "recorder")):
            row = FG.run(X.reserve(bid, tester, source, bounty_root), bounty_root)
            r = row["result"]
            mismatches = sum(s["replay_mismatch"] for s in (r.get("sets") or {}).values())
            check(f"gate, rules off: no payout for {name}", r["code"] == "replay_mismatch" and mismatches > 0 and row["payout"] is None and X.view(bid, bounty_root)["available"] == 40, f"{r['code']}, {mismatches} mismatches: {r['words'][:80]}")
        row = FG.run(X.reserve(bid, "repeat", "SPEED_MPS = 2.0\n" + fix_source, bounty_root), bounty_root)
        check("gate, rules off: a repeated constant has no numbers the judge will use, so no payout", row["result"]["code"] == "not_rejudged" and row["payout"] is None, row["result"]["words"][:90])
    finally:
        X.RUNNER = real_runner

    # The same forge for the window robot: a controller that runs an easy world in place of the given one, and leaves a record that replays by itself.
    session, cid = WINDOW_CAMPAIGN.split("/")
    plan = json.loads((X.SERVER_RUNS / session / "campaigns" / cid / "scenarios.json").read_text())
    grid = {r["index"]: r for r in json.loads((X.SERVER_RUNS / session / "campaigns" / cid / "grid.json").read_text())["rows"]}
    failing = next(w for w in plan["worlds"] if grid[w["index"]]["verdict"] == "stalled")
    hostile = root / "window_swap.py"
    hostile.write_text(WINDOW + WINDOW_SWAP)
    swap = F.trial5("window", str(hostile), failing, root / "window_swap", True)
    check("window: a run on a swapped easy world is caught outside the sandbox", swap["verdict"] == "replay_mismatch" and not swap["passed"], swap["reason"][:110])
    honest = F.trial5("window", str(F.PACK5["window"]["file"]), failing, root / "window_honest", True)
    check("window: the honest run on that world keeps its true verdict", honest["verdict"] == "stalled" and honest["rejudged"], honest["verdict"])
    good = F.trial5("window", str(HERE / "fixtures" / "fix5" / "good_match_fan.py"), failing, root / "window_good", True)
    check("window: a real fix on that world passes outside the sandbox", good["passed"] and good["rejudged"], good["reason"][:90])

    # The real honest fix, over HTTP on this board's own port, from submit to paid.
    port = ARGS.port
    log = open(root / "server.log", "ab")
    H.own_all(bounty_root)
    server = subprocess.Popen([str(X.PYTHON), str(HERE / "board_server.py"), "--root", str(bounty_root), "--port", str(port)], stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if http(port, "GET", "/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.2)
        status, reply = http(port, "POST", f"/api/bounties/{bid}/fix", {"tester": "ana", "source": fix_source})
        check("honest: submit returns the secret once", status == 202 and len(reply.get("claim_secret", "")) >= 32, str(status))
        secret, n = reply["claim_secret"], reply["n"]
        while True:
            fix = http(port, "GET", f"/api/bounties/{bid}/fixes/{n}")[1]
            if fix["state"] not in ("queued", "running"):
                break
            time.sleep(2)
        r = fix["result"]
        check("honest: a real constant fix gets accepted after the outside judge", r["code"] == "accepted" and fix["payout"]["status"] == "Pending" and sum(s["replay_mismatch"] + s["not_rejudged"] for s in r["sets"].values()) == 0, f"{r['words'][:80]} sets {json.dumps({k: [v['better'], v['worse'], v['same']] for k, v in r['sets'].items()})}, proof {r['proof_wall_s']} s")
        time.sleep(max(0.0, fix["payout"]["dispute_ends_at"] - time.time()) + 0.5)
        check("honest: finalize after the window", http(port, "POST", f"/api/bounties/{bid}/fixes/{n}/finalize", {})[0] == 200)
        status, _ = http(port, "POST", f"/api/bounties/{bid}/fixes/{n}/claim", {"tester": "ana"})
        check("honest: a claim with no secret field is refused", status == 400, str(status))
        status, reply = http(port, "POST", f"/api/bounties/{bid}/fixes/{n}/claim", {"tester": "ana", "secret": "wrong"})
        check("honest: a claim with the wrong secret is refused", status == 403 and reply["error"] == "bad_secret", str(status))
        status, reply = http(port, "POST", f"/api/bounties/{bid}/fixes/{n}/claim", {"tester": "mallory", "secret": secret})
        check("honest: another name with the right secret is refused", status == 409 and "NotSubmitter" in reply["reason"], str(status))
        status, reply = http(port, "POST", f"/api/bounties/{bid}/fixes/{n}/claim", {"tester": "ana", "secret": secret})
        check("honest: the submitter gets paid", status == 200 and reply["fix"]["payout"]["status"] == "Claimed" and reply["bounty"]["balance"]["claimed_by_tester"] == {"ana": 40}, json.dumps(reply["bounty"]["balance"]))
    finally:
        server.terminate()
        server.wait(10)
    print(f"full section: {time.time() - t0:.0f} s", flush=True)


def demo_campaign(campaign):
    """The stored window batch in the shape of a finished campaign. Returns its worlds."""
    import gzip
    demo = X.POLICY / "runs" / "demo" / "window"
    with gzip.open(demo / "scenarios.json.gz", "rt") as f:
        plan = json.load(f)
    with gzip.open(demo / "timeline.json.gz", "rt") as f:
        last = json.load(f)[-1]
    for w in plan["worlds"]:
        if not w["held_back"]:
            run, source = campaign / f"w{w['index']:03d}", demo / f"w{w['index']:03d}"
            (run / "run").mkdir(parents=True)
            shutil.copyfile(source / "job_result.json", run / "job_result.json")
            shutil.copyfile(source / "run" / "actions.jsonl.gz", run / "run" / "actions.jsonl.gz")
            with gzip.open(source / "export" / "result.json.gz", "rb") as f:
                (run / "run" / "result.json").write_bytes(f.read())
    (campaign / "scenarios.json").write_text(json.dumps(plan))
    held = {w["index"]: w["held_back"] for w in plan["worlds"]}
    (campaign / "grid.json").write_text(json.dumps({"pack": "window", "running": False, "rows": [{**r, "held_back": held[r["index"]]} for r in last["rows"]]}))
    return plan["worlds"]


def code_copy(root, edit=None):
    """A copy of what a replay imports, so one test can change it."""
    out = root / f"stale_code_{time.monotonic_ns()}"
    shutil.copytree(X.POLICY / "highrise5", out / "highrise5", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(X.POLICY / "packs" / "window", out / "packs" / "window", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(X.POLICY / "packs" / "__init__.py", out / "packs" / "__init__.py")
    (out / "bounty").mkdir()
    shutil.copyfile(HERE / "rejudge.py", out / "bounty" / "rejudge.py")
    (out / "server").mkdir()
    shutil.copyfile(X.POLICY / "server" / "pack_job.py", out / "server" / "pack_job.py")
    if edit:
        edit(out / "highrise5")
    return out


DENSE_AIR = ("rho = (AIR_PRESSURE_PA - e) / (287.05 * kelvin) + e / (461.5 * kelvin)", "rho = 1.15 * ((AIR_PRESSURE_PA - e) / (287.05 * kelvin) + e / (461.5 * kelvin))")


def thicker_air(folder):
    path = folder / "world5.py"
    source = path.read_text()
    if DENSE_AIR[0] not in source:
        raise SystemExit("The density attack no longer finds its line in world5.py.")
    path.write_text(source.replace(*DENSE_AIR))


def stale_rule(root):
    """A stored batch, in the shape of a campaign, against copies of the code. Each stored action log replays on the copy, with no controller."""
    campaign = root / "stale_campaign"
    worlds = demo_campaign(campaign)
    base = hashlib.sha256(WINDOW.encode()).hexdigest()
    code = lambda edit=None: code_copy(root, edit)
    stale = lambda rows, code_root, sha=base: X._is_stale(campaign, rows, "window", sha, code_root)
    append = lambda name, text: (lambda folder: (folder / name).write_text((folder / name).read_text() + text))
    check("the stored batch is not stale on the code as it is", not stale(worlds, code()))
    check("a world-building file that alters no compiled physics passes", not stale(worlds, code(append("world5.py", "\nNEW_KIND = 'generated'\n"))))
    hidden = next(w for w in worlds if w["held_back"])
    alter = f"""
_real_compile = compile
_hidden = json.dumps(W.validate(json.loads({json.dumps(hidden['world'])!r})), sort_keys=True)
def compile(world):
    physics, view, effects = _real_compile(world)
    return (physics + "<!-- this world now differs -->" if json.dumps(world, sort_keys=True) == _hidden else physics), view, effects
"""
    altered = code(append("compile5.py", alter))
    check("a change that alters only a hidden world's physics is refused", stale(worlds, altered))
    check("the same change leaves every other world's physics alone", not stale([w for w in worlds if w is not hidden], altered))
    check("a world with no physics hash is refused", stale([{k: v for k, v in w.items() if k != "hash"} if w is hidden else w for w in worlds], code()))
    check("a held-back world whose stored hash differs is refused", stale([{**w, "hash": "0" * 64} if w is hidden else w for w in worlds], code()))
    public = next(w for w in worlds if not w["held_back"])
    check("a public world with no stored result is refused", stale([{**public, "index": 999}], code()))
    for name in ("judge5.py", "sim5.py", "run_trial5.py"):
        check(f"a change of a single byte in {name} is refused", stale(worlds, code(append(name, "\n# changed\n"))))
    check("a stored run from another controller is refused", stale(worlds, code(), "0" * 64))
    broken = code(append("compile5.py", "\nraise SystemExit(3)\n"))
    check("a compile error counts as changed", stale(worlds, broken))
    dense = code(thicker_air)
    physics = [{"world": w["world"], "physics": w["hash"]} for w in worlds]
    check("attack: air density x1.15 in world5.py leaves every physics hash the same, so a hash alone misses it", X._same_physics(physics, dense / "highrise5"))
    check("attack: that density change is refused, since the stored actions no longer replay", stale(worlds, dense))
    grime = code(append("scene5.py", "\n_real_regions = regions\ndef regions(world, kind, value):\n    return [(*r[:4], r[4] * 0.5) for r in _real_regions(world, kind, value)]\n"))
    check("attack: a sim change in scene5.py leaves every physics hash the same", X._same_physics(physics, grime / "highrise5"))
    check("attack: that scene5.py change is refused too", stale(worlds, grime))
    run = campaign / f"w{public['index']:03d}"
    real = (run / "job_result.json").read_text()
    verdict = json.loads(real)
    (run / "job_result.json").write_text(json.dumps({**verdict, "verdict": "passed" if verdict["verdict"] != "passed" else "slip_distance"}))
    check("attack: a stored verdict the replay does not give is refused", stale(worlds, code()))
    (run / "job_result.json").write_text(real)
    actions = (run / "run" / "actions.jsonl.gz").read_bytes()
    (run / "run" / "actions.jsonl.gz").unlink()
    check("attack: a public world with no stored actions is refused", stale(worlds, code()))
    (run / "run" / "actions.jsonl.gz").write_bytes(actions)
    payout_rule(root, dense)


def payout_rule(root, dense):
    """The whole money path with a real ledger. The proof itself is stubbed, since what this tests is the last check before a payout."""
    runs = root / "payout_runs"
    worlds = demo_campaign(runs / SESSION / "campaigns" / "c1")
    grid = json.loads((runs / SESSION / "campaigns" / "c1" / "grid.json").read_text())
    group = max(X._fixable_groups("window", grid["rows"]).items(), key=lambda kv: kv[1])[0]
    made = root / "payout_board"
    check("attack: a post on the changed code is refused", refused(lambda: X.post(SESSION, "c1", group, "Dense air", "Check company", 40, root=made, runs=runs, code_root=dense), "campaign_stale"))
    bid = X.post(SESSION, "c1", group, "Honest post", "Check company", 40, root=made, runs=runs)["id"]
    folder = X.folder_of(bid, made)
    check("an honest post on the code as it is goes through", B._ledger(folder).bounty["available"] == 40 and len(worlds) > 0)
    check("the bounty keeps its own copy of the stored actions", all((folder / "campaign" / f"w{w['index']:03d}" / "run" / "actions.jsonl.gz").is_file() for w in worlds if not w["held_back"]))

    def proved(code):
        return {"accepted": code == "accepted", "code": code, "words": "A stubbed proof.", "stage": "done", "flags": [], "patched_sha256": "ab" * 32, "sets": {}, "target": []}
    real_run = FG._run
    try:
        FG._run = lambda *a: proved("accepted")
        row = FG.run(X.reserve(bid, "ana", WINDOW + "\n# only a comment\n", made, secret="s1"), made, code_root=dense)
        check("attack: a comment-only fix on changed physics gets no payout", row["result"]["code"] == "campaign_stale" and row["payout"] is None, row["result"]["code"])
        check("it holds no units", B._ledger(folder).bounty["available"] == 40)
        FG._run = lambda *a: proved("awaiting_company")
        row = FG.run(X.reserve(bid, "ana", WINDOW + "\n# a flagged line\n", made, secret="s2"), made)
        row = FG.company_decide(bid, row["n"], True, made, code_root=dense)
        check("attack: a company approval on changed physics gets no payout", row["result"]["code"] == "campaign_stale" and row["payout"] is None and B._ledger(folder).bounty["available"] == 40, row["result"]["code"])
        FG._run = lambda *a: proved("accepted")
        public = next(w for w in worlds if not w["held_back"])
        actions = folder / "campaign" / f"w{public['index']:03d}" / "run" / "actions.jsonl.gz"
        kept = actions.read_bytes()
        actions.unlink()
        row = FG.run(X.reserve(bid, "ana", WINDOW + "\n# a third\n", made, secret="s3"), made)
        check("attack: a payout with a stored log gone is refused", row["result"]["code"] == "campaign_stale" and row["payout"] is None, row["result"]["code"])
        actions.write_bytes(kept)
        row = FG.run(X.reserve(bid, "bob", WINDOW + "\n# a fourth\n", made, secret="s4"), made)
        check("an accepted proof on the code as it is holds the pay", row["payout"] and row["payout"]["status"] == "Pending" and B._ledger(folder).bounty["available"] == 0, str(row["result"]["code"]))
    finally:
        FG._run = real_run


def inspection_rule(root):
    """Finding: inspection skipped the stale rule. Hashes only here, no sim."""
    base = hashlib.sha256(INSPECTION.encode()).hexdigest()
    missing = root / "not_there"
    import gzip
    demo = X.POLICY / "runs" / "demo" / "inspection"
    with gzip.open(demo / "scenarios.json.gz", "rt") as f:
        check("the stored inspection batch names the code as it is", not X._is_stale(demo, json.load(f)["worlds"], "inspection", base))
    check("attack: an inspection post with nothing stored is refused", X._is_stale(missing, [{}], "inspection", base))
    check("attack: an inspection post with no worlds is refused", X._is_stale(missing, [], "inspection", base))
    code_root = root / "inspection_code"
    for name in X.FROZEN_FILES["inspection"]:
        (code_root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(X.POLICY / name, code_root / name)
    campaign = root / "inspection_campaign"
    (campaign / "w001").mkdir(parents=True)
    worlds = [{"index": 1, "hash": "a" * 64, "world": {}, "held_back": False}, {"index": 2, "hash": "b" * 64, "world": {}, "held_back": True}]
    job = campaign / "w001" / "job_result.json"
    stale = lambda rows=worlds, sha=base, code=code_root: X._is_stale(campaign, rows, "inspection", sha, code)
    check("attack: a stored inspection run with no result is refused", stale())
    job.write_text(json.dumps({"verdict": "timed_out"}))
    check("attack: a stored inspection run with no code hashes is refused", stale())
    job.write_text(json.dumps({"verdict": "timed_out", "code_sha256": X.frozen_shas("inspection", code_root)}))
    check("a stored inspection run with the same code passes", not stale())
    check("attack: another controller is refused", stale(sha="0" * 64))
    check("attack: a held-back world with no hash is refused", stale([worlds[0], {**worlds[1], "hash": None}]))
    check("attack: code that is not there is refused", stale(code=missing))
    for name in X.FROZEN_FILES["inspection"]:
        kept = (code_root / name).read_bytes()
        (code_root / name).write_bytes(kept + b"\n# changed\n")
        check(f"attack: a change of one line in {Path(name).name} is refused", stale())
        (code_root / name).write_bytes(kept)


def site_rule(root):
    """The World ID findings, with labelled mock replies. No real World ID call."""
    sys.path.insert(0, str(X.POLICY / "server"))
    import site_world as W
    human = {"PATH": os.environ["PATH"], "WORLD_APP_ID": "app_mock", "WORLD_ACTION": "crashlab-site-login", "WORLD_RP_ID": "rp_mock", "WORLD_RP_SIGNING_KEY": "0x" + "11" * 32, "WORLD_ENVIRONMENT": "staging"}
    device = {**human, "WORLD_CREDENTIAL": "device"}
    db = root / "site_world.sqlite"

    def nonce():
        value = f"n{time.monotonic_ns()}"
        with W.closing(W._open(db)) as d:
            d.execute("INSERT INTO nonces VALUES (?,?,?)", (value, "b", time.time() + 60))
        return value

    def agrees(result, env):
        return True, {"success": True, "environment": "staging", "protocol_version": result["protocol_version"], "results": [{"identifier": i.get("identifier"), "success": True} for i in result["responses"]]}

    def human_try(*identifiers):
        spot = time.monotonic_ns()
        items = [{"identifier": name, "nullifier": hex(spot + n), "proof": ["0x1"]} for n, name in enumerate(identifiers)]
        result = {"protocol_version": "4.0", "nonce": nonce(), "action": human["WORLD_ACTION"], "session_id": f"session_{spot}", "environment": "staging", "responses": items}
        try:
            return W.verify(result, "b", None, human, db, agrees)["credential"]
        except W.Rejected as r:
            return r.code

    def device_try(identifier, protocol="3.0"):
        value = nonce()
        item = {"identifier": identifier, "nullifier": hex(time.monotonic_ns()), "merkle_root": "0x1", "proof": "0x1", "signal_hash": W._signal_hash(value, device)}
        result = {"protocol_version": protocol, "nonce": value, "action": device["WORLD_ACTION"], "environment": "staging", "responses": [item]}
        try:
            return W.verify(result, "b", None, device, db, agrees)["credential"]
        except W.Rejected as r:
            return r.code
    for name in ("selfie", "passport", "mnc", "device", "orb"):
        check(f"attack: human mode refuses a client that picks {name}", human_try(name) == "wrong_credential")
    check("attack: human mode refuses a good proof beside a chosen one", human_try("proof_of_human", "selfie") == "wrong_credential")
    check("attack: human mode refuses a proof with no identifier", human_try(None) == "wrong_credential")
    check("human mode takes proof_of_human", human_try("proof_of_human") == "human")
    for name in ("proof_of_human", "selfie", "passport", "mnc", "orb"):
        check(f"attack: device mode refuses a client that picks {name}", device_try(name) == "wrong_credential")
    check("device mode takes the device identifier", device_try("device") == "device")
    W.add_login("old_human", "0xa", "staging", "human", db)
    W.add_login("old_device", "0xb", "staging", "device", db)
    check("attack: an old human login reads as signed out in device mode", W.login_of("old_human", db, env=device) is None)
    check("attack: an old device login reads as signed out in human mode", W.login_of("old_device", db, env=human) is None)
    check("a login still works in its own mode", W.login_of("old_human", db, env=human)["human_id"] == "0xa" and W.login_of("old_device", db, env=device)["human_id"] == "0xb")


def could_not_run(root):
    """A real broken sandbox: a worker that dies on import, as a missing module does. The proof's report is stubbed, since that is not what this tests."""
    import gzip
    with gzip.open(X.POLICY / "runs" / "demo" / "window" / "scenarios.json.gz", "rt") as f:
        world = next(w for w in json.load(f)["worlds"] if not w["held_back"])
    entry = {k: world[k] for k in ("index", "name", "world", "seed")}
    broken = root / "broken_worker.py"
    broken.write_text("import generate_object\n")
    real_worker = F.WORKER5
    probe = root / "canary"
    check("the sandbox check passes when the sandbox works", F.sandbox_works5("window", entry, probe / "good"))
    F.WORKER5 = broken
    try:
        check("the sandbox check fails on a real import crash in the sandbox", not F.sandbox_works5("window", entry, probe / "bad"))
    finally:
        F.WORKER5 = real_worker

    made = root / "cnr"
    runs = root / "cnr_runs"
    small_campaign(runs, [("t", {}, 1, FAKE)], [("h", {}, 2, FAKE)], [("p", {}, 3, FAKE_PASS)])
    info = X.post(SESSION, "c1", "timed_out", "Crash check", "Check company", 40, root=made, runs=runs)
    bid = info["id"]
    crashed = {**FG._fail("target_not_fixed", "1 of 1 failing worlds still fail.", "sim"), "target": [{"index": 0, "name": "w", "old": "timed_out", "new": "controller_crashed", "passed": False, "safe_hold": False, "reason": "x"}], "sets": {"held_back": {"n": 15, "better": 0, "worse": 15, "same": 0, "passed_before": 0, "passed_after": 0, "limits_hit": 0, "replay_mismatch": 0}}}
    real_run, real_works = FG._run, FG._sandbox_works
    FG._run = lambda *a: crashed
    source = INSPECTION + "\n# a fix\n"
    try:
        FG._sandbox_works = lambda *a: False
        row = FG.run(X.reserve(bid, "ana", source, made, secret="s"), made)
        check("a sandbox crash reads as could not run, not as a verdict", row["state"] == "could_not_run" and row["result"]["code"] == "could_not_run" and "could not run" in row["result"]["words"], row["result"]["code"])
        check("it shows no worse count", row["result"]["sets"] is None and row["result"]["target"] == [])
        check("it holds no pay", row["payout"] is None and B._ledger(X.folder_of(bid, made)).bounty["available"] == 40)
        again = X.reserve(bid, "ana", source, made, secret="s2")
        check("it does not use a submission, and the same source can go again", again["used_before"] == 0, again["used_before"])
        FG._sandbox_works = lambda *a: True
        row = FG.run(again, made)
        check("a crash from the source itself stays a charged result", row["state"] == "done" and row["result"]["code"] == "target_not_fixed", row["result"]["code"])
        check("that one does use a submission", X.reserve(bid, "ana", source + "# other\n", made, secret="s3")["used_before"] == 1)
    finally:
        FG._run, FG._sandbox_works = real_run, real_works


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--port", type=int, default=5398)
    ARGS = ap.parse_args()
    root = new_root()
    f1()
    f2()
    stale_rule(root)
    inspection_rule(root)
    site_rule(root)
    could_not_run(root)
    f3_and_secret(root)
    arc_agent(root)
    budget_owner(root)
    if not ARGS.fast:
        full(root)
    print(f"{sum(results)} of {len(results)} passed. Folder {root}", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
