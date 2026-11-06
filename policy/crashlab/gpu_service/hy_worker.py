"""Image to textured GLB on the pod, under venv-hy: one JSON request per stdin line, one JSON reply per stdout line. Stage lines come first, each with "stage"."""
import json
import os
import sys
import time
import traceback

OUT = sys.stdout
sys.stdout = sys.stderr  # imports and pipelines print freely. The reply stream stays clean.
REPO = "/workspace/t3d/Hunyuan3D-2.1"
os.chdir(REPO)
sys.path[:0] = [f"{REPO}/hy3dshape", f"{REPO}/hy3dpaint", REPO]
import types

sys.modules["bpy"] = types.ModuleType("bpy")  # mesh_utils imports it at load, for a conversion this worker does not call. PyPI has no bpy for Python 3.10.
from torchvision_fix import apply_fix  # the repo's own fix for torchvision's moved module

apply_fix()
import torch
from PIL import Image
from rembg import new_session, remove
from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
from convert_utils import create_glb_with_pbr_materials
from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
import pymeshlab

MODES = {"quality": {"steps": 50, "octree": 512, "faces": 150000, "views": 9, "view_res": 768}}


def say(row):
    OUT.write(json.dumps(row) + "\n")
    OUT.flush()


def decimated(source, target, faces):
    """The repo's own step needs open3d and caps at 40,000 faces. This keeps more of the shape's detail for the paint step."""
    meshes = pymeshlab.MeshSet()
    meshes.load_new_mesh(source)
    if meshes.current_mesh().face_number() > faces:
        meshes.meshing_decimation_quadric_edge_collapse(targetfacenum=faces, preservenormal=True, planarquadric=True, autoclean=True)
    meshes.save_current_mesh(target, save_textures=False)


def main():
    shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained("tencent/Hunyuan3D-2.1")
    conf = Hunyuan3DPaintConfig(MODES["quality"]["views"], MODES["quality"]["view_res"])
    conf.realesrgan_ckpt_path = f"{REPO}/hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
    conf.multiview_cfg_path = f"{REPO}/hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
    conf.custom_pipeline = f"{REPO}/hy3dpaint/hunyuanpaintpbr"
    paint = Hunyuan3DPaintPipeline(conf)
    cutter = new_session("birefnet-general")
    say({"ready": True})
    for line in sys.stdin:
        req = json.loads(line)
        try:
            job(req, shape, paint, cutter)
        except Exception as error:  # one bad object fails its job, and the loaded models stay
            traceback.print_exc()
            say({"error": type(error).__name__})


def job(req, shape, paint, cutter):
    folder = req["folder"]
    mode = MODES[req["mode"]]
    torch.cuda.reset_peak_memory_stats()
    started = mark = time.time()
    timing = {}

    def lap(name):
        nonlocal mark
        timing[name] = round(time.time() - mark, 1)
        mark = time.time()

    cut = remove(Image.open(f"{folder}/image.png").convert("RGB"), session=cutter)
    cut.save(f"{folder}/cut.png")
    lap("cut_out")
    say({"stage": "shape"})
    mesh = shape(image=cut, num_inference_steps=mode["steps"], octree_resolution=mode["octree"], guidance_scale=5.0, num_chunks=200000,
                 generator=torch.Generator("cuda").manual_seed(req["seed"]), output_type="trimesh")[0]
    mesh.export(f"{folder}/white.glb")
    lap("shape")
    say({"stage": "paint"})
    torch.cuda.empty_cache()
    decimated(f"{folder}/white.glb", f"{folder}/white_remesh.obj", mode["faces"])
    lap("decimate")
    paint.config.max_selected_view_num = mode["views"]
    paint.config.resolution = mode["view_res"]
    paint(mesh_path=f"{folder}/white_remesh.obj", image_path=cut, output_mesh_path=f"{folder}/textured.obj", use_remesh=False, save_glb=False)
    create_glb_with_pbr_materials(f"{folder}/textured.obj", {"albedo": f"{folder}/textured.jpg", "metallic": f"{folder}/textured_metallic.jpg", "roughness": f"{folder}/textured_roughness.jpg"}, f"{folder}/textured.glb")
    lap("texture")
    peak = round(torch.cuda.max_memory_reserved() / 2**30, 1)
    torch.cuda.empty_cache()  # gives the VRAM back between jobs, for other work on this card
    say({"seconds": round(time.time() - started, 1), "timing": timing, "faces": len(mesh.faces), "peak_gb": peak})


if __name__ == "__main__":
    main()
