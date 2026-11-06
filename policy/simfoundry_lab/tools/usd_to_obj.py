"""Writes NVIDIA's published SimFoundry example scene (droid_desk_serve_fruits) out of USD as OBJ and PNG, plus a manifest with masses and poses from the files."""
import glob, json, sys, zipfile, io
from pathlib import Path
import numpy as np
from PIL import Image
from pxr import Usd, UsdGeom, UsdPhysics
Image.MAX_IMAGE_PIXELS = None

ROOT = Path("work/hf/assets/assets")
SCENE = ROOT / "scenes/DROID/droid_desk_serve_fruits"
OUT = Path("work/scene")
TEX = 2048

def write_obj(path, pts, faces, uv=None):
    with open(path, "w") as f:
        f.write(f"mtllib none\n")
        np.savetxt(f, pts, fmt="v %.6f %.6f %.6f")
        if uv is not None:
            np.savetxt(f, uv, fmt="vt %.6f %.6f")
            np.savetxt(f, np.repeat(faces + 1, 2, axis=1)[:, [0, 1, 2, 3, 4, 5]], fmt="f %d/%d %d/%d %d/%d")
        else:
            np.savetxt(f, faces + 1, fmt="f %d %d %d")

def mesh_tris(prim):
    m = UsdGeom.Mesh(prim)
    pts = np.array(m.GetPointsAttr().Get(), dtype=np.float64)
    counts = np.array(m.GetFaceVertexCountsAttr().Get())
    idx = np.array(m.GetFaceVertexIndicesAttr().Get())
    assert (counts == 3).all(), "non-triangle mesh"
    return pts, idx.reshape(-1, 3), m

def uv_of(m, tris):
    pv = UsdGeom.PrimvarsAPI(m.GetPrim()).GetPrimvar("st")
    uv = np.array(pv.Get(), dtype=np.float64)
    interp = pv.GetInterpolation()
    ix = pv.GetIndices()
    if ix: uv = uv[np.array(ix)]
    return uv, interp

state = json.load(open(SCENE / "droid_desk_serve_fruits_scene_state_latest.json"))
reg = state["state"]["registry"]["object_registry"]
info = state["objects_info"]["init_info"]
manifest = {"ground_z": state["ground_plane_info"]["position"][2], "objects": []}
for name, spec in info.items():
    if spec["class_name"] != "USDObject" or name.startswith("mesh_background"):
        continue
    usd = SCENE / spec["args"]["usd_path"]
    stage = Usd.Stage.Open(str(usd))
    link = next(p for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI))
    mass = UsdPhysics.MassAPI(link)
    vis = next(p for p in stage.Traverse() if p.GetTypeName() == "Mesh" and "/visuals/" in str(p.GetPath()) and str(p.GetPath()).startswith(str(link.GetPath())))
    pts, tris, m = mesh_tris(vis)
    uv, interp = uv_of(m, tris)
    if interp == "faceVarying":
        pts = pts[tris.reshape(-1)]
        tris = np.arange(len(pts)).reshape(-1, 3)
    uv = uv.copy(); uv[:, 1] = uv[:, 1]
    d = OUT / name; d.mkdir(parents=True, exist_ok=True)
    write_obj(d / "visual.obj", pts, tris, uv)
    img = Image.open(next(usd.parent.parent.glob("material/material_0.png"))).convert("RGB")
    img.thumbnail((TEX, TEX)); img.save(d / "tex.png")
    cols = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI)]
    hull_names = []
    for i, c in enumerate(cols):
        cp, ct, _ = mesh_tris(c)
        cx = np.array(UsdGeom.Xformable(c).ComputeLocalToWorldTransform(0))
        cp = cp @ cx[:3, :3] + cx[3, :3]
        write_obj(d / f"hull_{i}.obj", cp, ct); hull_names.append(f"hull_{i}.obj")
    pose = reg[name]["root_link"]
    manifest["objects"].append(dict(name=name, category=spec["args"]["category"], pos=pose["pos"], ori_xyzw=pose["ori"],
        mass=float(mass.GetMassAttr().Get()), com=[float(x) for x in mass.GetCenterOfMassAttr().Get()],
        hulls=hull_names, size=(pts.max(0) - pts.min(0)).tolist(), visual_tris=len(tris)))
    print(name, manifest["objects"][-1]["mass"], "kg", len(cols), "hulls", len(tris), "tris", flush=True)

bgp = ROOT / "backgrounds/mesh_backgrounds"
bgdoc = json.load(open(bgp / "droid_v1.background.json"))
stage = Usd.Stage.Open(str(bgp / "droid_v1.usdz"))
prim = next(p for p in stage.Traverse() if p.GetTypeName() == "Mesh")
pts, tris, m = mesh_tris(prim)
uv, interp = uv_of(m, tris)
if interp == "faceVarying":
    pts = pts[tris.reshape(-1)]; tris = np.arange(len(pts)).reshape(-1, 3)
xf = np.array(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0))
pts = pts @ xf[:3, :3] + xf[3, :3]
(OUT / "background").mkdir(exist_ok=True)
write_obj(OUT / "background/visual.obj", pts, tris, uv)
z = zipfile.ZipFile(bgp / "droid_v1.usdz")
tex = [n for n in z.namelist() if n.lower().endswith((".png", ".jpg", ".jpeg"))]
print("bg textures", tex, "any collision api:", any(p.HasAPI(UsdPhysics.CollisionAPI) for p in stage.Traverse()))
img = Image.open(io.BytesIO(z.read(tex[0]))).convert("RGB"); img.thumbnail((4096, 4096)); img.save(OUT / "background/tex.png")
manifest["background"] = dict(pos=reg["mesh_background_0"]["root_link"]["pos"], ori_xyzw=reg["mesh_background_0"]["root_link"]["ori"],
    source=stage.GetDefaultPrim().GetName(), centre_source=bgdoc["registration"]["support_surface"]["centre_source"], collision=False)
json.dump(manifest, open(OUT / "manifest.json", "w"), indent=1)
