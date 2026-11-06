"""Real checks of the bounty board: check_board.py --fast | --gate | --server. Exit 0 only if every case behaves.

--fast runs no sim. --gate runs the real gate. --server starts board_server.py on port 5298 and stops it at the end.
All data goes in a new folder under policy/runs/board/, named check_<time>.
"""
import argparse
import json
import stat
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--gate", action="store_true")
    a = ap.parse_args()
    root = G.POLICY / "runs" / "board" / f"check_{time.strftime('%Y%m%d_%H%M%S')}"
    if a.fast:
        fast(root)
    if a.gate:
        gate_flow(root)
    print(f"{sum(results)}/{len(results)} passed; output {root}")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
