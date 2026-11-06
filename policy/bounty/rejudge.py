"""The judge outside the sandbox: <pack python> -I rejudge.py, a JSON request on stdin, a JSON reply on stdout. Started by fix.py after the sandbox process has ended. Results are simulated.

It imports the frozen sim and judge, and never the submitted file. The world and seed come from the request, which fix.py read before the sandbox ran. Files in the run folder are hostile data.
Window: replays the recorded actions on that world and seed. Every state hash, the chain and the point where the judge stops must match.
Inspection: runs the frozen sim and the frozen RouteFollower again, with the submitted constants as plain numbers, then compares every recorded array with that run.
The verdict always comes from the run made here. A record that differs makes "matches" false.
"""
import gzip
import io
import json
import math
import os
import stat
import sys
from pathlib import Path

POLICY = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(POLICY), str(POLICY / "server")]

MAX_RECORD_BYTES = 200 * 2**20  # The sandbox's file limit. Actions and arrays hold nothing larger.
MAX_UNPACKED_BYTES = 2 * 2**30
RECORD_NAMES = {"t", "body_q", "body_qd", "joint_q", "base_q", "command", "foot_v_xy", "feet", "sim_failed", "object_f", "ground_f", "body_on_ground_f", "meta"}
ROUTE_CONSTANTS = {"SPEED_MPS", "TURN_RADPS", "HEADING_GAIN", "TURN_IN_PLACE_DEG", "LOOKAHEAD_M", "ARRIVE_M"}


def read_plain(path):
    """The bytes of a regular file, never through a link. None if it is not one, or is too large."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
            return None
        return f.read()


def read_log(data, genesis, digest):
    """Returns (rows, chain head), or None if the log is not a whole hash chain."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
            text = f.read(MAX_UNPACKED_BYTES + 1)
        if len(text) > MAX_UNPACKED_BYTES:
            return None
        rows = [json.loads(line) for line in text.splitlines()]
        prev = genesis
        for n, row in enumerate(rows):
            if row["i"] != n - 1 or digest(prev, row["i"], row["a"], row["s"]) != row["h"]:
                return None
            prev = row["h"]
    except (OSError, EOFError, ValueError, KeyError, TypeError):
        return None
    return (rows, prev) if rows else None


def window(req):
    import pack_job
    from packs.window import pack as P

    R, S, W = P.R, P.R.S, P.W
    folder = Path(req["run"])
    world, seed = W.validate(req["world"]), req["seed"]
    data = read_plain(folder / "actions.jsonl.gz")
    log = read_log(data, R.GENESIS, S.digest) if data else None
    if log is None:
        return {"no_record": True}
    rows, head = log
    sim = S.Sim(world, seed)
    if rows[0]["a"] != [] or rows[0]["s"] != sim.start_sha:
        return {"no_record": False, "matches": False, "why": "the log starts from another state"}
    judge = P.J.Judge()
    action = [0.0] * len(S.ACTION_FIELDS)
    status, stopped = "invalid_action", False
    for row in rows[1:]:
        action = row["a"]
        if stopped or not sim.step(action):
            return {"no_record": False, "matches": False, "why": f"the log holds an action the sim refuses or a step past the end, at step {row['i']}"}
        judge.update(sim, action)
        if sim.state_sha() != row["s"]:
            return {"no_record": False, "matches": False, "why": f"the replay differs from the record at step {row['i']}"}
        if sim.diverged:
            status, stopped = "sim_diverged", True
        elif judge.should_stop(sim, action):
            status, stopped = "ok", True
    result = judge.finish(sim, action)
    if status != "ok":  # A log that ends early counts as the run's own invalid action, which fails. A cut log cannot pass.
        result.update(passed=False, failure=status, outcome="sim_diverged" if status == "sim_diverged" else "fail", diverged_reason=sim.diverged_reason)
    result.update(status=status, label=R.sim_label(R.code_hashes()))
    judged = pack_job.split_judged(P.judge({"result": result}, world))
    events = sorted(({"name": k, "t": v["t"], "value": v["value"]} for k, v in result["fired"].items()), key=lambda e: e["t"])
    reply = {**judged, "events": events, "code": None, "label": result["label"], "note": P.SIMULATED_NOTE, "safe_hold": judged["verdict"] in P.HOLDS, "seed": seed, "final_state_sha256": sim.state_sha(), "action_chain_head": head, "no_record": False}
    stored_data = read_plain(folder / "result.json")
    try:
        stored = json.loads(stored_data)
        same = all(stored[k] == result[k] for k in ("failure", "passed", "coverage", "slip_m", "peak_tether_n", "time_s", "status")) and stored["action_chain_head"] == head and stored["seed"] == seed and stored["world_sha256"] == W.world_hash(world)
    except (TypeError, ValueError, KeyError):
        same = False
    return {**reply, "matches": same, "why": None if same else "the stored result differs from the replay"}


def record_problem(saved, world, seed, physics_hash, policy_dt):
    """The cheap checks, so a broken record costs no sim run: names, frame count, clock, finite numbers, seed and world."""
    import numpy as np

    if set(saved) != RECORD_NAMES:
        return "the record holds other arrays than the sim writes"
    t = saved["t"]
    frames = len(t) if t.ndim == 1 else -1
    if frames < 0 or frames > round(world["route"]["time_limit_s"] / policy_dt):
        return "the frame count is outside the route's time limit"
    if not np.array_equal(t, np.asarray([(k + 1) * policy_dt for k in range(frames)], dtype=np.float32)):
        return "the record's clock is not the sim's clock"
    for name in RECORD_NAMES - {"meta", "feet", "sim_failed"}:
        if saved[name].dtype.kind != "f" or len(saved[name]) != frames or not np.isfinite(saved[name]).all():
            return f"{name} is not one finite row per frame"
    try:
        saved_meta = json.loads(str(saved["meta"]))
    except ValueError:
        return "the record's notes do not parse"
    if saved_meta.get("seed") != seed or saved_meta.get("physics_hash") != physics_hash:
        return "the record names another seed or world"
    return None


def load_record(path):
    import numpy as np
    import zipfile

    data = read_plain(path)
    if data is None:
        return None
    try:
        box = io.BytesIO(data)
        with zipfile.ZipFile(box) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED_BYTES:
                return None
        with np.load(box, allow_pickle=False) as saved:
            return {k: saved[k] for k in saved.files}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError):
        return None


def inspection(req):
    import warp as wp

    from packs.inspection import controller as C
    from packs.inspection import model as M
    from packs.inspection import job as JOB
    from packs.inspection import pack as P
    from packs.inspection import sim as S
    from packs.inspection import world as W

    wp.config.verbose = False
    constants = req["constants"]
    if set(constants) != ROUTE_CONSTANTS or not all(type(v) in (int, float) and math.isfinite(v) for v in constants.values()):
        raise SystemExit("the constants are not the six plain numbers")
    saved = load_record(Path(req["run"]) / "record.npz")
    if saved is None:
        return {"no_record": True}
    world = P.validate(req["world"])
    problem = record_problem(saved, world, req["seed"], W.physics_hash(world), S.POLICY_DT)
    if problem:
        return {"no_record": False, "matches": False, "why": problem}
    M.asset_dir = lambda: req["asset"]
    for name, value in constants.items():
        setattr(C, name, value)
    rec, meta = P.run(world, seed=req["seed"])
    reply = {**JOB._finish(P, rec, meta)[0], "seed": req["seed"], "no_record": False}
    differ = [k for k in rec if k != "meta" and (rec[k].dtype != saved[k].dtype or rec[k].shape != saved[k].shape or rec[k].tobytes() != saved[k].tobytes())]
    if differ:
        return {**reply, "matches": False, "why": "these arrays differ from the run made here: " + ", ".join(sorted(differ))}
    return {**reply, "matches": True, "why": None}


def main():
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    req = json.load(sys.stdin)
    reply = {"window": window, "inspection": inspection}[req["pack"]](req)
    os.write(real_stdout, json.dumps(reply, allow_nan=False).encode())


if __name__ == "__main__":
    main()
