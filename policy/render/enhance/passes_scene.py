"""Blender side of the pass export. Run through export_passes.py, not directly.

Builds the same geometry and camera as scene.py, with one flat shader on everything. Each frame's EXR holds
depth along the view axis in metres (R) and an object label (G). No lights, blur or depth of field."""
import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

RENDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RENDER_DIR))
import scene  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402

LABELS = {"sky_city": 0, "robot": 1, "glass": 2, "tether": 3, "frame": 4, "tower": 5}
TOWER = {"tower_sides", "corners", "parapet"}
FRAME = {"frame", "seal"}


def label_of(name):
    if name.startswith("robot"):
        return LABELS["robot"]
    if name == "glass":
        return LABELS["glass"]
    if name == "tether":
        return LABELS["tether"]
    if name in FRAME:
        return LABELS["frame"]
    if name in TOWER:
        return LABELS["tower"]
    return LABELS["sky_city"]


def pass_material():
    m = bpy.data.materials.new("pass")
    m.use_nodes = True
    t = m.node_tree
    t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    emit = t.nodes.new("ShaderNodeEmission")
    join = t.nodes.new("ShaderNodeCombineColor")
    cam = t.nodes.new("ShaderNodeCameraData")
    info = t.nodes.new("ShaderNodeObjectInfo")
    t.links.new(cam.outputs["View Z Depth"], join.inputs[0])
    t.links.new(info.outputs["Object Index"], join.inputs[1])
    t.links.new(join.outputs[0], emit.inputs["Color"])
    t.links.new(emit.outputs[0], out.inputs["Surface"])
    return m


def setup_render(args):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.device = "GPU"
    sc.cycles.samples = 1
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = False
    sc.cycles.max_bounces = 0
    sc.cycles.pixel_filter_type = "BOX"
    sc.cycles.filter_width = 0.01  # One ray per pixel, so a pixel holds one label, never a blend.
    sc.cycles.seed = 1
    w, h = args.res.split("x")
    sc.render.resolution_x, sc.render.resolution_y = int(w), int(h)
    sc.render.resolution_percentage = 100
    sc.render.use_motion_blur = False
    sc.render.use_persistent_data = True
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "32"
    sc.render.image_settings.exr_codec = "ZIP"
    sc.view_settings.view_transform = "Raw"
    sc.view_settings.look = "None"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", required=True)
    ap.add_argument("--shot", required=True)
    ap.add_argument("--poses", required=True, help="the clip's pose log; camera and robot must match it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--start-frame", type=int, default=0)
    ap.add_argument("--end-frame", type=int, default=None)
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = scene.run_data.Run(a.trial)
    shot = scene.shot_list.SHOTS[a.shot]
    logged = json.loads(Path(a.poses).read_text())
    t0 = shot["t"]
    n = int(round(shot["seconds"] * a.fps))
    if len(logged) != n:
        raise SystemExit(f"pose log has {len(logged)} frames, shot has {n}")

    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    setup_render(a)
    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    sc.world = world

    mat = pass_material()
    haze, focus = scene.shot_list.HAZE, (0.0, 0.0, run.area["z1"])
    scene.build_glass(run, mat)
    scene.build_frame(run, mat, mat)
    scene.build_tower_body(run, mat, mat, mat)
    scene.city_gen.build(run, haze, focus, scene.N, scene.out, scene.new_mat)
    robot, tether, boot_z = scene.build_robot(run)
    for ob in bpy.data.objects:
        ob.pass_index = label_of(ob.name)
    bpy.context.view_layer.material_override = mat

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    r0, r1 = np.array(run.pose(t0)[0]), np.array(run.pose(t0 + (n - 1) / a.fps)[0])
    rows = []
    end = a.end_frame if a.end_frame is not None else n
    for fi in range(a.start_frame, end):
        t = t0 + fi / a.fps
        pos, quat = run.pose(t)
        robot.location, robot.rotation_quaternion = pos, quat
        q = Quaternion(quat)
        tp = Vector(pos) + q @ Vector((0, 0, boot_z))
        d = Vector(run.anchor) - tp
        tether.location = tp
        tether.rotation_quaternion = d.to_track_quat("Z", "Y")
        tether.scale = (run.tether_radius, run.tether_radius, d.length)

        camp = scene.shot_list.camera_at(shot, fi / max(n - 1, 1), r0, r1, np.array(pos))
        scene.place_camera(cam, camp["pos"], camp["target"], camp["lens"], camp["focus"], camp["fstop"], camp.get("roll", 0.0))
        cam.data.dof.use_dof = False
        bpy.context.view_layer.update()

        lg = logged[fi]
        cam_err = float(np.linalg.norm(np.array(cam.location) - np.array(lg["cam"])))
        pose_err = float(np.linalg.norm(np.array(pos) - np.array(lg["robot_loc"])))
        if cam_err > 1e-4 or pose_err > 1e-4 or abs(cam.data.lens - lg["lens"]) > 1e-3:
            raise SystemExit(f"frame {fi}: camera or pose differs from the clip's log: cam {cam_err}, pose {pose_err}, lens {cam.data.lens} vs {lg['lens']}")

        sc.render.filepath = str(out_dir / ("frame_%04d.exr" % fi))
        bpy.ops.render.render(write_still=True)
        px = world_to_camera_view(sc, cam, robot.matrix_world.translation)
        rows.append({"frame": fi, "t": t, "robot_world": list(pos), "cam_matrix": [list(r) for r in cam.matrix_world],
                     "lens_mm": cam.data.lens, "sensor_mm": cam.data.sensor_width, "screen": [px.x, px.y, px.z]})
        print("frame %d" % fi, flush=True)
        (out_dir / ("cameras_%04d_%04d.json" % (a.start_frame, end))).write_text(json.dumps(rows))


if __name__ == "__main__":
    main()
