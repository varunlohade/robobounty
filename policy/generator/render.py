"""Stills of gated scenes and sheets. render.py stills <scene out label>... | preview <run dir> <out> | sheet <out> <title> <png label>...

Offscreen only. It uses the free cameras of policy/highrise/preview.py plus one far view of the whole facade. It is not a Blender render.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "cgl")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from PIL import Image, ImageDraw

W_PX, H_PX = 640, 480


def still(scene_path, out, label):
    import mujoco
    import scene_sim as X
    merged = X.merge(X.G.check(Path(scene_path).read_bytes()), X.base_world())
    m = mujoco.MjModel.from_xml_string(merged)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    m.vis.global_.offwidth, m.vis.global_.offheight = W_PX, H_PX
    m.vis.map.zfar = 2000.0
    r = mujoco.Renderer(m, H_PX, W_PX, max_geom=6000)
    r.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
    r.scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = 0
    views = (((1.2, -0.1, 136.7), 6.0, 104, -12), ((1.2, -0.5, 136.7), 25.0, 130, -15), ((1.2, 0.0, 80.0), 210.0, 120, -8))
    sheet = Image.new("RGB", (W_PX * 3, H_PX + 24), (20, 20, 20))
    for i, (look, dist, az, el) in enumerate(views):
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = look
        cam.distance, cam.azimuth, cam.elevation = dist, az, el
        r.update_scene(d, cam)
        sheet.paste(Image.fromarray(r.render()), (i * W_PX, 24))
    ImageDraw.Draw(sheet).text((6, 6), label, fill=(255, 255, 255))
    sheet.save(out)


def contact_sheet(out, title, items):
    cols = 3
    cell_w, cell_h = 640, 170
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, 28 + (cell_h + 22) * rows), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title, fill=(0, 0, 0))
    for n, (png, label) in enumerate(items):
        x, y = (n % cols) * cell_w, 28 + (n // cols) * (cell_h + 22)
        draw.text((x + 6, y + 4), label, fill=(0, 0, 0))
        if png and Path(png).exists():
            im = Image.open(png)
            im = im.crop((0, 24, im.width, im.height))
            sheet.paste(im.resize((cell_w - 6, cell_h)), (x + 3, y + 20))
        else:
            draw.rectangle((x + 3, y + 20, x + cell_w - 3, y + 20 + cell_h), fill=(225, 225, 225))
            draw.text((x + 20, y + 80), "no valid scene", fill=(120, 0, 0))
    sheet.save(out)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "stills":
        a = sys.argv[2:]
        for i in range(0, len(a), 3):
            still(a[i], a[i + 1], a[i + 2])
    elif cmd == "preview":
        import scene_sim as X
        run = Path(sys.argv[2])
        X.install((run / "scene.xml").read_bytes())
        sys.path.insert(0, str(HERE.parent / "highrise"))
        import preview
        sys.argv = ["preview.py", str(run), sys.argv[3]]
        preview.main()
    elif cmd == "sheet":
        a = sys.argv[4:]
        contact_sheet(sys.argv[2], sys.argv[3], [(a[i] if a[i] != "-" else None, a[i + 1]) for i in range(0, len(a), 2)])
