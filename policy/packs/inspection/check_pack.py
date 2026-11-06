"""Runs the inspection worlds, judges them from their records, writes results.json and browser replays. Exit code 0 means every check held.

Run from policy/: .venv-newton/bin/python -m packs.inspection.check_pack
Every number is simulated: one upstream policy, one upstream robot model, no calibration.
"""
import copy
import gzip
import json
import subprocess
import sys
import pathlib

import numpy as np

from .. import missing
from . import pack as P
from . import plant as PL
from . import sim as S
from . import world as W

OUT = S.HERE / "out"
SEED = 0
WORLDS = PL.WORLDS
REFUSALS = [
    ("add_box", {"name": "x", "x": 0.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "blocks_start"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": -1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": True, "sy": 1, "sz": 1}, "bad_args"),
    ("add_box", {"name": "x", "x": float("nan"), "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "x", "x": float("inf"), "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "x", "x": 10 ** 400, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "out_of_range"),
    ("add_box", {"name": "x", "x": "2", "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "bad_args"),
    ("add_box", {"name": "X; rm -rf /", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "bad_name"),
    ("add_box", {"name": "../../etc", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "bad_name"),
    ("add_box", {"name": "x", "x": 39.9, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "outside_world"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1, "mesh": "a.obj"}, "bad_args"),
    ("add_box", {"name": "x", "x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1, 7: 7}, "bad_args"),
    ("add_box", ["name", "x"], "bad_args"),
    ("add_box", {"x": 2.0, "y": 0.0, "sx": 1, "sy": 1, "sz": 1}, "bad_args"),
    ("add_ramp", {"name": "x", "x": 2.0, "y": 0.0, "length": 0.2, "width": 1, "height": 1.0}, "too_steep"),
    ("add_pipe", {"name": "x", "x": 0.0, "y": 0.0, "length": 3.0, "radius": 0.1}, "blocks_start"),
    ("add_pipe", {"name": "x", "x": 2.0, "y": 0.0, "length": 3.0, "radius": 5.0}, "out_of_range"),
    ("add_cable_tray", {"name": "x", "x": 2.0, "y": 0.0, "length": 99.0}, "out_of_range"),
    ("add_valve", {"name": "x", "x": 2.0, "y": 0.0, "size": 2.0}, "out_of_range"),
    ("add_pipe_rack", {"name": "x", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": "up", "height": 4.0}, "bad_args"),
    ("add_light", {"name": "x", "x": 1.0, "y": 1.0}, "bad_args"),
    ("set_floor", {"friction": 9.0}, "out_of_range"),
    ("set_floor", {"friction": None}, "bad_args"),
    ("set_payload", {"mass_kg": -1.0}, "out_of_range"),
    ("set_gravity", {"g": 0.0}, "out_of_range"),
    ("set_route", {"waypoints": []}, "bad_args"),
    ("set_route", {"waypoints": "north"}, "bad_args"),
    ("set_route", {"waypoints": [{"x": 0.1, "y": 0.0}]}, "route_leg_too_short"),
    ("set_route", {"waypoints": [{"x": 1.0 + i, "y": 0.0} for i in range(W.MAX_WAYPOINTS + 1)]}, "too_many_waypoints"),
    ("set_route", {"waypoints": [{"x": 1.0, "y": 0.0, "code": "x"}]}, "bad_args"),
    ("add_tank", {"name": "x", "x": 1.0, "y": 1.0, "radius": -1.0}, "out_of_range"),
    ("run_code", {}, "unknown_function"),
    ("__class__", {}, "unknown_function"),
    (["add_box"], {}, "unknown_function"),
]


def state_diff(a, b):
    same_len = len(a["t"]) == len(b["t"])
    return {
        "bitwise_equal": bool(same_len and all(np.array_equal(a[k], b[k]) for k in ("body_q", "joint_q", "body_qd"))),
        "frames": [len(a["t"]), len(b["t"])],
        "final_base_m": round(float(np.linalg.norm(a["base_q"][-1, :3] - b["base_q"][-1, :3])), 3),
    }


def _child(name, out):
    code = f"from packs.inspection import check_pack as C, sim as S; S.run(C.world_of({name!r}), seed={SEED}, out={str(out)!r})"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, cwd=str(S.HERE.parents[1]))
    return S.load(out)[0]


def world_of(name):
    return W.build(*WORLDS[name])


def write_replay(name, rec, meta, result):
    data = P.replay(rec, meta, result)
    path = OUT / f"{name}.replay.json.gz"
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(data, separators=(",", ":")).encode())
    return data, path


def replay_errors(data, rec, path):
    with gzip.open(path, "rb") as f:
        back = json.loads(f.read())
    errors = []
    if back != data or back["simulated"] is not True:
        errors.append("replay file differs from its data")
    nb = len(back["body_labels"])
    frames = back["frames"]
    if len(frames) != (len(rec["t"]) + S.REPLAY_STRIDE - 1) // S.REPLAY_STRIDE or any(len(f["q"]) != nb * 7 for f in frames):
        errors.append("replay has the wrong frame shape")
    last = (len(rec["t"]) - 1) // S.REPLAY_STRIDE
    if np.abs(np.array(frames[last]["q"]) - rec["body_q"][last * S.REPLAY_STRIDE].ravel()).max() > 1e-3:
        errors.append("replay poses differ from the record")
    return errors


def main():
    OUT.mkdir(exist_ok=True)
    results = {"label": S.code_label(), "note": S.NOTE, "worlds": {}}
    failures = []

    def need(ok, text):
        if not ok:
            failures.append(text)

    need(not missing(P), f"pack is missing {missing(P)}")
    base = W.new_world()
    snapshot = copy.deepcopy(base)
    for fn, args, code in REFUSALS:
        got = P.call(base, fn, args)
        need(got["result"] == f"cannot_build:{code}", f"refusal {fn}: {got['result']}, wanted {code}")
        need(got["world"] == snapshot and got["rerun"] is False, f"refusal {fn} changed the world")
    for bad in (None, [], {"schema": 1}, {**base, "schema": 2}, {**base, "objects": [{"kind": "mesh", "path": "/etc/passwd"}]}, {**base, "objects": "x"}, {**base, "extra": 1}):
        try:
            W.validate(bad)
            failures.append(f"validate took a bad world: {str(bad)[:60]}")
        except W.Refuse as refused:
            need(refused.code == "invalid_world", f"validate gave {refused.code}")
    results["refusals_checked"] = len(REFUSALS)

    picture = P.call(base, "add_tank", {"name": "t", "x": 3.0, "y": 3.0, "radius": 1.0})
    need(picture["result"] == W.PICTURE and picture["rerun"] is False, f"a tank should be picture only: {picture['result']}")
    need(P.physics_hash(picture["world"]) == P.physics_hash(base), "scenery should leave the physics hash")
    edit = P.call(base, "add_box", {"name": "b", "x": 3.0, "y": 3.0, "sx": 1, "sy": 1, "sz": 1})
    need(edit["result"] == W.OK and edit["rerun"] is True, "a box should need a re-run")

    records = {}
    for name in WORLDS:
        world = world_of(name)
        rec, meta = P.run(world, seed=SEED, out=OUT / f"{name}.npz")
        result = P.judge(rec, world)
        records[name] = rec
        data, path = write_replay(name, rec, meta, result)
        failures.extend(f"{name}: {e}" for e in replay_errors(data, rec, path))
        results["worlds"][name] = {
            **result, "frames": len(rec["t"]), "shapes": meta["shapes"], "rtf": round(meta["rtf"], 2), "peak_nacon": meta["peak_nacon"], "peak_nefc": meta["peak_nefc"],
            "total_mass_kg": round(meta["total_mass_kg"], 1), "mean_support_N": round(float((rec["ground_f"] + rec["object_f"])[50:].mean()), 1), "replay_kb": round(path.stat().st_size / 1024),
        }
        print(name, results["worlds"][name], flush=True)
        need(meta["peak_nacon"] < meta["nconmax"], f"{name}: the contact buffer filled")
        need(not meta["sim_failed"], f"{name}: the physics blew up")

    w = results["worlds"]
    plant, plant_rec = w["plant"], records["plant"]
    need(plant["passed"], f"plant should pass: {plant['reason']}")
    for name in ("low_pipe", "dropped_tray", "valve", "leak_walkway", "leak_corner", "steep_crossover", "payload_10kg", "gravity_3_71"):
        results.setdefault("vs_plant", {})[name] = state_diff(records[name], plant_rec)
        need(not results["vs_plant"][name]["bitwise_equal"], f"{name} should change the run")
    for name in ("low_pipe", "dropped_tray", "valve", "steep_crossover"):
        need(w[name]["object_peak_N"] > plant["object_peak_N"] or w[name]["object_contact_s"] > plant["object_contact_s"], f"{name} should add contact")
        need(not w[name]["passed"] or w[name]["time_s"] != plant["time_s"], f"{name} should change the result")
    need(w["leak_walkway"]["foot_slip_mps"] > plant["foot_slip_mps"], "the leak should slip more than plant")
    need(w["leak_corner"]["foot_slip_mps"] > plant["foot_slip_mps"] or not w["leak_corner"]["passed"], "the leak at the corner should slip more or fail")

    results["clear_cabinet_vs_plant"] = state_diff(records["clear_cabinet"], plant_rec)
    need(results["clear_cabinet_vs_plant"]["bitwise_equal"], "a clear object should leave the run bitwise the same")
    need(w["clear_cabinet"]["shapes"] == plant["shapes"] + 1, "clear_cabinet should hold one more shape")
    need(w["clear_cabinet"]["object_peak_N"] == plant["object_peak_N"], "clear_cabinet should add no contact")

    bare = W.build(("set_route", PL.ROUTE), *PL.WALKWAY)
    rec, _ = P.run(bare, seed=SEED)
    results["scenery_vs_bare"] = state_diff(rec, plant_rec)
    need(results["scenery_vs_bare"]["bitwise_equal"], "scenery should leave the run bitwise the same")

    weight = plant["total_mass_kg"] * W.EARTH_G
    need(abs(plant["mean_support_N"] - weight) < 0.15 * weight, f"mean support force {plant['mean_support_N']} should be near the weight {weight:.0f}")
    loaded = w["payload_10kg"]
    need(abs(loaded["total_mass_kg"] - plant["total_mass_kg"] - 10.0) < 0.01, "the payload should add 10 kg")
    need(abs(loaded["mean_support_N"] - loaded["total_mass_kg"] * W.EARTH_G) < 0.15 * loaded["total_mass_kg"] * W.EARTH_G, "the support force should carry the payload")
    light = w["gravity_3_71"]
    need(abs(light["mean_support_N"] - light["total_mass_kg"] * 3.71) < 0.2 * light["total_mass_kg"] * 3.71, "the support force should follow gravity")

    world = world_of("plant")
    blown = P.judge({**plant_rec, "sim_failed": np.array(True)}, world)
    need(blown["verdict"] == "sim_failed" and not blown["passed"], "a blown-up run should not pass")
    again, _ = P.run(world, seed=SEED)
    other_process = _child("plant", OUT / "plant_process2.npz")
    (OUT / "plant_process2.npz").unlink()
    results["determinism"] = {"same_seed_same_process": state_diff(plant_rec, again), "same_seed_new_process": state_diff(plant_rec, other_process)}
    need(results["determinism"]["same_seed_same_process"]["bitwise_equal"], "same seed in one process should match")
    need(results["determinism"]["same_seed_new_process"]["bitwise_equal"], "same seed in a new process should match")
    seeds = {}
    for seed in (1, 2, 3, 4):
        rec, meta = P.run(world, seed=seed)
        got = P.judge(rec, world)
        seeds[seed] = {"verdict": got["verdict"], "time_s": got["time_s"], "deviation_max_m": got["deviation_max_m"], "differs_from_seed_0": not state_diff(rec, plant_rec)["bitwise_equal"]}
        need(got["passed"], f"plant seed {seed}: {got['reason']}")
        need(seeds[seed]["differs_from_seed_0"], f"seed {seed} should differ from seed 0")
    results["other_seeds"] = seeds

    results["failures"] = failures
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({k: v for k, v in results.items() if k != "worlds"}, indent=1))
    print("FAIL" if failures else "PASS", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
