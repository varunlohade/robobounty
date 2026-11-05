"""Checks world schema v4: hostile specs rejected, each element changes the physics, old worlds unchanged, build speed.

check_elements.py [--replays N] [--campaigns DIR ...]
Old worlds: builds the MJCF with the frozen world.py from git and with this one and compares bytes, then replays stored logs and compares state hashes.
"""
import argparse
import copy
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay
import sim as S
import world as W

FREEZE = "aa9be66"
NOMINAL = W.load(HERE / "worlds" / "nominal.json")


def v4(*elements, **fields):
    return {**NOMINAL, "schema": W.SCHEMA_V4, "elements": list(elements), **fields}


LEDGE = {"type": "ledge", "x_m": 2.0, "below_top_m": 1.5, "width_m": 1.0, "depth_m": 0.1, "thick_m": 0.1}
HOSTILE = {
    "unknown type": v4({"type": "mesh", "file": "/etc/passwd"}),
    "type not a string": v4({**LEDGE, "type": 1}),
    "xml in a type": v4({**LEDGE, "type": "<include file='x'/>"}),
    "extra field": v4({**LEDGE, "file": "a.stl"}),
    "missing field": v4({k: v for k, v in LEDGE.items() if k != "depth_m"}),
    "text in a number": v4({**LEDGE, "x_m": "<geom/>"}),
    "bool in a number": v4({**LEDGE, "x_m": True}),
    "out of range": v4({**LEDGE, "depth_m": 5.0}),
    "nan": v4({**LEDGE, "x_m": float("nan")}),
    "infinity": v4({**LEDGE, "x_m": float("inf")}),
    "float in an integer": v4({"type": "corner", "x_m": 3.0, "side": 1.0}),
    "zero corner side": v4({"type": "corner", "x_m": 3.0, "side": 0}),
    "over the type cap": v4(*[dict(LEDGE)] * 7),
    "over the total cap": v4(*([dict(LEDGE)] * 6 + [{"type": "sill", "x_m": 2.0, "below_top_m": 1.0, "width_m": 1.0, "depth_m": 0.01, "thick_m": 0.05}] * 6
                               + [{"type": "fin", "x_m": 2.0, "below_top_m": 1.0, "height_m": 1.0, "depth_m": 0.1, "thick_m": 0.05}] * 8
                               + [{"type": "sign", "x_m": 2.0, "below_top_m": 1.0, "width_m": 1.0, "height_m": 1.0, "depth_m": 0.1, "color": 0}] * 4
                               + [{"type": "vent", "x_m": 2.0, "below_top_m": 1.0, "width_m": 1.0, "height_m": 0.5, "open_frac": 0.2}])),
    "elements not a list": v4(),
    "element not an object": v4("ledge"),
    "blocks the start": v4({**LEDGE, "x_m": 0.15, "below_top_m": -0.13}),
    "cradle on the start": v4({"type": "cradle", "x_m": 0.15, "below_top_m": -0.13, "width_m": 1.0, "height_m": 0.5, "travel_m": 0.0, "period_s": 50.0}),
    "corner off the start": v4({"type": "corner", "x_m": 0.2, "side": 1}),
    "elements on a v3 world": {**NOMINAL, "elements": []},
    "nested object": v4({**LEDGE, "x_m": {"$ref": "x"}}),
}
HOSTILE["elements not a list"]["elements"] = {"type": "ledge"}


def check_hostile(failures):
    for name, raw in HOSTILE.items():
        try:
            W.validate(copy.deepcopy(raw))
            failures.append(f"accepted: {name}")
        except W.WorldError:
            pass
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "huge.json"
        p.write_text(" " * (W.MAX_WORLD_FILE_BYTES + 1) + json.dumps(NOMINAL))
        try:
            W.load(p)
            failures.append("accepted: huge file")
        except W.WorldError:
            pass
        p.write_text('{"schema": "highrise.world.v4", "elements": [{"type": "ledge", "x_m": NaN}]}')
        try:
            W.load(p)
            failures.append("accepted: NaN in JSON text")
        except W.WorldError:
            pass
    for raw in [v4(LEDGE)]:
        xml = W.build_xml(W.validate(raw))
        if "include" in xml or "file=" in xml:
            failures.append("MJCF reaches for a file")
    print(f"hostile specs rejected: {len(HOSTILE) + 2}")


def drive(world, speed, ticks, seed=3):
    """Drives straight down the first lane with no controller."""
    sim = S.Sim(world, seed)
    sim.min_dp = sim.dp
    for _ in range(ticks):
        if not sim.step([speed, speed, 1.0, 0.6, 0.0, 0.0]):
            raise RuntimeError("bad action")
        sim.min_dp = min(sim.min_dp, sim.dp)
    return sim


def check_effects(failures):
    """Each element against the same run without it. x_m 0.15 is the first lane, which runs down from the start."""
    sill = {"type": "sill", "x_m": 0.15, "below_top_m": 1.0, "width_m": 0.8, "depth_m": 0.05, "thick_m": 0.05}
    ledge = {**LEDGE, "x_m": 0.15, "below_top_m": 1.0, "width_m": 0.8, "depth_m": 0.15}
    fin = {"type": "fin", "x_m": 0.15, "below_top_m": 1.5, "height_m": 0.8, "depth_m": 0.3, "thick_m": 0.1}
    sign = {"type": "sign", "x_m": 0.15, "below_top_m": 1.0, "width_m": 0.8, "height_m": 0.4, "depth_m": 0.12, "color": 0}
    balcony = {"type": "balcony", "x_m": 0.5, "below_top_m": 1.0, "width_m": 2.0, "depth_m": 1.0, "slab_m": 0.2}
    step = {"type": "frame_step", "x_m": 0.15, "below_top_m": 1.0, "width_m": 0.8, "height_m": 0.5, "step_m": 0.028}
    vent = {"type": "vent", "x_m": 0.15, "below_top_m": 0.9, "width_m": 0.8, "height_m": 0.5, "open_frac": 0.5}
    wet = {"type": "wet_patch", "x_m": 0.15, "below_top_m": 0.5, "width_m": 1.5, "height_m": 3.0, "wetness": 1.0}
    grid = {"type": "pane_grid", "pane_width_m": 0.9, "pane_height_m": 2.2, "offset_x_m": 0.15, "offset_z_m": 0.3, "mullion_depth_m": 0.03, "skip_every": 0}
    corner = {"type": "corner", "x_m": 1.0, "side": 1}
    calm = {"gust_count": 0, "steady_wind_ms": 0.0}
    base = W.validate({**NOMINAL, "schema": W.SCHEMA_V4, **calm})
    plain = drive(base, 0.15, 400)
    z_plain = plain.body_xz()[1]
    print(f"baseline: 20 s down from start, travelled {W.start_pose(base)[1] - z_plain:.2f} m, pressure {plain.dp:.0f} Pa")
    for name, el in (("ledge", ledge), ("sill", sill), ("fin", fin), ("sign", sign), ("balcony", balcony), ("frame_step", step)):
        sim = drive(W.validate(v4(el, **calm)), 0.15, 400)
        short = sim.body_xz()[1] - z_plain
        print(f"{name}: travel short by {short:.2f} m, pressure {sim.dp:.0f} Pa")
        if short < 0.1:
            failures.append(f"{name} did not stop or slow the robot")
    sim = drive(W.validate(v4(vent, **calm)), 0.15, 400)
    drop = plain.min_dp - sim.min_dp
    print(f"vent: lowest pressure {sim.min_dp:.0f} Pa against {plain.min_dp:.0f} Pa, end gap {sim.gap_center:.3f} m")
    if drop < 500:
        failures.append("vent did not change the seal")
    sim = drive(W.validate(v4(wet, **{**calm, "wetness": 0.0})), 0.15, 300)
    dry = S.Sim(W.validate(v4(wet, **{**calm, "wetness": 0.0})), 1).m.geom_friction[sorted(S.Sim(base, 1).roller_geoms)[0], 0]
    mu = sim.m.geom_friction[sim.el_roller_ids, 0]
    print(f"wet_patch: roller friction {np.round(mu, 3).tolist()} over the patch, world friction {W.friction({**base, 'wetness': 0.0}):.3f}")
    if not np.any(mu < 0.5):
        failures.append("wet_patch did not lower roller friction")
    dirty = {"type": "dirt_patch", "x_m": 1.0, "below_top_m": 1.0, "width_m": 1.0, "height_m": 1.0, "level": 2.0}
    sim = S.Sim(W.validate(v4(dirty, **calm)), 3)
    if sim.dirt.max() < S.Sim(base, 3).dirt.max() + 1.5:
        failures.append("dirt_patch did not add dirt")
    print(f"dirt_patch: peak dirt {sim.dirt.max():.2f}, friction there {sim.el_patches[0][4]:.3f}")
    sim = drive(W.validate(v4(grid, **calm)), 0.15, 400)
    short = sim.body_xz()[1] - z_plain
    print(f"pane_grid: {len(sim.mullions)} mullions, {len(sim.transoms)} transoms, depth {sim.joint_depth}, travel short by {short:.2f} m, pressure {sim.dp:.0f} Pa")
    if len(sim.mullions) == len(plain.mullions) and len(sim.transoms) == len(plain.transoms):
        failures.append("pane_grid did not change the layout")
    w_corner = W.validate(v4(corner, **calm))
    sim = S.Sim(w_corner, 3)
    print(f"corner: glass ends at x {sim.glass['x1']:.2f}, {int(sim.dirt_mask.sum())} glass cells of {sim.dirt_mask.size}")
    for _ in range(100):
        sim.step([0.0, 0.0, 1.0, 0.6, 0.0, 0.0])
    # Turn towards the corner and drive off the edge.
    while abs(sim.heading()) > 0.05 and sim.t < 40:
        sim.step([0.08, -0.08, 1.0, 0.6, 0.0, 0.0])
    t0 = sim.t
    while sim.center_on_glass() and sim.t < t0 + 60:
        sim.step([0.2, 0.2, 1.0, 0.6, 0.0, 0.0])
    print(f"corner: drove off the edge at t {sim.t:.1f} s, pressure {sim.dp:.0f} Pa, gap {sim.gap_center:.3f} m")
    if sim.center_on_glass():
        failures.append("robot never reached the corner")
    sb = {"type": "setback", "above_top_m": 0.7, "depth_m": 2.0}
    sim = S.Sim(W.validate(v4(sb, **calm)), 3)
    print(f"setback: glass top {sim.glass['z1']:.2f} against {plain.glass['z1']:.2f}")
    if sim.glass["z1"] >= plain.glass["z1"]:
        failures.append("setback did not lower the glass top")
    cradle = {"type": "cradle", "x_m": 0.15, "below_top_m": 1.2, "width_m": 1.0, "height_m": 0.6, "travel_m": 3.0, "period_s": 30.0}
    w = W.validate(v4(cradle, **calm))
    sim = S.Sim(w, 3)
    z0 = sim.body_xz()[1]
    zs = []
    hit = 0.0
    for _ in range(1200):
        sim.step([0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        zs.append(float(sim.d.mocap_pos[0, 2]))
        hit = max(hit, sim.impact_tick)
    print(f"cradle: moved {max(zs) - min(zs):.2f} m, peak chassis contact {hit:.0f} N, robot moved {abs(sim.body_xz()[1] - z0):.2f} m")
    if max(zs) - min(zs) < 1.0:
        failures.append("cradle did not move")
    if hit <= 0 and abs(sim.body_xz()[1] - z0) < 0.02:
        failures.append("cradle did not touch the robot")


def check_old_worlds(failures, campaigns, replays):
    source = subprocess.run(["git", "show", f"{FREEZE}:policy/highrise/world.py"], capture_output=True, text=True, check=True, cwd=HERE).stdout
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frozen_world.py"
        path.write_text(source)
        spec = importlib.util.spec_from_file_location("frozen_world", path)
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
    trials = []
    for c in campaigns:
        for line in (Path(c) / "results.jsonl").read_text().splitlines():
            trials.append(Path(c) / json.loads(line)["trial"])
    same = 0
    for t in trials:
        world = json.loads((t / "world.json").read_text())
        if W.build_xml(W.validate(world)) != frozen.build_xml(frozen.validate(world)):
            failures.append(f"MJCF changed: {t.name}")
        else:
            same += 1
        if W.world_hash(W.validate(world)) != frozen.world_hash(frozen.validate(world)):
            failures.append(f"world hash changed: {t.name}")
    print(f"old worlds: MJCF byte-identical to {FREEZE} on {same}/{len(trials)}")
    random.Random(4).shuffle(trials)
    matched = 0
    for t in trials[:replays]:
        r = replay.replay(t)
        if r["first_divergent_step"] is None and r["final_state_match"] and r["chain_ok"] and r["model_match"] and r["start_state_match"]:
            matched += 1
        else:
            failures.append(f"state hash differs: {t}")
    print(f"old worlds: every step's state hash matches on {matched}/{min(replays, len(trials))} replays")


def check_wasm(failures):
    """Loads and steps every sample in the browser build of MuJoCo, under Node."""
    module = HERE.parent.parent / "node_modules" / "@mujoco" / "mujoco" / "mujoco.js"
    with tempfile.TemporaryDirectory() as tmp:
        for path in sorted((HERE / "worlds" / "samples").glob("*.json")):
            (Path(tmp) / f"{path.stem}.xml").write_text(W.build_xml(W.load(path)))
        script = Path(tmp) / "load.mjs"
        script.write_text(f"""import fs from 'node:fs';
import load from '{module}';
const mj = await load();
let n = 0;
const version = mj.mj_versionString ? mj.mj_versionString() : 'unknown';
for (const f of fs.readdirSync('{tmp}').filter(f => f.endsWith('.xml'))) {{
  const m = mj.MjModel.from_xml_string(fs.readFileSync('{tmp}/' + f, 'utf8'));
  const d = new mj.MjData(m);
  for (let i = 0; i < 500; i++) mj.mj_step(m, d);
  n += 1;
}}
console.log(version, n);
""")
        done = subprocess.run(["node", str(script)], capture_output=True, text=True)
    print(f"browser MuJoCo under Node: version and samples loaded and stepped: {done.stdout.strip()}")
    if done.returncode != 0 or not done.stdout.strip().endswith(" 8"):
        failures.append(f"wasm load failed: {done.stderr[-300:]}")


def check_speed(failures):
    times = {}
    for path in sorted((HERE / "worlds" / "samples").glob("*.json")):
        t0 = time.perf_counter()
        sim = S.Sim(W.load(path), 1)
        times[path.stem] = (time.perf_counter() - t0, sim.m.ngeom)
    worst = max(t for t, _ in times.values())
    print("build seconds, validate to ready:", {k: (round(t, 3), n) for k, (t, n) in times.items()})
    if worst > 2.0:
        failures.append(f"build took {worst:.2f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replays", type=int, default=0)
    ap.add_argument("--campaigns", nargs="*", default=[])
    a = ap.parse_args()
    failures = []
    check_hostile(failures)
    check_effects(failures)
    check_speed(failures)
    check_wasm(failures)
    if a.campaigns:
        check_old_worlds(failures, a.campaigns, a.replays)
    print("FAIL" if failures else "PASS", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
