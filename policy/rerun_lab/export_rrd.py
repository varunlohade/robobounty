"""Turns recorded CrashLab runs into Rerun .rrd files. Reads recorded files only and never runs physics. Every recording is labelled simulated.

From policy/rerun_lab: .venv/bin/python export_rrd.py [--out DIR]
Writes window.rrd, inspection.rrd and compare.rrd.
One run, for the lab's Open in Rerun button: export_rrd.py --window-run DIR --to FILE, or --inspection-run NPZ REPLAY --to FILE.
"""
import argparse
import ast
import gzip
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import rerun as rr
import rerun.blueprint as rrb

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
ROOT = POLICY.parent
sys.path[:0] = [str(POLICY), str(POLICY / "highrise5")]
import compile5 as C
import world5 as W
from packs.inspection.judge import _deviation

WINDOW_RUN = POLICY / "runs/board/exp/weak/w013/run"
INSPECTION_RECORD = POLICY / "packs/inspection/out/low_pipe.npz"
INSPECTION_REPLAY = POLICY / "packs/inspection/out/low_pipe.replay.json.gz"
ROBOT_MESH = ROOT / "public/robots/anymal_c"
COMPARE_DIR = POLICY / "runs/highrise/campaign_dubai_v4/fix"
BEFORE_RUN = COMPARE_DIR / "baseline/runs/seen/A/t0030"
AFTER_RUN = COMPARE_DIR / "try_2/runs/seen/B/t0030"

TIMELINE = "sim_time"
RED = [235, 60, 50]
AMBER = [245, 170, 40]
BLUE = [70, 150, 245]
GREY = [170, 175, 180]
WINDOW_CHARTS = {"suction_pa": "Suction (Pa)", "wind_ms": "Wind (m/s)", "speed_ms": "Speed (m/s)", "coverage_pct": "Coverage (%)", "battery_v": "Battery (V)", "tether_n": "Tether (N)"}
INSPECTION_CHARTS = {"foot_slip_mps": "Foot slip (m/s)", "base_height_m": "Base height (m)", "deviation_m": "Route deviation (m)", "object_force_n": "Object contact (N)"}
RULE_WORDS = {
    "detach": "The robot came off the glass at {t:.1f} s.",
    "false_done": "The robot reported done at {t:.1f} s, with more coverage than it had.",
    "slip_distance": "The robot slid {value:.3f} m in one slide at {t:.1f} s.",
    "coverage": "The robot cleaned {coverage:.1f}% of the glass.",
}


def load_json(path):
    with gzip.open(path, "rb") as f:
        return json.load(f)


def stream(app, source_bytes, name):
    # A stable recording id, so the same source gives the same recording.
    rid = hashlib.sha256(source_bytes).hexdigest()[:32]
    rec = rr.RecordingStream(app, recording_id=rid, send_properties=False)
    rec.send_recording_name(name)
    return rec


def label_simulated(rec, path, label, note, reason, facts):
    rec.send_property("crashlab", rr.AnyValues(simulated=True, label=label, note=note, reason=reason))
    lines = ["# SIMULATED RUN", "", note, "", f"**Judge:** {reason}", "", f"**Label:** `{label}`", ""]
    lines += [f"- {k}: `{v}`" for k, v in facts.items()]
    rec.log(f"{path}run_info", rr.TextDocument("\n".join(lines), media_type="text/markdown"), static=True)


def send_scalar(rec, entity, t, values, color, name):
    rec.log(entity, rr.SeriesLines(colors=[color], names=[name], widths=[1.5]), static=True)
    rec.send_columns(entity, indexes=[rr.TimeColumn(TIMELINE, duration=np.asarray(t, dtype=np.float64))], columns=rr.Scalars.columns(scalars=np.asarray(values, dtype=np.float64)))


def send_failure_point(rec, chart, t, value):
    """A red marker on one chart. Rerun has no vertical line for a moment in a time series, so each chart gets a point."""
    entity = f"{chart}/failure"
    rec.log(entity, rr.SeriesPoints(colors=[RED], names=["failure"], marker_sizes=[6.0], markers=["cross"]), static=True)
    rec.send_columns(entity, indexes=[rr.TimeColumn(TIMELINE, duration=[t])], columns=rr.Scalars.columns(scalars=[float(value)]))


def send_events(rec, entity, events):
    events = sorted(events, key=lambda e: e[0])
    rec.send_columns(entity, indexes=[rr.TimeColumn(TIMELINE, duration=[e[0] for e in events])],
                     columns=rr.TextLog.columns(text=[e[2] for e in events], level=[e[1] for e in events]))


def whole_run(duration):
    """Without this a chart shows about one minute around the cursor, not the run."""
    return rrb.TimeAxis(view_range=rr.TimeRange(start=rrb.TimeRangeBoundary.absolute(seconds=0.0), end=rrb.TimeRangeBoundary.absolute(seconds=float(duration))))


def value_at(t, values, at):
    t, values = np.asarray(t), np.asarray(values)
    return float(values[min(int(np.searchsorted(t, at)), len(values) - 1)])


# Window robot


def wind_model(sim_file):
    """Takes the Wind class from the run's sim source, so this file does not need MuJoCo and holds no second copy of the formula."""
    tree = ast.parse(Path(sim_file).read_text())
    keep = [n for n in tree.body if (isinstance(n, ast.ClassDef) and n.name == "Wind")
            or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TURBULENCE_FRACTION")]
    space = {"math": math, "np": np}
    exec(compile(ast.Module(keep, []), str(sim_file), "exec"), space)
    return space["Wind"]


def euler_xyz_quat(euler):
    """MuJoCo's default euler order, in degrees, as x y z w."""
    q = np.array([0.0, 0.0, 0.0, 1.0])
    for axis, angle in enumerate(euler):
        half = math.radians(angle) / 2
        s = np.zeros(3)
        s[axis] = math.sin(half)
        w1, v1, w2, v2 = q[3], q[:3], math.cos(half), s
        q = np.append(w1 * v2 + w2 * v1 + np.cross(v1, v2), w1 * w2 - v1 @ v2)
    return q


def rotate(q, v):
    return np.asarray(v) + 2 * np.cross(q[:3], np.cross(q[:3], v) + q[3] * np.asarray(v))


def rgba255(rgba, alpha=None):
    a = rgba[3] if alpha is None else alpha
    return [int(round(c * 255)) for c in (*rgba[:3], a)]


def log_shape_group(rec, entity, shapes):
    """shapes: dicts of type, size (half sizes, or radius and half length), pos, quat (x y z w), colour."""
    for kind in ("box", "cylinder", "capsule", "sphere"):
        group = [s for s in shapes if s["type"] == kind]
        if not group:
            continue
        pos = np.array([s["pos"] for s in group], dtype=np.float32)
        quat = [rr.Quaternion(xyzw=s["quat"]) for s in group]
        colours = [s["colour"] for s in group]
        path = f"{entity}/{kind}s"
        if kind == "box":
            rec.log(path, rr.Boxes3D(half_sizes=[s["size"][:3] for s in group], centers=pos, quaternions=quat, colors=colours, fill_mode="solid"), static=True)
        elif kind == "cylinder":
            rec.log(path, rr.Cylinders3D(radii=[s["size"][0] for s in group], lengths=[s["size"][1] * 2 for s in group], centers=pos, quaternions=quat, colors=colours, fill_mode="solid"), static=True)
        elif kind == "capsule":
            # A Rerun capsule starts at its translation and runs along +z. Ours are centred.
            start = np.array([np.asarray(s["pos"]) - rotate(np.array(s["quat"]), [0.0, 0.0, s["size"][1]]) for s in group], dtype=np.float32)
            rec.log(path, rr.Capsules3D(radii=[s["size"][0] for s in group], lengths=[s["size"][1] * 2 for s in group], translations=start, quaternions=quat, colors=colours), static=True)
        else:
            rec.log(path, rr.Ellipsoids3D(half_sizes=[[s["size"][0]] * 3 for s in group], centers=pos, colors=colours, fill_mode="solid"), static=True)


def compiled_shapes(world):
    """The window scene from the same compiler the run used. Returns (scene shapes, robot shapes in the body frame)."""
    root = ET.fromstring(C.compile(world)[1])
    materials = {m.get("name"): [float(v) for v in m.get("rgba", "0.6 0.6 0.6 1").split()] for m in root.findall("asset/material")}

    def shape(g, offset=(0.0, 0.0, 0.0)):
        kind = g.get("type") or ("sphere" if g.get("name", "").startswith("roller") else "box")
        size = [float(v) for v in g.get("size", "0.035").split()]
        pos = np.array([float(v) for v in g.get("pos", "0 0 0").split()]) + offset
        quat = euler_xyz_quat([float(v) for v in g.get("euler").split()]) if g.get("euler") else np.array([0.0, 0.0, 0.0, 1.0])
        if g.get("quat"):
            w, x, y, z = [float(v) for v in g.get("quat").split()]
            quat = np.array([x, y, z, w])
        name = g.get("material") or ("alu" if g.get("class") == "joint" else "cream" if g.get("name") == "chassis" else "rubber")
        return {"type": kind, "size": size, "pos": pos.tolist(), "quat": quat.tolist(), "colour": rgba255(materials.get(name, [0.6, 0.6, 0.6, 1.0])), "name": g.get("name")}

    body = root.find("worldbody")
    scene = [shape(g) for g in body.findall("geom") if g.get("type") in ("box", "capsule", "cylinder", "sphere")]
    for s in scene:
        if s["name"] == "glass":
            s["colour"] = [52, 78, 104, 110]
    robot_body = body.find("body[@name='robot']")
    robot = [shape(g) for g in robot_body.findall("geom")]
    for child in robot_body.findall("body"):
        offset = np.array([float(v) for v in child.get("pos").split()])
        robot += [shape(g, offset) for g in child.findall("geom")]
    return scene, robot


def reason_words(result):
    rule = result.get("failure")
    if not rule:
        return f"The run passed with {result['coverage'] * 100:.1f}% of the glass clean." if result.get("passed") else f"The run ended as {result.get('outcome')}."
    event = result["fired"][rule]
    words = RULE_WORDS.get(rule, "The judge fired " + rule + " at {t:.1f} s.")
    return words.format(t=event["t"], value=event["value"], coverage=result["coverage"] * 100)


def log_window_run(rec, run, prefix="", tint=RED, facts_label=""):
    run = Path(run)
    result = json.loads((run / "result.json").read_text())
    raw_world = json.loads((run / "world.json").read_text())
    world = W.load(run / "world.json")
    recording, trace = load_json(run / "qpos.json.gz"), load_json(run / "trace.json.gz")
    hz = recording["hz"]
    frames = np.array(recording["frames"], dtype=np.float64)
    t = np.arange(len(frames)) / hz
    columns = {name: i for i, name in enumerate(trace["columns"])}
    rows = trace["rows"]
    t_row = (np.arange(len(rows)) + 1) / hz
    col = lambda name: np.array([r[columns[name]] for r in rows], dtype=np.float64)
    speed = np.hypot(np.diff(frames[:, 0]), np.diff(frames[:, 2])) * hz
    sim_file = POLICY / ("highrise5/sim5.py" if raw_world.get("schema") == W.SCHEMA else "highrise/sim.py")
    wind = wind_model(sim_file)(raw_world, result["seed"])
    wind_ms = np.array([wind.speed_dir(float(x))[0] for x in t_row])
    coverage = [(t_row[i], r[columns["coverage"]] * 100) for i, r in enumerate(rows) if r[columns["coverage"]] is not None]
    fail_t = result["fired"][result["failure"]]["t"] if result.get("failure") else None

    world_root = f"{prefix}world"
    rec.log(world_root, rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)
    scene, robot = compiled_shapes(world)
    log_shape_group(rec, f"{world_root}/scene", scene)
    log_shape_group(rec, f"{world_root}/robot/body", robot)
    rec.send_columns(f"{world_root}/robot", indexes=[rr.TimeColumn(TIMELINE, duration=t)],
                     columns=rr.Transform3D.columns(translation=frames[:, :3], quaternion=frames[:, [4, 5, 6, 3]]))
    rec.log(f"{world_root}/path", rr.LineStrips3D([frames[:, :3] + [0.0, -0.13, 0.0]], colors=[tint], radii=[0.008]), static=True)

    area = W.area_rect(world)
    dirt = np.load(run / "dirt.npz") if (run / "dirt.npz").exists() else {"mask": np.zeros((1, 1), bool), "dirt": np.zeros((1, 1))}  # A recorded batch stores no dirt grid.
    iz, ix = np.nonzero(dirt["mask"])
    cell = (area["x1"] - area["x0"]) / dirt["mask"].shape[1]
    level = np.clip(dirt["dirt"][iz, ix] / max(world["area"]["dirt_level"], 1e-6), 0, 1)
    points = np.stack([area["x0"] + (ix + 0.5) * cell, np.full(len(ix), -0.003), area["z0"] + (iz + 0.5) * (area["z1"] - area["z0"]) / dirt["mask"].shape[0]], axis=1)
    dirt_colour = np.stack([70 + 120 * level, 140 - 40 * level, 150 - 110 * level], axis=1).astype(np.uint8)
    rec.log(f"{world_root}/final_dirt", rr.Points3D(points, colors=dirt_colour, radii=[cell / 2.2]), static=True)

    signals = f"{prefix}signals"
    colour = tint if prefix else BLUE
    suffix = f" {facts_label}" if facts_label else ""
    send_scalar(rec, f"{signals}/suction_pa/value", t_row, col("dp"), colour, f"pressure{suffix}")
    send_scalar(rec, f"{signals}/wind_ms/value", t_row, wind_ms, colour, f"wind, from the world and seed{suffix}")
    send_scalar(rec, f"{signals}/speed_ms/value", t_row, speed, colour, f"speed on the glass{suffix}")
    send_scalar(rec, f"{signals}/speed_ms/slip", t_row, col("slip_rate"), AMBER, f"slip rate{suffix}")
    send_scalar(rec, f"{signals}/coverage_pct/value", [c[0] for c in coverage], [c[1] for c in coverage], colour, f"coverage{suffix}")
    send_scalar(rec, f"{signals}/battery_v/value", t_row, col("volts"), colour, f"battery volts{suffix}")
    send_scalar(rec, f"{signals}/tether_n/value", t_row, col("tension"), colour, f"tether load{suffix}")

    reason = reason_words(result)
    label = result.get("label") or "sim highrise (older code, no label in the result)"
    facts = {"run": str(run.relative_to(ROOT)), "world_sha256": result["world_sha256"][:16], "seed": result["seed"],
             "min_pressure_pa": result.get("min_pressure_pa"), "peak_tether_n": result.get("peak_tether_n"), "coverage": result.get("coverage"),
             "wind source": "not in the trace; computed by the run's Wind class from the world and seed"}
    label_simulated(rec, f"{prefix}", label, "Results are simulated with hand-built physics. Not a real robot, and not calibrated.", reason, facts)

    events = []
    phase = None
    for i, r in enumerate(rows):
        if r[columns["phase"]] != phase:
            phase = r[columns["phase"]]
            events.append((float(t_row[i]), "INFO", f"Controller phase: {phase}"))
    for rule, event in result.get("fired", {}).items():
        events.append((float(event["t"]), "ERROR" if rule == result.get("failure") else "WARN", f"Judge rule {rule} fired, value {event['value']}"))
    if fail_t is not None:
        events.append((float(fail_t), "CRITICAL", f"FAILURE: {reason}"))
        i = min(int(np.searchsorted(t, fail_t)), len(frames) - 1)
        rec.log(f"{world_root}/failure", rr.Points3D([frames[i, :3] + [0.0, -0.15, 0.0]], colors=[RED], radii=[0.05], labels=[f"FAILURE {fail_t:.1f} s"], show_labels=True), static=True)
        for name, series_t, values in (("suction_pa", t_row, col("dp")), ("wind_ms", t_row, wind_ms), ("speed_ms", t_row, speed), ("coverage_pct", [c[0] for c in coverage], [c[1] for c in coverage]),
                                       ("battery_v", t_row, col("volts")), ("tether_n", t_row, col("tension"))):
            send_failure_point(rec, f"{signals}/{name}", float(fail_t), value_at(series_t, values, fail_t))
    send_events(rec, f"{prefix}events", events)
    return {"result": result, "fail_t": fail_t, "reason": reason, "end": frames[-1, :3], "area": area, "duration": float(t[-1])}


def window_blueprint(info):
    x, y, z = info["end"]
    eye = rrb.EyeControls3D(position=[x + 0.6, y - 3.6, z + 0.7], look_target=[x, y, z - 0.3], eye_up=[0, 0, 1])
    fail = info["fail_t"]
    return rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial3DView(name="Run in 3D (simulated)", origin="/world", eye_controls=eye, line_grid=rrb.LineGrid3D(visible=False), background=[28, 30, 34]),
                rrb.Vertical(rrb.TextDocumentView(name="Judge", origin="/run_info"), rrb.TextLogView(name="Events", origin="/events"), row_shares=[3, 2]),
                column_shares=[5, 3]),
            rrb.Grid(*[rrb.TimeSeriesView(name=title, origin=f"/signals/{key}", axis_x=whole_run(info["duration"]), plot_legend=rrb.PlotLegend(visible=False)) for key, title in WINDOW_CHARTS.items()], grid_columns=3),
            row_shares=[3, 2]),
        rrb.TopPanel(state="hidden"), rrb.BlueprintPanel(state="hidden"), rrb.SelectionPanel(state="hidden"),
        rrb.TimePanel(state="collapsed", timeline=TIMELINE, play_state="paused"),
        collapse_panels=False)


def export_window(out, run=WINDOW_RUN):
    source = (run / "result.json").read_bytes() + (run / "qpos.json.gz").read_bytes()
    result = json.loads((run / "result.json").read_text())
    world = W.load(run / "world.json")
    if C.physics_hash(world) != result["physics_sha256"]:
        raise SystemExit("The compiler no longer builds this run's physics, so the scene would not match the run.")
    rec = stream("crashlab_window", source, f"SIMULATED window run, {result['failure'] or result['outcome']} at {result['time_s']} s")
    rec.save(out)
    info = log_window_run(rec, run)
    rec.send_blueprint(window_blueprint(info), make_active=True, make_default=True)
    rec.flush()
    rec.disconnect()
    return info


# Inspection robot


def mesh_by_body():
    """The same robot mesh the app draws. One mesh per body, in the body frame, coloured per part."""
    manifest = json.loads((ROBOT_MESH / "robot.json").read_text())
    data = (ROBOT_MESH / "robot.bin").read_bytes()
    n, layout = manifest["vertices"], manifest["layout"]
    pos = np.frombuffer(data, np.float32, n * 3, layout["position"]).reshape(-1, 3)
    normal = np.frombuffer(data, np.float32, n * 3, layout["normal"]).reshape(-1, 3)
    index = np.frombuffer(data, np.uint32, manifest["indices"], layout["index"])
    bodies = {}
    for part in manifest["parts"]:
        tri = index[part["first_index"]:part["first_index"] + part["index_count"]]
        bodies.setdefault(part["body"], []).append((tri, part["colour"]))
    meshes = {}
    for body, parts in bodies.items():
        colours = np.zeros((n, 3), dtype=np.uint8)
        for tri, colour in parts:
            # A textured part has a white base colour. Rerun gets no texture here, so draw it mid grey.
            colours[tri] = [150, 150, 150] if min(colour) >= 0.99 else [int(c * 255) for c in colour]
        tri = np.concatenate([p[0] for p in parts])
        used, inverse = np.unique(tri, return_inverse=True)
        meshes[body] = rr.Mesh3D(vertex_positions=pos[used], vertex_normals=normal[used], vertex_colors=colours[used], triangle_indices=inverse.reshape(-1, 3))
    return meshes


def replay_shapes(items, alpha=None):
    out = []
    for s in items:
        out.append({"type": s["type"], "size": s["size"], "pos": s["pos"], "quat": s["quat"], "colour": rgba255([*s.get("colour", [0.5, 0.5, 0.5]), 1.0], alpha), "object": s.get("object", s["name"])})
    return out


def export_inspection(out, record_file=INSPECTION_RECORD, replay_file=INSPECTION_REPLAY):
    replay = load_json(replay_file)
    record = np.load(record_file)
    result = replay["result"]
    rec = stream("crashlab_inspection", record_file.read_bytes(), f"SIMULATED inspection run, {result['verdict']} at {result['fell_t_s']} s")
    rec.save(out)
    t = record["t"].astype(np.float64)
    rec.log("world", rr.ViewCoordinates.RIGHT_HAND_Z_UP, static=True)

    solids = replay_shapes(replay["solids"])
    for name in sorted({s["object"] for s in solids}):
        log_shape_group(rec, f"world/solids/{name}", [s for s in solids if s["object"] == name])
    log_shape_group(rec, "world/scenery", replay_shapes(replay["scenery"]))

    meshes = mesh_by_body()
    for i, body in enumerate(replay["body_labels"]):
        pose = record["body_q"][:, i].astype(np.float64)
        rec.send_columns(f"world/robot/{body}", indexes=[rr.TimeColumn(TIMELINE, duration=t)],
                         columns=rr.Transform3D.columns(translation=pose[:, :3], quaternion=pose[:, 3:7]))
        if body in meshes:
            rec.log(f"world/robot/{body}/mesh", meshes[body], static=True)

    route = np.array([[p["x"], p["y"]] for p in replay["route"]])
    rec.log("world/route", rr.LineStrips3D([np.c_[route, np.full(len(route), 0.03)]], colors=[GREY], radii=[0.012]), static=True)
    base = record["base_q"].astype(np.float64)
    rec.log("world/path", rr.LineStrips3D([np.c_[base[:, :2], np.full(len(base), 0.04)]], colors=[AMBER], radii=[0.012]), static=True)

    in_contact = record["feet"]
    slip = record["foot_v_xy"].astype(np.float64)
    any_foot = in_contact.any(axis=1)
    # NaN where no foot touches the floor, so the chart shows a gap and draws no line across it.
    slip_mean = np.array([slip[i][in_contact[i]].mean() if any_foot[i] else np.nan for i in range(len(t))])
    deviation = _deviation(base[:, :2], [tuple(p) for p in route])
    send_scalar(rec, "signals/foot_slip_mps/value", t, slip_mean, BLUE, "mean slip of the feet in contact")
    send_scalar(rec, "signals/base_height_m/value", t, base[:, 2], BLUE, "base height")
    send_scalar(rec, "signals/deviation_m/value", t, deviation, BLUE, "distance from the route")
    send_scalar(rec, "signals/object_force_n/value", t, record["object_f"].astype(np.float64), BLUE, "force on objects")

    fail_t = float(result["fell_t_s"])
    i = min(int(np.searchsorted(t, fail_t)), len(t) - 1)
    rec.log("world/failure", rr.Points3D([base[i, :3]], colors=[RED], radii=[0.08], labels=[f"FELL {fail_t:.1f} s"], show_labels=True), static=True)
    for name, series_t, values in (("foot_slip_mps", t[any_foot], slip_mean[any_foot]), ("base_height_m", t, base[:, 2]), ("deviation_m", t, deviation), ("object_force_n", t, record["object_f"])):
        send_failure_point(rec, f"signals/{name}", fail_t, value_at(series_t, values, fail_t))

    events = [(float(x), "INFO", f"Reached waypoint {n + 1}") for n, x in enumerate(result["waypoint_t_s"])]
    events.append((fail_t, "CRITICAL", f"FAILURE: {result['reason']}"))
    send_events(rec, "events", events)
    facts = {"run": str(record_file.relative_to(ROOT)), "robot": replay["robot"], "min_clearance_m": result["min_clearance_m"], "object_peak_N": result["object_peak_N"],
             "judge foot_slip_mps": result["foot_slip_mps"], "judge deviation_max_m": result["deviation_max_m"]}
    label_simulated(rec, "", replay["label"], replay["note"], result["reason"], facts)

    eye = rrb.EyeControls3D(position=[base[-1, 0] - 1.7, base[-1, 1] - 1.1, 1.1], look_target=[base[-1, 0], base[-1, 1], 0.15], eye_up=[0, 0, 1])
    blueprint = rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial3DView(name="Run in 3D (simulated)", origin="/world", eye_controls=eye, line_grid=rrb.LineGrid3D(visible=False), background=[28, 30, 34]),
                rrb.Vertical(rrb.TextDocumentView(name="Judge", origin="/run_info"), rrb.TextLogView(name="Events", origin="/events"), row_shares=[3, 2]),
                column_shares=[5, 3]),
            rrb.Grid(*[rrb.TimeSeriesView(name=title, origin=f"/signals/{key}", axis_x=whole_run(t[-1]), plot_legend=rrb.PlotLegend(visible=False)) for key, title in INSPECTION_CHARTS.items()], grid_columns=4),
            row_shares=[3, 2]),
        rrb.TopPanel(state="hidden"), rrb.BlueprintPanel(state="hidden"), rrb.SelectionPanel(state="hidden"),
        rrb.TimePanel(state="collapsed", timeline=TIMELINE, play_state="paused"),
        collapse_panels=False)
    rec.send_blueprint(blueprint, make_active=True, make_default=True)
    rec.flush()
    rec.disconnect()
    return {"fail_t": fail_t, "reason": result["reason"], "duration": float(t[-1]),
            "checks": {"foot_slip_mean": float(slip[in_contact].mean()), "judge_foot_slip": result["foot_slip_mps"],
                       "deviation_max_before_fall": float(deviation[:i - 1].max()), "judge_deviation_max": result["deviation_max_m"]}}


# Two runs of one world, before and after a controller change


def export_compare(out):
    before = json.loads((BEFORE_RUN / "result.json").read_text())
    after = json.loads((AFTER_RUN / "result.json").read_text())
    if before["world_sha256"] != after["world_sha256"] or before["seed"] != after["seed"]:
        raise SystemExit("These two runs are not the same world and seed.")
    source = (BEFORE_RUN / "qpos.json.gz").read_bytes() + (AFTER_RUN / "qpos.json.gz").read_bytes()
    rec = stream("crashlab_compare", source, "SIMULATED compare, one world, before and after a controller change")
    rec.save(out)
    a = log_window_run(rec, BEFORE_RUN, "before/", RED, "before")
    b = log_window_run(rec, AFTER_RUN, "after/", BLUE, "after")
    patch = (COMPARE_DIR / "try_2/patch.diff").read_text()
    rec.log("patch", rr.TextDocument(f"# Code change\n\nBefore: {a['reason']}\n\nAfter: {b['reason']}\n\n```diff\n{patch}\n```", media_type="text/markdown"), static=True)
    x, y, z = a["end"]
    view = lambda name, root: rrb.Spatial3DView(name=name, origin=f"/{root}/world", line_grid=rrb.LineGrid3D(visible=False), background=[28, 30, 34],
                                                eye_controls=rrb.EyeControls3D(position=[x + 0.6, y - 3.8, z + 0.7], look_target=[x, y, z - 0.3], eye_up=[0, 0, 1]))
    charts = [rrb.TimeSeriesView(name=title, contents=[f"/before/signals/{key}/**", f"/after/signals/{key}/**"], axis_x=whole_run(max(a["duration"], b["duration"])), plot_legend=rrb.PlotLegend(visible=False)) for key, title in WINDOW_CHARTS.items()]
    blueprint = rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(view("Before (simulated)", "before"), view("After (simulated)", "after"), rrb.TextDocumentView(name="Code change", origin="/patch"), column_shares=[2, 2, 1]),
            rrb.Grid(*charts, grid_columns=3),
            row_shares=[3, 2]),
        rrb.TopPanel(state="hidden"), rrb.BlueprintPanel(state="hidden"), rrb.SelectionPanel(state="hidden"),
        rrb.TimePanel(state="collapsed", timeline=TIMELINE, play_state="paused"),
        collapse_panels=False)
    rec.send_blueprint(blueprint, make_active=True, make_default=True)
    rec.flush()
    rec.disconnect()
    return {"fail_t": a["fail_t"], "before": a["reason"], "after": b["reason"], "duration": max(a["duration"], b["duration"]), "coverage": (before["coverage"], after["coverage"])}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--window-run")
    ap.add_argument("--inspection-run", nargs=2)
    ap.add_argument("--to")
    args = ap.parse_args()
    if args.to:
        if args.window_run:
            export_window(Path(args.to), Path(args.window_run).resolve())
        else:
            export_inspection(Path(args.to), *[Path(p).resolve() for p in args.inspection_run])
        sys.exit(0)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    infos = {"window": export_window(out / "window.rrd"), "inspection": export_inspection(out / "inspection.rrd"), "compare": export_compare(out / "compare.rrd")}
    summary = {k: {f: v[f] for f in ("fail_t", "duration", "reason", "checks", "before", "after", "coverage") if f in v} for k, v in infos.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    for name in infos:
        print(name, (out / f"{name}.rrd").stat().st_size)
