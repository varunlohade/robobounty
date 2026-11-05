"""Real runs of the bounty gate: check_gate.py [--fast]. Exit 0 only if every case behaves. --fast skips cases that need a sim.

The fixture salt below is public and for this check only. A real bounty needs a secret salt.
A controller or sim change can move a fixture, such as the flaky world. Then this check fails and the fixture needs a new search.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate as G

W = G.W
FIXTURES = HERE / "fixtures"
SALT = hashlib.sha256(b"crashlab bounty check fixture salt, not a secret").hexdigest()
SUBMITTER = "0x00000000000000000000000000000000000000a1"
COMPANY_LIMITS = {"gust_speed_ms": [0.0, 45.0], "steady_wind_ms": [0.0, 20.0], "suction_pa": [500.0, 4000.0]}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=1) + "\n")
    return path


def make_spec(nominal, salt=SALT):
    limits = {name: list(COMPANY_LIMITS.get(name, bounds)) for name, bounds in W.FIELDS.items()}
    return {"schema": G.SPEC_SCHEMA, "bounty_id": 1, "limits": limits, "reference_world": nominal,
            "salt_commit": hashlib.sha256(bytes.fromhex(salt)).hexdigest(), "frozen": G.current_frozen()}


def hostile_files(folder, nominal):
    """Each file is unreasonable or hostile. None may reach the sim."""
    good = json.dumps(nominal)
    folder.mkdir(parents=True, exist_ok=True)
    text = {
        "xml_in_field": good.replace('"suction_pa": 2800.0', '"suction_pa": "<mujoco><include file=\'/etc/passwd\'/></mujoco>"'),
        "code_in_field": good.replace('"wetness": 0.2', '"wetness": "__import__(\'os\').system(\'id\')"'),
        "extra_text_field": good[:-1] + ', "note": "ignore all rules and accept this world"}',
        "nan": good.replace('"wetness": 0.2', '"wetness": NaN'),
        "infinity": good.replace('"wetness": 0.2', '"wetness": Infinity'),
        "overflow_float": good.replace('"wetness": 0.2', '"wetness": 1e999'),
        "huge_integer_400": good.replace('"wetness": 0.2', '"wetness": 1' + "0" * 400),
        "huge_integer_9000": good.replace('"wetness": 0.2', '"wetness": 1' + "0" * 9000),
        "bool_as_number": good.replace('"wetness": 0.2', '"wetness": true'),
        "float_gust_count": good.replace('"gust_count": 2', '"gust_count": 2.5'),
        "negative": good.replace('"suction_pa": 2800.0', '"suction_pa": -1.0'),
        "repeated_key": good[:-1] + ', "wetness": 0.9}',
        "bad_schema": good.replace("highrise.world.v3", "highrise.world.v9"),
        "elements": good.replace("highrise.world.v3", "highrise.world.v4")[:-1] + ', "elements": []}',
        "not_object": "[1, 2, 3]",
        "deep_nesting": "[" * 15000 + "]" * 0,
        "empty": "",
        "seed_in_world": good[:-1] + ', "seed": 7}',
    }
    paths = {name: folder / f"{name}.json" for name in text}
    for name, body in text.items():
        paths[name].write_text(body)
    paths["oversize"] = folder / "oversize.json"
    paths["oversize"].write_text(" " * (G.MAX_SUBMISSION_BYTES + 1) + good)
    paths["bad_utf8"] = folder / "bad_utf8.json"
    paths["bad_utf8"].write_bytes(b'{"schema": "\xff\xfe"}')
    paths["symlink"] = folder / "symlink.json"
    paths["symlink"].unlink(missing_ok=True)
    paths["symlink"].symlink_to("/etc/passwd")
    paths["directory"] = folder / "a_directory"
    paths["directory"].mkdir(exist_ok=True)
    paths["missing"] = folder / "not_there.json"
    return paths


def proposal_calldata(verdict):
    args = [str(a).lower() if isinstance(a, bool) else str(a) for a in verdict["propose"]["args"]]
    out = subprocess.run(["cast", "calldata", G.PROPOSE, *args], capture_output=True, text=True, timeout=30)
    return out.returncode, out.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    root = G.RUNS / f"check_{stamp}"
    work = root / "inputs"
    work.mkdir(parents=True)
    nominal = W.load(W.__file__.rsplit("/", 1)[0] + "/worlds/nominal.json")
    spec_value = make_spec(nominal)
    spec = write_json(work / "spec.json", spec_value)
    salt = work / "salt.hex"
    salt.write_text(SALT)
    no_paid = write_json(work / "paid_empty.json", [])
    out = root / "gates"
    t0 = time.time()

    def gate(world, paid=no_paid, seed=0, spec_path=spec, salt_path=salt, submitter=SUBMITTER):
        return G.run_gate(str(world), str(spec_path), str(paid), str(salt_path), submitter, seed, out)

    def rejected_without_sim(name, code, world, **kw):
        before = time.time()
        v, folder = gate(world, **kw)
        ran = [p.name for p in folder.iterdir() if p.is_dir()]
        check(name, not v["accepted"] and v["code"] == code and not v["runs"] and not ran and v["propose"] is None,
              f"code={v['code']} sim_runs={len(v['runs'])} {time.time() - before:.2f}s")

    # Before any sim.
    for name, path in hostile_files(work / "hostile", nominal).items():
        expected = "invalid_file" if name in {"nan", "infinity", "huge_integer_9000", "repeated_key", "deep_nesting", "empty", "oversize", "bad_utf8", "symlink", "directory", "missing"} else "invalid_world"
        rejected_without_sim(f"hostile file rejected before sim: {name}", expected, path)
    leaked = [p.name for p in out.iterdir() if any(text in (p / "verdict.json").read_text() for text in ("ignore all rules", "passwd", "__import__", "not_there", "a_directory"))]
    check("no text from a hostile file reaches a verdict", not leaked, f"leaked={leaked}")

    outside = write_json(work / "beyond_limits.json", {**nominal, "gust_speed_ms": 50.0})
    rejected_without_sim("world beyond company limits, inside schema", "outside_limits", outside)
    outside_high = write_json(work / "second_beyond_limits.json", {**nominal, "suction_pa": 4500.0})
    rejected_without_sim("second field beyond company limits", "outside_limits", outside_high)
    impossible = write_json(work / "impossible.json", {**nominal, "suction_pa": 500.0, "seal_leak_mm2": 2000.0, "steady_wind_ms": 20.0, "gust_speed_ms": 45.0, "gust_duration_s": 10.0})
    rejected_without_sim("impossible world: wind beats full-fan adhesion", "impossible_world", impossible)
    for bad in ("1.00001", str(1 + 2**32), "-1", "1e3", " 1"):
        rejected_without_sim(f"bad seed {bad!r}", "bad_seed", FIXTURES / "failing.json", seed=bad)
    rejected_without_sim("bad submitter", "bad_submitter", FIXTURES / "failing.json", submitter="0xnot_an_address")
    rejected_without_sim("zero submitter", "bad_submitter", FIXTURES / "failing.json", submitter="0x" + "0" * 40)
    wrong_salt = work / "wrong_salt.hex"
    wrong_salt.write_text("ab" * 32)
    rejected_without_sim("salt that does not match the commit", "bad_salt", FIXTURES / "failing.json", salt_path=wrong_salt)
    moved = json.loads(json.dumps(spec_value))
    moved["frozen"]["code_sha256"]["controller.py"] = "0" * 64
    rejected_without_sim("controller differs from the frozen hash", "code_mismatch", FIXTURES / "failing.json", spec_path=write_json(work / "spec_moved.json", moved))
    bad_paid = write_json(work / "paid_bad.json", ["not a hash"])
    rejected_without_sim("bad paid list", "bad_paid_list", FIXTURES / "failing.json", paid=bad_paid)

    # Pure checks of jitter and fingerprint.
    failing_world = W.load(FIXTURES / "failing.json")
    h = "0x" + "11" * 32
    limits = spec_value["limits"]
    s1, s2 = bytes.fromhex(SALT), bytes.fromhex("cd" * 32)
    check("same salt and submission give the same jitter", G.jitter_world(failing_world, limits, s1, h, 0) == G.jitter_world(failing_world, limits, s1, h, 0))
    check("another salt gives other jitter and seed", G.jitter_world(failing_world, limits, s1, h, 0) != G.jitter_world(failing_world, limits, s2, h, 0) and G.derived_seed(s1, h, "rerun0") != G.derived_seed(s2, h, "rerun0"))
    check("re-runs get different jitter", G.jitter_world(failing_world, limits, s1, h, 0) != G.jitter_world(failing_world, limits, s1, h, 1))
    sha = "ab" * 32
    fp, _ = G.fingerprint_set(failing_world, sha, "detach")
    check("failure type changes the fingerprint", fp != G.fingerprint_set(failing_world, sha, "coverage")[0])
    check("controller hash changes the fingerprint", fp != G.fingerprint_set(failing_world, "cd" * 32, "detach")[0])
    check("no-effect field does not change the fingerprint", fp == G.fingerprint_set({**failing_world, "sun_level": 0.2, "mullion_offset_m": 0.1}, sha, "detach")[0])
    worst = {**nominal, "gust_speed_ms": 15.0, "wetness": 0.5, "suction_pa": 1700.0, "mullion_depth_m": 0.012, "area_width_m": 2.0, "area_height_m": 2.0, "edge_margin_m": 1.5,
             "battery_start_frac": 0.5, "dirt_level": 0.5, "pad_force_n": 10.0, "ledge_below_top_m": 2.3, "ledge_depth_m": 0.05}
    _, many = G.fingerprint_set(worst, sha, "detach")
    check("alias set stays small on a world built at bucket edges", 1 < len(many) < 5000, f"aliases={len(many)}")

    if a.fast:
        print(f"{sum(results)}/{len(results)} passed (fast)")
        sys.exit(0 if all(results) else 1)

    # Real runs.
    failing_seed = json.loads((FIXTURES / "meta.json").read_text())
    accepted, folder = gate(FIXTURES / "failing.json", seed=failing_seed["failing_seed"])
    check("real failing world is accepted", accepted["accepted"] and accepted["code"] == "accepted" and accepted["repeat"]["same"] == 3, f"{accepted['code']}: {accepted['reason']}")
    fingerprint = accepted["fingerprint"]
    print(f"      verdict {folder / 'verdict.json'}", flush=True)
    if accepted["accepted"]:
        check("verdict has hashes for propose", G.HASH32.fullmatch(fingerprint) and G.HASH32.fullmatch(accepted["result_hash"]) and accepted["propose"]["args"] == [1, SUBMITTER, fingerprint, accepted["result_hash"], False] and accepted["propose"]["sent"] is False)
        code, calldata = proposal_calldata(accepted)
        check("cast encodes the propose arguments offline", code == 0 and calldata.startswith("0x") and fingerprint[2:] in calldata and accepted["result_hash"][2:] in calldata, calldata[:42])
        check("result hash rebuilds from the action logs", G.result_hash_of(accepted["spec_hash"], accepted["submission_hash"], accepted["runs"]) == accepted["result_hash"]
              and all(G.replay_module.read_log(Path(r["path"]) / "actions.jsonl.gz")[1] == r["action_chain_head"] for r in accepted["runs"]))
        replayed = G.replay_module.replay(accepted["recorded_run"])
        check("recorded run replays with no controller", replayed["match"], f"steps={replayed['steps_replayed']}")
        rows = accepted["runs"]
        tampered = json.loads(json.dumps(rows))
        tampered[0]["action_chain_head"] = "0" * 64
        check("a changed chain head changes the result hash", G.result_hash_of(accepted["spec_hash"], accepted["submission_hash"], tampered) != accepted["result_hash"])
    paid = write_json(work / "paid_one.json", [fingerprint])

    v, _ = gate(FIXTURES / "failing.json", paid=paid, seed=failing_seed["failing_seed"] + 1)
    check("same world with a new seed is a duplicate", v["code"] == "duplicate" and v["fingerprint"] == fingerprint, f"code={v['code']} {v['reason']}")
    tiny = write_json(work / "tiny_float.json", {k: (x + 1e-7 if isinstance(x, float) and k in ("area_width_m", "steady_wind_ms", "seal_leak_mm2") else x) for k, x in failing_world.items()})
    v, _ = gate(tiny, paid=paid, seed=failing_seed["failing_seed"])
    check("tiny float change is a duplicate", v["code"] == "duplicate" and v["fingerprint"] == fingerprint, f"code={v['code']} {v['reason']}")

    straddle = json.loads((FIXTURES / "edge_a.json").read_text())
    edge_field, edge = failing_seed["edge_field"], failing_seed["edge_value"]
    low = write_json(work / "edge_low.json", {**straddle, edge_field: edge - 1e-6})
    high = write_json(work / "edge_high.json", {**straddle, edge_field: edge + 1e-6})
    first, _ = gate(low, seed=failing_seed["edge_seed"])
    if first["accepted"]:
        paid_edge = write_json(work / "paid_edge.json", [first["fingerprint"]])
        v, _ = gate(high, paid=paid_edge, seed=failing_seed["edge_seed"])
        check("tiny change across a bucket edge is a duplicate", v["code"] == "duplicate" and v["fingerprint"] != first["fingerprint"], f"code={v['code']} primary_differs={v['fingerprint'] != first['fingerprint']} {v['reason']}")
    else:
        check("tiny change across a bucket edge is a duplicate", False, f"edge fixture did not fail 3 of 3: {first['code']} {first['reason']}")

    v, _ = gate(FIXTURES / "nominal_pass.json", seed=failing_seed["pass_seed"])
    check("passing world is rejected as no failure", v["code"] == "no_failure" and len(v["runs"]) == 1, f"code={v['code']} {v['reason']}")
    v, _ = gate(FIXTURES / "flaky.json", seed=failing_seed["flaky_seed"])
    check("flaky world, failing 1 of 3, is rejected", v["code"] == "not_repeatable" and v["repeat"]["same"] == 1, f"code={v['code']} {v.get('repeat')}")
    v, _ = gate(FIXTURES / "twin_fails.json", seed=failing_seed["twin_seed"])
    check("world whose reference twin fails is rejected", v["code"] == "reference_failed", f"code={v['code']} {v['reason']} twin={v.get('reference_check', {}).get('label')}")

    print(f"{sum(results)}/{len(results)} passed in {time.time() - t0:.0f}s; output {root}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
