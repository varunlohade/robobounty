"""Replays a record through Newton's raytraced SensorCamera on the CPU, to an mp4 and a still. No window and no GPU.

The picture comes only from the recorded body poses and the world in the record. Every frame says "simulated".
Usage from policy/: python -m packs.inspection.render <record.npz> <out.mp4> [--still T]
"""
import argparse
import pathlib
import subprocess
import tempfile

import numpy as np
import warp as wp
from PIL import Image, ImageDraw, ImageFont

from newton.sensors import SensorCamera
from newton._src.sensors.sensor_camera_render.types import LightType
from newton._src.sensors.sensor_camera_render.types import TextureData

from . import judge as J
from . import model as M
from . import sim as S
from . import world as W

MAX_LIGHTS = 6
ROBOT_PAINT = 0.24


def _fill_holes(rgb, normals):
    """Newton's raytracer returns a zero normal on some far box pixels, and these show as dark specks. Each takes the mean of its neighbours that have a normal."""
    holes = np.abs(normals).sum(axis=2) == 0.0
    out = rgb.astype(np.float32)
    for _ in range(4):
        if not holes.any():
            break
        total = np.zeros_like(out)
        count = np.zeros(holes.shape, dtype=np.float32)
        for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            good = np.roll(~holes, (dy, dx), axis=(0, 1))
            total += np.roll(out, (dy, dx), axis=(0, 1)) * good[..., None]
            count += good
        fill = holes & (count > 0)
        out[fill] = total[fill] / count[fill][:, None]
        holes = holes & ~fill
    return out.astype(np.uint8)


def _look_at(eye, at):
    forward = np.asarray(at, dtype=float) - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, (0.0, 0.0, 1.0))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    m = wp.mat33(right[0], up[0], -forward[0], right[1], up[1], -forward[1], right[2], up[2], -forward[2])
    return wp.transformf(wp.vec3f(*eye), wp.quat_from_matrix(m))


def _chase_xy(xy, window):
    kernel = np.ones(window) / window
    pad = np.pad(xy, ((window // 2, window - 1 - window // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, i], kernel, mode="valid") for i in range(2)], axis=1)


def _concrete():
    """A 12 m floor tile: power-floated concrete with slab joints every 3 m, tyre marks and stains. One RGBA byte array, picture only."""
    size = 2048
    rng = np.random.default_rng(7)
    field = np.zeros((size, size))
    for cells, weight in ((6, 0.05), (24, 0.05), (96, 0.03), (384, 0.025)):
        coarse = rng.normal(size=(cells, cells))
        image = Image.fromarray(coarse.astype(np.float32), mode="F").resize((size, size), Image.BICUBIC)
        field += weight * np.asarray(image)
    grit = rng.normal(size=(size, size)) * 0.018
    shade = 0.92 + field + grit
    for k in range(4):
        slab = (size * k) // 4
        offset = rng.uniform(-0.03, 0.03)
        shade[slab:slab + size // 4] += offset
    joint = size // 4
    width = 3
    for k in range(4):
        shade[max(joint * k - width, 0):joint * k + width, :] *= 0.32
        shade[:, max(joint * k - width, 0):joint * k + width] *= 0.32
    return _bytes(np.stack([shade * 1.0, shade * 0.985, shade * 0.95], axis=2))


def _grime():
    """Streaks that run down a surface, for painted steel and concrete."""
    size = 512
    rng = np.random.default_rng(11)
    streak = np.asarray(Image.fromarray(rng.normal(size=(8, 96)).astype(np.float32), mode="F").resize((size, size), Image.BICUBIC))
    blotch = np.asarray(Image.fromarray(rng.normal(size=(12, 12)).astype(np.float32), mode="F").resize((size, size), Image.BICUBIC))
    shade = 0.9 + 0.05 * streak + 0.05 * blotch
    return _bytes(np.stack([shade] * 3, axis=2))


def _sheet():
    """Profiled wall cladding: ribs every 0.3 m in a 1.2 m tile, with vertical streaks."""
    size = 512
    u = np.arange(size) / size * 4.0
    rib = 0.93 + 0.07 * np.clip(np.cos(2.0 * np.pi * u) * 2.5, -1.0, 1.0)
    rng = np.random.default_rng(13)
    streak = np.asarray(Image.fromarray(rng.normal(size=(4, 48)).astype(np.float32), mode="F").resize((size, size), Image.BICUBIC))
    shade = rib[None, :] + 0.04 * streak
    return _bytes(np.stack([shade] * 3, axis=2))


def _bytes(rgb):
    rgba = np.concatenate([np.clip(rgb, 0.0, 1.0), np.ones((*rgb.shape[:2], 1))], axis=2)
    return (rgba * 255.0).astype(np.uint8)


def _texture(pixels, metres, device):
    data = TextureData()
    data.texture = wp.Texture2D(pixels, filter_mode=wp.TextureFilterMode.LINEAR, address_mode=wp.TextureAddressMode.WRAP, normalized_coords=True, dtype=wp.uint8, num_channels=4, device=device)
    data.repeat = wp.vec2f(1.0 / metres, 1.0 / metres)
    return data


def _dress(camera, model, world):
    """Sets textures and lights through private fields of Newton's camera: its public call offers only a checkerboard and one light. Picture only, no effect on the physics."""
    context = camera._render_context
    table = [_texture(_concrete(), 12.0, model.device), _texture(_grime(), 2.5, model.device), _texture(_sheet(), 1.2, model.device)]
    context._texture_data_source = table
    context._texture_data = wp.array(table, dtype=TextureData, device=model.device)
    ids = np.full(model.shape_count, -1, dtype=np.int32)
    for i, label in enumerate(model.shape_label):
        if label.endswith("ground"):
            ids[i] = 0
        elif "#" in label:
            texture = W.TEXTURED.get(label.rsplit("#", 1)[1])
            if texture:
                ids[i] = {"grime": 1, "sheet": 2}[texture]
    context._shape_texture_ids = wp.array(ids, dtype=wp.int32, device=model.device)
    # Upstream's meshes are near white, and blow out under the hall lights. Scale them to grey paint.
    colours = model.shape_color.numpy()
    robot = np.array([label.startswith("/anymal") for label in model.shape_label])
    colours[robot] *= ROBOT_PAINT
    model.shape_color.assign(colours)
    points = W.lights(world)[:MAX_LIGHTS]
    # Roof glazing casts the shadows, straight down, because a slanted light speckles the walls in this renderer. A second directional light with no shadow stands in for light that bounces around the hall. Then the high-bay lights.
    count = len(points) + 2
    context._lights_active = wp.array([True] * count, dtype=wp.bool, device=model.device)
    context._lights_type = wp.array([LightType.DIRECTIONAL, LightType.DIRECTIONAL] + [LightType.SPOTLIGHT] * len(points), dtype=wp.int32, device=model.device)
    context._lights_cast_shadow = wp.array([True, False] + [False] * len(points), dtype=wp.bool, device=model.device)
    context._lights_position = wp.array([wp.vec3f(0.0), wp.vec3f(0.0)] + [wp.vec3f(*p) for p in points], dtype=wp.vec3f, device=model.device)
    context._lights_orientation = wp.array([wp.vec3f(0.0, 0.0, -1.0), wp.normalize(wp.vec3f(0.5, 0.7, -0.5))] + [wp.vec3f(0.0, 0.0, -1.0)] * len(points), dtype=wp.vec3f, device=model.device)


def render(path, out, *, title="", width=960, height=540, stride=4, stills=()):
    rec, meta = S.load(path)
    model, _ = M.load_model(meta["world"], picture=True)
    state = model.state()
    camera = SensorCamera(model)
    _dress(camera, model, meta["world"])
    camera.default_render_config.enable_shadows = True
    camera.default_render_config.enable_textures = True
    camera.default_clear_data = SensorCamera.ClearData(clear_color=0xFF23211F, clear_albedo=0xFF000000)
    rays = SensorCamera.compute_camera_rays_pinhole(width, height, camera_fov=np.radians(45.0), device=model.device)
    image = camera.allocate_image_color(1, width, height)
    normals = camera.allocate_image_normal(1, width, height)
    transforms = wp.empty(1, dtype=wp.transformf, device=model.device)
    chase = _chase_xy(rec["base_q"][:, :2], 75)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = J.judge(rec, meta["world"])
    dt = float(rec["t"][1] - rec["t"][0])
    still_at = {int(round(t / (dt * stride))): t for t in stills}
    with tempfile.TemporaryDirectory() as tmp:
        for n, i in enumerate(range(0, len(rec["t"]), stride)):
            state.body_q.assign(rec["body_q"][i])
            model.bvh_refit_shapes(state)
            eye = np.array([chase[i, 0] - 2.2, chase[i, 1] - 4.0, 2.7])
            transforms.assign([_look_at(eye, (chase[i, 0] + 0.2, chase[i, 1] + 0.5, 0.55))])
            camera.update(state, transforms, rays, color_image=image, normal_image=normals)
            rgba = image.numpy()[0].view(np.uint8).reshape(height, width, 4)
            frame = Image.fromarray(_fill_holes(rgba[..., :3], normals.numpy()[0].reshape(height, width, 3)))
            draw = ImageDraw.Draw(frame)
            draw.rectangle((0, 0, width, 30), fill=(20, 20, 20))
            draw.text((10, 5), f"SIMULATED  ANYmal C, upstream policy  {title}  t={rec['t'][i]:.1f}s  run: {result['verdict']}", fill=(240, 240, 240), font=font)
            frame.save(f"{tmp}/f{n:05d}.png")
            if n in still_at:
                frame.save(out.with_name(f"{out.stem}-t{still_at[n]:g}.png"))
        fps = round(1.0 / (dt * stride))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{tmp}/f%05d.png", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", str(out)], check=True)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("record")
    parser.add_argument("out")
    parser.add_argument("--title", default="")
    parser.add_argument("--stills", type=float, nargs="*", default=())
    args = parser.parse_args()
    print(render(args.record, args.out, title=args.title, stills=args.stills))
