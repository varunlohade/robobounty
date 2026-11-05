"""CrashLab bounty gate: decides if one submitted world file counts as a new, valid failure. See README.md.

gate.py --world W --spec S --paid P --salt-file F --submitter 0x.. [--seed N] [--out DIR]
Writes verdict.json into a new run folder. Exit 0 means accepted, 1 means rejected. It sends nothing on chain.
"""
import argparse
import hashlib
import hmac
import itertools
import json
import math
import multiprocessing as mp
import os
import re
import stat
import sys
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
sys.path.insert(0, str(POLICY / "highrise"))
import replay as replay_module
import run_trial
import sim as S
import world as W

SPEC_SCHEMA = "crashlab.bounty.spec.v1"
VERDICT_SCHEMA = "crashlab.bounty.verdict.v1"
FINGERPRINT_DOMAIN = "crashlab.bounty.fingerprint.v1"
JITTER_DOMAIN = "crashlab.bounty.jitter.v1"
RUNS = POLICY / "runs" / "bounty"
MAX_SUBMISSION_BYTES = 16 * 1024  # a plain world is about 1 KB
MAX_SPEC_BYTES = 64 * 1024
MAX_PAID_BYTES = 1 << 20
MAX_PROCS = 2
NICE = 10
RUN_TIMEOUT_S = 300
RERUNS = 3
JITTER_SHARE = 0.01  # each re-run moves a field by up to this share of its schema range
REFERENCE_KEEP = 0.25  # the reference twin keeps this share of the world's distance from nominal
MIN_GUST_FOR_LOAD_S = 2.0  # a shorter gust may pass before the robot lifts, so the hardware check skips it
HASH32 = re.compile(r"0x[0-9a-f]{64}")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
PROPOSE = "propose(uint256,address,bytes32,bytes32,bool)"
HOLDS = {"wind_hold", "battery_stop"}
NOT_CHECKED = [
    "World ID of the submitter (risk 12): the backend must check it before the resolver proposes.",
    "Collusion between submitter and company or solver (risk 11).",
    "Money left in the bounty and its deadline: the contract checks both.",
    "Top prize: isTopPrize stays false. The company decides a top prize.",
]


class Rejected(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code, self.reason = code, reason


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key")
        out[k] = v
    return out


def read_json(path, limit, what):
    """Only a small regular file gets read. No error text from the file reaches the verdict."""
    code = "invalid_file"
    try:
        info = os.lstat(path)
    except OSError:
        raise Rejected(code, f"The {what} file cannot be read.") from None
    if not stat.S_ISREG(info.st_mode):
        raise Rejected(code, f"The {what} file is not a regular file.")
    if info.st_size > limit:
        raise Rejected(code, f"The {what} file is larger than {limit} bytes.")
    try:
        data = Path(path).read_bytes()[:limit + 1]
        if len(data) > limit:
            raise Rejected(code, f"The {what} file is larger than {limit} bytes.")
        return json.loads(data.decode("utf-8"), parse_constant=W._reject_constant, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, RecursionError, OverflowError):  # bad UTF-8, bad JSON, NaN, repeated key, huge integer, deep nesting
        raise Rejected(code, f"The {what} file is not strict JSON.") from None


def check_world(raw):
    """Strict world.py validation. Field names from the file never enter a reason."""
    if not isinstance(raw, dict):
        raise Rejected("invalid_world", "A world must be one JSON object.")
    if "elements" in raw:
        raise Rejected("invalid_world", "Scene elements are not open to bounties, because company limits have no rows for them.")
    expected = set(W.FIELDS) | {"schema"}
    if set(raw) != expected:
        raise Rejected("invalid_world", f"The world has {len(expected - set(raw))} missing and {len(set(raw) - expected)} unknown fields.")
    try:
        return W.validate(raw)
    except W.WorldError as e:
        raise Rejected("invalid_world", f"The world fails validation: {e}.") from None
    except (OverflowError, TypeError):  # math.isfinite raises on a huge integer
        raise Rejected("invalid_world", "The world holds a number too large to use.") from None


def check_spec(spec):
    if not isinstance(spec, dict) or set(spec) != {"schema", "bounty_id", "limits", "reference_world", "salt_commit", "frozen"}:
        raise Rejected("bad_spec", "The spec does not have the exact fields.")
    bounty_id = spec["bounty_id"]
    if spec["schema"] != SPEC_SCHEMA or isinstance(bounty_id, bool) or not isinstance(bounty_id, int) or not 0 < bounty_id < 2**256:
        raise Rejected("bad_spec", "The spec schema or bounty id is wrong.")
    limits = spec["limits"]
    if not isinstance(limits, dict) or set(limits) != set(W.FIELDS):
        raise Rejected("bad_spec", "The spec must set limits for every world field.")
    for name, (lo, hi) in W.FIELDS.items():
        row = limits[name]
        if not (isinstance(row, list) and len(row) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in row)):
            raise Rejected("bad_spec", f"The limits for {name} must be two numbers.")
        if not lo <= row[0] <= row[1] <= hi:
            raise Rejected("bad_spec", f"The limits for {name} are not inside the schema range.")
    try:
        reference = check_world(spec["reference_world"])
        check_limits(reference, limits)
    except Rejected:
        raise Rejected("bad_spec", "The reference world is not valid, or it is outside the company limits.") from None
    frozen = spec["frozen"]
    if not isinstance(frozen, dict) or set(frozen) != {"code_sha256", "versions"} or not isinstance(frozen["code_sha256"], dict) or not isinstance(frozen["versions"], dict):
        raise Rejected("bad_spec", "The spec must pin the code and versions.")
    return reference


def check_limits(world, limits):
    for name in W.FIELDS:
        lo, hi = limits[name]
        if not lo <= world[name] <= hi:
            raise Rejected("outside_limits", f"{name}={world[name]} is outside the company limits [{lo}, {hi}].")


def check_salt(path, spec):
    try:
        salt = bytes.fromhex(Path(path).read_text().strip())
    except (OSError, ValueError):
        raise Rejected("bad_salt", "The salt file cannot be read as hex.") from None
    if len(salt) < 32 or sha256_hex(salt) != spec["salt_commit"]:
        raise Rejected("bad_salt", "The salt is too short, or it does not match the commit in the spec.")
    return salt


def current_frozen():
    return {"code_sha256": {**run_trial.code_hashes(), "gate.py": sha256_hex(Path(__file__).read_bytes())}, "versions": S.versions()}


def check_frozen(spec):
    if current_frozen() != spec["frozen"]:
        raise Rejected("code_mismatch", "The controller, sim, judge, gate or MuJoCo version differs from the frozen values in the spec.")


def hardware_hold(world):
    """Full-fan adhesion on clean flat glass against the outward wind load at the peak wind, without turbulence."""
    rho, _ = W.air(world)
    leak = world["seal_leak_mm2"] * 1e-6 + S.DUST_LEAK_M2_PER_GM2 * world["dust_gm2"]
    dp, _ = S.impeller_pressure(world["suction_pa"] * rho / S.REFERENCE_AIR_DENSITY, S.IMPELLER_FLOW_MAX_M3S, leak, rho)
    counted_gust = world["gust_speed_ms"] if world["gust_count"] > 0 and world["gust_duration_s"] >= MIN_GUST_FOR_LOAD_S else 0.0
    peak = max(world["steady_wind_ms"], counted_gust)
    return {"adhesion_n": round(dp * S.SEALED_AREA_M2, 2), "outward_load_n": round(0.5 * rho * S.OUTWARD_LOAD_COEF * S.AREA_BODY_FRONT * peak * peak, 2)}


def reference_twin(world, nominal):
    twin = dict(world)
    for name in W.FIELDS:
        value = nominal[name] + REFERENCE_KEEP * (world[name] - nominal[name])
        twin[name] = round(value) if name in W.INTEGER_FIELDS else value
    return W.validate(twin)


# Fingerprint factors: a few physical values, not 29 raw fields. Each row is (name, input fields, value, bucket edges).
def _peak_wind(w):
    return max(w["steady_wind_ms"], w["gust_speed_ms"] if w["gust_count"] > 0 else 0.0)


def _full_fan_pressure(w):
    rho, _ = W.air(w)
    leak = w["seal_leak_mm2"] * 1e-6 + S.DUST_LEAK_M2_PER_GM2 * w["dust_gm2"]
    return S.impeller_pressure(w["suction_pa"] * rho / S.REFERENCE_AIR_DENSITY, S.IMPELLER_FLOW_MAX_M3S, leak, rho)[0]


def _joint_leak_mm2(w):
    cold = w["temperature_c"] - S.SKIRT_STIFFEN_BELOW_C
    lip = S.LIP_CONFORM_M * min(1.0, max(S.SKIRT_STIFFEN_FLOOR, 1 + S.SKIRT_STIFFEN_PER_C * cold))
    step = max(0.0, w["mullion_depth_m"] - lip)
    return 1e6 * (S.CROSS_LEAK_SHAPE * step * step + w["joint_gap_m"] * S.JOINT_GROOVE_DEPTH_M)


def _usable_battery(w):
    kelvin = w["temperature_c"] + 273.15
    return w["battery_start_frac"] * min(1.0, max(S.BATTERY_CAPACITY_FLOOR, 1 + S.BATTERY_CAPACITY_PER_K * (kelvin - 298.15)))


def _ledge_in_path(w):
    """Ledge depth when it crosses the assigned area, else 0. A ledge the robot never meets does not make a new failure."""
    left = w["ledge_x_m"] + w["area_width_m"] / 2 - w["ledge_width_m"] / 2
    crosses = w["ledge_below_top_m"] < w["area_height_m"] + W.BODY_SIDE and left < w["area_width_m"] + W.BODY_SIDE and left + w["ledge_width_m"] > -W.BODY_SIDE
    return w["ledge_depth_m"] if crosses else 0.0


FACTORS = (
    ("peak_wind_ms", ("steady_wind_ms", "gust_speed_ms"), _peak_wind, (7.0, 10.0, 15.0, 22.0, 35.0)),
    ("wind_into_wall_ms", ("steady_wind_ms", "gust_speed_ms", "wind_dir_deg"), lambda w: _peak_wind(w) * max(0.0, math.sin(math.radians(w["wind_dir_deg"]))), (5.0, 15.0)),
    ("grip_mu", ("wetness", "temperature_c", "humidity_pct", "dust_gm2"), W.friction, (0.35, 0.45, 0.60)),
    ("full_fan_pa", ("suction_pa", "seal_leak_mm2", "dust_gm2", "temperature_c", "humidity_pct"), _full_fan_pressure, (800.0, 1500.0, 2200.0)),
    ("joint_leak_mm2", ("mullion_depth_m", "joint_gap_m", "temperature_c"), _joint_leak_mm2, (30.0, 100.0, 300.0, 800.0)),
    ("area_m2", ("area_width_m", "area_height_m"), lambda w: w["area_width_m"] * w["area_height_m"], (4.0, 8.0, 15.0)),
    ("edge_margin_m", ("edge_margin_m",), lambda w: w["edge_margin_m"], (0.6, 1.5)),
    ("usable_battery", ("battery_start_frac", "temperature_c"), _usable_battery, (0.25, 0.5, 0.75)),
    ("dirt_per_pad_n", ("dirt_level", "pad_force_n"), lambda w: w["dirt_level"] / w["pad_force_n"], (0.02, 0.05, 0.10)),
    ("ledge_in_path_m", ("ledge_x_m", "ledge_width_m", "ledge_below_top_m", "ledge_depth_m", "area_width_m", "area_height_m"), _ledge_in_path, (0.001, 0.05, 0.12)),
)


def buckets(world):
    return {name: bisect_right(edges, fn(world)) for name, _, fn, edges in FACTORS}


def nearby_buckets(world):
    """For each factor, every bucket the world reaches when its inputs move by the re-run jitter."""
    out = {}
    for name, inputs, fn, edges in FACTORS:
        seen = set()
        for signs in itertools.product((-1, 0, 1), repeat=len(inputs)):
            moved = dict(world)
            for field, sign in zip(inputs, signs):
                lo, hi = W.FIELDS[field]
                moved[field] = min(hi, max(lo, world[field] + sign * JITTER_SHARE * (hi - lo)))
            seen.add(bisect_right(edges, fn(moved)))
        out[name] = sorted(seen)
    return out


def fingerprint_of(controller_sha, failure, bucket_map):
    return "0x" + sha256_hex(canonical([FINGERPRINT_DOMAIN, controller_sha, failure, bucket_map]))


def fingerprint_set(world, controller_sha, failure):
    """The fingerprint, plus every fingerprint within jitter reach. A paid one in this set makes the world a duplicate."""
    names = [row[0] for row in FACTORS]
    near = nearby_buckets(world)
    aliases = {fingerprint_of(controller_sha, failure, dict(zip(names, combo))) for combo in itertools.product(*(near[n] for n in names))}
    return fingerprint_of(controller_sha, failure, buckets(world)), aliases


def derive(salt, submission_hash, label):
    return hmac.new(salt, f"{JITTER_DOMAIN}|{submission_hash}|{label}".encode(), hashlib.sha256).digest()


def derived_seed(salt, submission_hash, label):
    return int.from_bytes(derive(salt, submission_hash, f"{label}|seed")[:8], "big") % 2**31


def jitter_world(world, limits, salt, submission_hash, k):
    """No numpy here: anyone with the revealed salt can rebuild these values in any language."""
    out = dict(world)
    for name, (lo, hi) in W.FIELDS.items():
        if name in W.INTEGER_FIELDS:
            continue
        u = int.from_bytes(derive(salt, submission_hash, f"rerun{k}|{name}")[:8], "big") / 2**64
        moved = world[name] + (2 * u - 1) * JITTER_SHARE * (hi - lo)
        out[name] = min(limits[name][1], max(limits[name][0], moved))
    return W.validate(out)


def _low_priority():
    if os.getpriority(os.PRIO_PROCESS, 0) < NICE:
        os.setpriority(os.PRIO_PROCESS, 0, NICE)


def _run_job(job):
    world, seed, out = job
    return run_trial.run(world, seed, out)


def run_jobs(pool, jobs):
    pending = [pool.apply_async(_run_job, (job,)) for job in jobs]
    try:
        return [p.get(timeout=RUN_TIMEOUT_S) for p in pending]
    except mp.TimeoutError:
        pool.terminate()
        raise Rejected("sim_timeout", f"A run took longer than {RUN_TIMEOUT_S} s.") from None


def label_of(result):
    return result["failure"] or result["outcome"]


def record_run(rows, name, seed, world, out, result, spec):
    if result["code_sha256"] != {k: v for k, v in spec["frozen"]["code_sha256"].items() if k != "gate.py"} or result["versions"] != spec["frozen"]["versions"]:
        raise Rejected("code_mismatch", "The code changed while the gate was running.")
    _, head = replay_module.read_log(Path(out) / "actions.jsonl.gz")
    if head != result["action_chain_head"]:
        raise Rejected("sim_fault", "An action log does not match its stored chain head.")
    rows.append({"name": name, "path": str(out), "seed": seed, "world_sha256": W.world_hash(world), "model_sha256": result["model_sha256"],
                 "action_chain_head": head, "steps": result["steps"], "label": label_of(result), "passed": result["passed"], "fired": list(result["fired"]), "wall_s": result["wall_s"]})


def result_hash_of(spec_hash, submission_hash, runs):
    """A hash chain over the head of each action log, in run order."""
    h = sha256_hex(canonical(["crashlab.bounty.result.v1", spec_hash, submission_hash]))
    for row in runs:
        h = sha256_hex(canonical([h, row["name"], row["seed"], row["world_sha256"], row["action_chain_head"], row["label"]]))
    return "0x" + h


def new_folder(root, stem):
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    while True:
        folder = root / (f"{stem}_{n}" if n else stem)
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            n += 1


def run_gate(world_path, spec_path, paid_path, salt_path, submitter, seed, out_root=RUNS):
    """Always writes one verdict. Returns (verdict, folder). Every check before stage "sim" costs no sim time."""
    verdict = {"schema": VERDICT_SCHEMA, "accepted": False, "code": None, "reason": None, "stage": "file", "fingerprint": None, "result_hash": None,
               "propose": None, "submission_hash": None, "spec_hash": None, "submitter": None, "claim_seed": None, "runs": [], "limits_of_this_result": "Simulation only. The physics is hand-built and not calibrated to a real robot."}
    folder = None
    state = {}
    try:
        state["spec"] = read_json(spec_path, MAX_SPEC_BYTES, "spec")
        reference = check_spec(state["spec"])
        spec = state["spec"]
        verdict["spec_hash"] = "0x" + sha256_hex(canonical(spec))
        paid = read_json(paid_path, MAX_PAID_BYTES, "paid list")
        if not isinstance(paid, list) or not all(isinstance(p, str) and HASH32.fullmatch(p) for p in paid):
            raise Rejected("bad_paid_list", "The paid list must be a list of 0x-prefixed lowercase 32-byte hashes.")
        salt = check_salt(salt_path, spec)
        if not isinstance(submitter, str) or not ADDRESS.fullmatch(submitter) or int(submitter, 16) == 0:
            raise Rejected("bad_submitter", "The submitter must be a nonzero 20-byte hex address.")
        verdict["submitter"] = submitter
        if isinstance(seed, str):  # threat model risk 9: 1.00001 and 1+2^32 must not reach the sim as new seeds
            seed = int(seed) if re.fullmatch(r"[0-9]{1,10}", seed) else None
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
            raise Rejected("bad_seed", "The seed must be a whole number from 0 to 2147483647.")
        verdict["claim_seed"] = seed

        verdict["stage"] = "world"
        world = check_world(read_json(world_path, MAX_SUBMISSION_BYTES, "world"))
        check_limits(world, spec["limits"])
        verdict["submission_hash"] = "0x" + sha256_hex(canonical([W.world_hash(world), seed, submitter.lower(), spec["bounty_id"]]))

        verdict["stage"] = "hardware"
        hold = hardware_hold(world)
        verdict["hardware_check"] = hold
        if hold["outward_load_n"] >= hold["adhesion_n"]:
            raise Rejected("impossible_world", f"The wind load of {hold['outward_load_n']} N beats the full-fan adhesion of {hold['adhesion_n']} N, so no controller can hold this robot on the glass.")

        verdict["stage"] = "frozen"
        check_frozen(spec)
        controller_sha = spec["frozen"]["code_sha256"]["controller.py"]
        verdict["controller_sha256"] = controller_sha

        verdict["stage"] = "sim"
        submission = verdict["submission_hash"]
        folder = new_folder(Path(out_root), submission[2:18])
        _low_priority()
        with mp.get_context("spawn").Pool(MAX_PROCS, initializer=_low_priority) as pool:
            rows = verdict["runs"]
            claim = run_jobs(pool, [(world, seed, str(folder / "claim"))])[0]
            record_run(rows, "claim", seed, world, folder / "claim", claim, spec)
            failure = label_of(claim)
            if claim["passed"]:
                raise Rejected("no_failure", "The robot passed this world, so there is no failure to pay for.")
            if failure in HOLDS:
                raise Rejected("no_failure", f"The robot stopped safely on the glass ({failure}). The judge does not count that as a failure.")
            if failure == "sim_diverged":
                raise Rejected("sim_fault", "The simulation broke down on this world. That is a sim fault, not a robot failure.")

            fingerprint, aliases = fingerprint_set(world, controller_sha, failure)
            verdict["fingerprint"] = fingerprint
            verdict["buckets"] = buckets(world)
            verdict["fingerprints_within_jitter"] = len(aliases)
            already = sorted(aliases & set(paid))
            if already:
                verdict["duplicate_of"] = already[0]
                raise Rejected("duplicate", f"This {failure} failure falls in a bucket that the bounty already paid for.")

            jobs = []
            for k in range(RERUNS):
                jobs.append((jitter_world(world, spec["limits"], salt, submission, k), derived_seed(salt, submission, f"rerun{k}"), str(folder / f"rerun{k}")))
            done = run_jobs(pool, jobs)
            for k, (job, result) in enumerate(zip(jobs, done)):
                record_run(rows, f"rerun{k}", job[1], job[0], job[2], result, spec)
            labels = [label_of(r) for r in done]
            same = labels.count(failure)
            verdict["repeat"] = {"failure": failure, "same": same, "of": RERUNS, "labels": labels}
            if same < RERUNS:
                raise Rejected("not_repeatable", f"The {failure} failure came back in {same} of {RERUNS} jittered re-runs. The gate needs {RERUNS} of {RERUNS}.")

            twin = reference_twin(world, reference)
            twin_seed = derived_seed(salt, submission, "reference")
            reference_result = run_jobs(pool, [(twin, twin_seed, str(folder / "reference"))])[0]
            record_run(rows, "reference", twin_seed, twin, folder / "reference", reference_result, spec)
            verdict["reference_check"] = {"keep_share": REFERENCE_KEEP, "label": label_of(reference_result), "passed": reference_result["passed"],
                                          "meaning": "The same world moved most of the way back to nominal. A pass shows the robot works near this world. It does not prove that this world is possible."}
            if not reference_result["passed"]:
                raise Rejected("reference_failed", f"The reference twin, {REFERENCE_KEEP:.0%} of the way from nominal to this world, did not pass ({label_of(reference_result)}). The gate cannot show that this world is fair.")

        verdict["result_hash"] = result_hash_of(verdict["spec_hash"], submission, rows)
        verdict["accepted"], verdict["code"] = True, "accepted"
        verdict["stage"] = "done"
        verdict["reason"] = f"New {failure} failure: it repeated {RERUNS} of {RERUNS} on jittered re-runs and the reference twin passed."
        verdict["recorded_run"] = str(folder / "claim")
        verdict["propose"] = {"function": PROPOSE, "args": [spec["bounty_id"], submitter, fingerprint, verdict["result_hash"], False],
                              "named": {"bountyId": spec["bounty_id"], "submitter": submitter, "fingerprint": fingerprint, "resultHash": verdict["result_hash"], "isTopPrize": False},
                              "sent": False}
    except Rejected as r:
        verdict["code"], verdict["reason"] = r.code, r.reason
    verdict["not_checked"] = NOT_CHECKED
    if folder is None:
        folder = new_folder(Path(out_root), f"rejected_{verdict['code']}")
    (folder / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    return verdict, folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--paid", required=True)
    ap.add_argument("--salt-file", required=True)
    ap.add_argument("--submitter", required=True)
    ap.add_argument("--seed", default="0")
    ap.add_argument("--out", default=str(RUNS))
    a = ap.parse_args()
    verdict, folder = run_gate(a.world, a.spec, a.paid, a.salt_file, a.submitter, a.seed, a.out)
    print(json.dumps({"accepted": verdict["accepted"], "code": verdict["code"], "reason": verdict["reason"], "verdict": str(folder / "verdict.json")}, indent=1))
    sys.exit(0 if verdict["accepted"] else 1)


if __name__ == "__main__":
    main()
