"""Real checks of the bounty board: check_board.py --fast | --gate | --server. Exit 0 only if every case behaves.

--fast runs no sim. --gate runs the real gate. --server starts board_server.py on port 5298 and stops it at the end.
All data goes in a new folder under policy/runs/board/, named check_<time>.
"""
import argparse
import json
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_gate
import board_spec
import board_store as B
import gate as G

W = G.W
SALT = "ab" * 32
FIXTURES = HERE / "fixtures"
BASE = "http://127.0.0.1:5298"
PAGE = "http://localhost:5299"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def refused(partial, code="bad_spec"):
    try:
        board_spec.build(1, partial, SALT)
    except G.Rejected as r:
        return r.code == code, f"{r.code}: {r.reason}"
    return False, "accepted"


def fast(root):
    spec, narrowed = board_spec.build(1, {"wind_ms": [0, 25]}, SALT)
    check("wind 0-25 becomes a spec", spec["limits"]["steady_wind_ms"] == [0, 25] and spec["limits"]["gust_speed_ms"] == [0, 25] and narrowed == ["gust_speed_ms", "steady_wind_ms"])
    others = {k: v for k, v in spec["limits"].items() if k not in narrowed}
    check("other fields keep the schema range", all(tuple(v) == W.FIELDS[k] for k, v in others.items()), f"{len(others)} fields")
    check("gate accepts the spec", bool(G.check_spec(spec)) and spec["frozen"] == G.current_frozen())
    for name, partial, code in (
        ("limit above the schema", {"wind_ms": [0, 30]}, "bad_spec"),
        ("limit below the schema", {"suction_pa": [100, 4000]}, "bad_spec"),
        ("low above high", {"suction_pa": [4000, 3000]}, "bad_spec"),
        ("limit that excludes the reference world", {"wetness": [0.5, 1.0]}, "bad_spec"),
        ("not two numbers", {"wetness": [0.5]}, "bad_spec"),
        ("true as a number", {"wetness": [False, True]}, "bad_spec"),
        ("unknown field", {"robot_power": [0, 1]}, "bad_limits"),
        ("same field twice", {"wind_ms": [0, 25], "gust_speed_ms": [0, 20]}, "bad_limits"),
        ("NaN", {"wetness": [float("nan"), 1.0]}, "bad_spec"),
    ):
        ok, detail = refused(partial, code)
        check(f"refuses {name}", ok, detail)

    root.mkdir(parents=True)
    first = B.post("Wind on tower A", "Sample company A", ["Night cleaning in wind"], 100, 10, {"wind_ms": [0, 25]}, root=root)
    second = B.post("Wet glass", "Sample company B", [], 50, 25, {"wetness": [0, 0.5]}, root=root)
    rows = B.list_bounties(root)
    check("two posts list as open with the ledger label", [r["id"] for r in rows] == [1, 2] and all(r["status"] == "open" and r["ledger_label"] == "Local ledger. Not on chain." for r in rows), rows[0]["ledger_label"])
    check("each bounty has its own folder, spec id and ledger id", all(json.loads((root / str(i) / "spec.json").read_text())["bounty_id"] == i and json.loads((root / str(i) / "ledger.json").read_text())["bounty"]["id"] == i for i in (1, 2)))
    check("get returns the post", B.get(2, root)["per_failure"] == 25 and first["limits"]["gust_speed_ms"] == [0, 25] and second["narrowed"] == ["wetness"])
    check("robot is fixed", all(r["robot"] == "High-rise window robot" for r in rows))
    check("no view holds the salt", (root / "1" / "salt.hex").read_text() not in json.dumps(rows))
    check("salt file is private", stat.S_IMODE((root / "1" / "salt.hex").stat().st_mode) == 0o600)
    check("scenario text is labelled as not enforced", "does not enforce" in rows[0]["scenarios_label"])
    for name, kw, code in (("pay above the cap", {"cap": 5, "per_failure": 10}, "bad_bounty"), ("zero cap", {"cap": 0}, "bad_bounty"), ("true as pay", {"per_failure": True}, "bad_bounty"), ("short window", {"window": 5}, "bad_bounty"), ("limit outside the schema", {"limits": {"wind_ms": [0, 30]}}, "bad_spec")):
        try:
            B.post(**{"title": "x", "company": "y", "scenarios": [], "cap": 10, "per_failure": 5, "limits": {}, "root": root, **kw})
            check(f"post refuses {name}", False, "accepted")
        except B.BoardError as e:
            check(f"post refuses {name}", e.code == code, f"{e.code}: {e.reason}")
    check("a refused post leaves no bounty", len(B.list_bounties(root)) == 2)


def gate_flow(root):
    root.mkdir(parents=True)
    meta = json.loads((FIXTURES / "meta.json").read_text())
    world = (FIXTURES / "failing.json").read_text()
    seed = meta["failing_seed"]
    wide = B.post("Wide limits", "Sample company", ["Any weather"], 100, 10, {"wind_ms": [0, 25]}, root=root)
    narrow = B.post("Dry glass only", "Sample company", [], 100, 10, {"wetness": [0, 0.5]}, root=root)

    before = time.time()
    row = board_gate.run(B.reserve(narrow["id"], "ana", seed, root), world, root)
    r = row["result"]
    gate_dirs = list((root / str(narrow["id"]) / "submissions" / "1" / "gate").rglob("claim"))
    check("same world, narrow limit: outside_limits with 0 runs", r["code"] == "outside_limits" and r["runs"] == 0 and not gate_dirs and row["payout"] is None, f"{r['reason']} {time.time() - before:.1f}s")
    check("narrow limit: ledger untouched", B.get(narrow["id"], root)["available"] == 100 and not B.get(narrow["id"], root)["failures"])

    before = time.time()
    row = board_gate.run(B.reserve(wide["id"], "ana", seed, root), world, root)
    r = row["result"]
    print(json.dumps(row, indent=1), flush=True)
    check("failing fixture, seed 3100024, wide limits: accepted", r["accepted"] and r["code"] == "accepted" and r["runs"] == 10, f"{r['code']}: {r['reason']} runs={r['runs']} {time.time() - before:.0f}s")
    money = B.get(wide["id"], root)
    check("ledger Pending, 10 test units held", row["payout"] and row["payout"]["status"] == "Pending" and money["failures"][r["fingerprint"]]["status"] == "Pending" and money["available"] == 90, f"available={money['available']}")
    check("verdict says World ID is not connected", r["human_cap"]["world_id_connected"] is False and r["human_cap"]["used"] == 0 and r["human_cap"]["cap"] == 5)
    if r["accepted"]:
        again = board_gate.run(B.reserve(wide["id"], "ben", seed + 1, root), world, root)
        check("same world again: duplicate, no second payout", again["result"]["code"] == "duplicate" and again["payout"] is None and B.get(wide["id"], root)["available"] == 90, f"code={again['result']['code']} runs={again['result']['runs']}")


def curl(method, path, body=None, origin=PAGE, host=None, ctype="application/json"):
    argv = ["curl", "-s", "-m", "20", "-X", method, "-w", "\n%{http_code}", f"{BASE}{path}"]
    if origin:
        argv += ["-H", f"Origin: {origin}"]
    if host:
        argv += ["-H", f"Host: {host}"]
    data = None
    if body is not None:
        data = body if isinstance(body, str) else json.dumps(body)
        argv += ["-H", f"Content-Type: {ctype}", "--data-binary", "@-"]
    out = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=30).stdout
    text, _, status = out.rpartition("\n")
    try:
        return int(status), json.loads(text)
    except ValueError:
        return int(status or 0), text


def wait_done(bounty, n, most_s=180):
    end = time.time() + most_s
    while time.time() < end:
        _, row = curl("GET", f"/api/bounties/{bounty}/submissions/{n}")
        if row["state"] == "done":
            return row
        time.sleep(0.5)
    raise SystemExit(f"submission {n} on bounty {bounty} did not finish")


def start_server(root):
    p = subprocess.Popen([sys.executable, str(HERE / "board_server.py"), "--root", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        time.sleep(0.2)
        if curl("GET", "/api/health")[0] == 200:
            return p
    p.terminate()
    raise SystemExit("the board server did not start")


def server_flow(root):
    root.mkdir(parents=True)
    meta = json.loads((FIXTURES / "meta.json").read_text())
    world = (FIXTURES / "failing.json").read_text()
    seed = meta["failing_seed"]
    server = start_server(root)
    try:
        for name, kw in (("no Origin", {"origin": None}), ("other origin", {"origin": "http://evil.example"}), ("main app origin", {"origin": "http://localhost:5199"}), ("other Host", {"host": "evil.example:5298"})):
            status, out = curl("GET", "/api/bounties", **kw)
            check(f"refuses {name}", status == 403 and out["error"] == "origin_refused", f"{status}")
        status, out = curl("POST", "/api/bounties", {"title": "x", "company": "y", "scenarios": [], "cap": 10, "per_failure": 5, "limits": {}}, origin=None)
        check("refuses a post with no Origin", status == 403, f"{status}")
        check("still no bounty after refused posts", curl("GET", "/api/bounties")[1]["bounties"] == [])

        status, narrow = curl("POST", "/api/bounties", {"title": "Dry glass only", "company": "Sample company", "scenarios": ["Dry day"], "cap": 100, "per_failure": 10, "limits": {"wetness": [0, 0.5]}})
        check("post bounty", status == 201 and narrow["status"] == "open", f"{status}")
        status, wide = curl("POST", "/api/bounties", {"title": "Wind up to 25", "company": "Sample company", "scenarios": [], "cap": 20, "per_failure": 10, "limits": {"wind_ms": [0, 25]}})
        check("post second bounty", status == 201 and wide["id"] == narrow["id"] + 1, f"{status}")
        status, out = curl("POST", "/api/bounties", {"title": "x", "company": "y", "scenarios": [], "cap": 10, "per_failure": 5, "limits": {"wind_ms": [0, 30]}})
        check("refuses a limit outside the schema", status == 400 and out["error"] == "bad_spec", f"{status} {out['reason']}")
        status, out = curl("POST", "/api/bounties", {"title": "x", "company": "y", "scenarios": [], "cap": 10, "per_failure": 5, "limits": {}, "robot": "my robot"})
        check("refuses a chosen robot", status == 400 and out["error"] == "bad_fields", f"{status}")
        status, out = curl("GET", "/api/bounties")
        check("list shows both open, with both labels", len(out["bounties"]) == 2 and all(b["status"] == "open" for b in out["bounties"]) and out["ledger_label"] == "Local ledger. Not on chain." and out["world_id_label"] == "World ID is not connected", f"{out['ledger_label']} {out['world_id_label']}")
        salts = [(root / str(i) / "salt.hex").read_text() for i in (narrow["id"], wide["id"])]
        check("no reply holds a salt", not any(s in json.dumps(out) for s in salts))

        submit = f"/api/bounties/{narrow['id']}/submit"
        for name, body, want, ctype in (("world over 16 KB", {"tester": "t", "seed": 1, "world": " " * (16 * 1024 + 1)}, 413, "application/json"), ("body over the limit", {"tester": "t", "seed": 1, "world": " " * (60 * 1024)}, 413, "application/json"),
                                        ("not JSON", "{not json", 400, "application/json"), ("plain text type", {"tester": "t", "seed": 1, "world": world}, 415, "text/plain"), ("seed as text", {"tester": "t", "seed": "--out", "world": world}, 400, "application/json"),
                                        ("bad name", {"tester": "../x", "seed": 1, "world": world}, 400, "application/json"), ("extra field", {"tester": "t", "seed": 1, "world": world, "x": 1}, 400, "application/json")):
            status, _ = curl("POST", submit, body, ctype=ctype)
            check(f"refuses {name}", status == want, f"{status}")
        check("refused submits use no place", curl("GET", f"/api/bounties/{narrow['id']}/submissions")[1]["submissions"] == [])
        status, out = curl("POST", "/api/bounties/99/submit", {"tester": "t", "seed": 1, "world": world})
        check("unknown bounty", status == 404, f"{status}")

        status, out = curl("POST", f"/api/bounties/{wide['id']}/submit", {"tester": "Ana", "seed": seed, "world": world})
        check("submit is queued", status == 202 and out["world_id_label"] == "World ID is not connected", f"{status} {out.get('used')} of {out.get('of')}")
        row = wait_done(wide["id"], out["n"])
        check("failing fixture accepted over HTTP, ledger Pending", row["result"]["code"] == "accepted" and row["result"]["runs"] == 10 and row["payout"]["status"] == "Pending", f"{row['result']['reason']} {row['wall_s']}s")
        status, money = curl("GET", f"/api/bounties/{wide['id']}")
        check("bounty shows the held amount", money["available"] == 10 and money["status"] == "open", f"available={money['available']}")

        fp = row["result"]["fingerprint"]
        step = lambda name, **body: curl("POST", f"/api/bounties/{wide['id']}/failures/{fp}/{name}", body)
        status, out = step("finalize")
        check("finalize before the window ends is refused", status == 409 and "DisputeWindowOpen" in out["reason"] and curl("GET", f"/api/bounties/{wide['id']}")[1]["balance"]["pending"] == 10, f"{status} {out['reason']}")
        status, out = step("claim", tester="Ana")
        check("claim before finalize is refused", status == 409 and "WrongStatus" in out["reason"], f"{status} {out['reason']}")

        status, third = curl("POST", "/api/bounties", {"title": "Reject test", "company": "Sample company", "scenarios": [], "cap": 10, "per_failure": 10, "limits": {}})
        status, out = curl("POST", f"/api/bounties/{third['id']}/submit", {"tester": "Ana", "seed": seed, "world": world})
        seen = 0
        while True:
            live = curl("GET", f"/api/bounties/{third['id']}/submissions/{out['n']}")[1]
            seen = max(seen, live.get("progress", {}).get("runs_done", 0))
            if live["state"] == "done":
                break
            time.sleep(0.3)
        check("progress counts real finished runs", 0 < seen <= 10 and live["result"]["runs"] == 10, f"saw {seen} of 10 before the end")
        check("a bounty with all its money held is not open", curl("GET", f"/api/bounties/{third['id']}")[1]["status"] == "cap_reached")
        status, out = curl("POST", f"/api/bounties/{third['id']}/submit", {"tester": "Late", "seed": seed, "world": world})
        check("submit to a used-up bounty is refused", status == 409 and out["error"] == "cap_reached", f"{status}")
        rejected_fp = live["result"]["fingerprint"]
        status, out = curl("POST", f"/api/bounties/{third['id']}/failures/{rejected_fp}/reject", {})
        money = curl("GET", f"/api/bounties/{third['id']}")[1]
        row3 = curl("GET", f"/api/bounties/{third['id']}/submissions/{live['n']}")[1]
        check("reject inside the window returns the money", status == 200 and money["available"] == 10 and money["balance"]["pending"] == 0 and row3["payout"]["status"] == "Rejected" and money["status"] == "open", f"{status} available={money['available']}")
        status, out = curl("POST", f"/api/bounties/{third['id']}/failures/{rejected_fp}/finalize", {})
        check("finalize after reject is refused", status == 409, f"{status} {out['reason']}")

        time.sleep(max(0.0, row["payout"]["dispute_ends_at"] - time.time()) + 0.5)
        status, out = step("reject")
        check("reject after the window is refused", status == 409 and "DisputeWindowClosed" in out["reason"], f"{status} {out['reason']}")
        status, out = step("claim", tester="Ana")
        check("claim before finalize is still refused after the window", status == 409, f"{status}")
        status, out = step("finalize")
        check("finalize after the window", status == 200 and out["failure"]["status"] == "Finalized" and out["bounty"]["balance"]["finalized"] == 10, f"{status} {out['failure']['status']}")
        status, out = step("claim", tester="Ben")
        check("claim by another name is refused", status == 409 and "NotSubmitter" in out["reason"], f"{status} {out['reason']}")
        status, out = step("claim", tester=" ANA ")
        balance = out["bounty"]["balance"]
        check("full path ends in Claimed with the right balance", status == 200 and out["failure"]["status"] == "Claimed" and balance["claimed"] == 10 and balance["pending"] == 0 and balance["finalized"] == 0 and balance["available"] == 10 and balance["claimed_by_tester"] == {"ana": 10} and balance["available"] + balance["claimed"] == wide["cap"], json.dumps(balance))
        check("the submission shows Claimed", curl("GET", f"/api/bounties/{wide['id']}/submissions/{row['n']}")[1]["payout"]["status"] == "Claimed")
        status, out = step("claim", tester="Ana")
        check("second claim is refused", status == 409, f"{status}")
        status, out = curl("POST", f"/api/bounties/{wide['id']}/failures/0x{'0' * 64}/finalize", {})
        check("unknown failure is refused", status == 409, f"{status} {out['reason']}")
        status, out = curl("POST", f"/api/bounties/{wide['id']}/failures/{fp}/finalize", {"x": 1})
        check("extra field on a step is refused", status == 400, f"{status}")

        base = f"/api/bounties/{wide['id']}/submissions/{row['n']}/replay"
        status, out = curl("POST", base, {})
        check("replay of the recorded run is written", status == 200 and out["base"] == base, f"{status}")
        status, manifest = curl("GET", f"{base}/manifest.json")
        check("replay files served, and the export matched the recorded run", status == 200 and manifest["replay_match"] is True and manifest["frames"] > 0, f"{manifest.get('frames')} frames")
        check("replay holds no other file", curl("GET", f"{base}/reference.json")[0] == 404 and curl("GET", f"{base}/..%2Fsubmission.json")[0] == 404 and curl("GET", f"{base}/salt.hex")[0] == 404)
        status, out = curl("POST", f"/api/bounties/{narrow['id']}/submissions/99/replay", {})
        check("no replay for an unknown submission", status == 404, f"{status}")

        for i in range(5):
            status, out = curl("POST", submit, {"tester": "Cap Check", "seed": seed + i, "world": world})
            if status != 202:
                check(f"cap submit {i + 1} queued", False, f"{status} {out}")
                continue
            row = wait_done(narrow["id"], out["n"], 60)
            check(f"submit {i + 1} of 5: outside_limits, 0 runs", row["result"]["code"] == "outside_limits" and row["result"]["runs"] == 0, f"{status}")
        status, out = curl("POST", submit, {"tester": " cap   CHECK ", "seed": seed + 9, "world": world})
        check("6th submit returns 429, labelled", status == 429 and out["error"] == "tester_cap" and out["world_id_label"] == "World ID is not connected", f"{status} {out['reason']}")
        status, out = curl("POST", submit, {"tester": "Other name", "seed": seed, "world": world})
        check("a new name gets past the cap, as the label says", status == 202, f"{status}")
        wait_done(narrow["id"], out["n"], 60)

        codes = []
        placed = []
        for i in range(8):
            status, out = curl("POST", submit, {"tester": f"queue {i}", "seed": seed, "world": world})
            codes.append(status)
            if status == 202:
                placed.append(out["n"])
        check("queue cap: one running and 4 waiting at most, the rest get 503", codes.count(503) >= 1 and set(codes) == {202, 503} and 4 <= len(placed) <= 5, f"{codes}")
        rows = [wait_done(narrow["id"], n, 120) for n in placed]
        spans = sorted((r["started_at"], r["started_at"] + r["wall_s"]) for r in rows)
        check("one gate at a time", all(a[1] <= b[0] + 0.15 for a, b in zip(spans, spans[1:])), f"{len(spans)} gates in {spans[-1][1] - spans[0][0]:.1f}s")
        status, out = curl("POST", submit, {"tester": f"queue {codes.index(503)}", "seed": seed, "world": world})
        check("a 503 did not use a place", status == 202 and out["used"] == 1, f"{status}")
        wait_done(narrow["id"], out["n"], 60)

        status, third = curl("POST", "/api/bounties", {"title": "Stop test", "company": "Sample company", "scenarios": [], "cap": 10, "per_failure": 10, "limits": {}})
        status, out = curl("POST", f"/api/bounties/{third['id']}/submit", {"tester": "Stop", "seed": seed, "world": world})
        time.sleep(3)
        running = curl("GET", f"/api/bounties/{third['id']}/submissions/{out['n']}")[1]["state"]
        server.terminate()
        server.wait(10)
        time.sleep(1)
        left = subprocess.run(["pgrep", "-f", str(root)], capture_output=True, text=True).stdout.split()
        check("stopping the server stops the running gate", running == "running" and not left, f"state was {running}, left={left}")
        server = start_server(root)
        row = curl("GET", f"/api/bounties/{third['id']}/submissions/{out['n']}")[1]
        check("after a restart that run shows interrupted", row["state"] == "interrupted", row["state"])
    finally:
        server.terminate()
        server.wait(10)
    code = subprocess.run(["curl", "-s", "-m", "2", "-o", "/dev/null", f"{BASE}/api/health"]).returncode
    check("server stopped, port closed", code != 0, f"curl exit {code}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--server", action="store_true")
    a = ap.parse_args()
    root = G.POLICY / "runs" / "board" / f"check_{time.strftime('%Y%m%d_%H%M%S')}"
    if a.fast:
        fast(root)
    if a.gate:
        gate_flow(root)
    if a.server:
        server_flow(root)
    print(f"{sum(results)}/{len(results)} passed; output {root}")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
