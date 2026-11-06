"""Replays a recorded run through Newton's raytraced SensorCamera on the CPU, with no window and no GPU, to frames and an mp4.

The picture comes only from the recorded body poses and the world in the record. Every frame says "simulated".
"""
import argparse
import pathlib
import subprocess
import tempfile

import numpy as np
import warp as wp
from PIL import Image, ImageDraw, ImageFont

from newton.sensors import SensorCamera

import judge as J
import sim as S


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


def render(path, out, *, width=960, height=540, stride=2, stills=()):
    rec, meta = J.load(path)
    model, _ = S.build_model(meta["world"], surface_priority=1)
    labels = model.shape_label
    ground = np.array([i for i, lb in enumerate(labels) if lb.endswith("ground")], dtype=np.uint32)
    state = model.state()
    camera = SensorCamera(model)
    camera.create_default_light(enable_shadows=True, direction=wp.normalize(wp.vec3f(-0.4, 0.5, -1.0)))
    camera.assign_checkerboard_material(shape_indices=ground)
    camera.default_render_config.enable_shadows = True
    camera.default_render_config.enable_textures = True
    camera.default_clear_data = SensorCamera.ClearData(clear_color=0xFFD8CFC4, clear_albedo=0xFF000000)
    rays = SensorCamera.compute_camera_rays_pinhole(width, height, camera_fov=np.radians(40.0), device=model.device)
    image = camera.allocate_image_color(1, width, height)
    transforms = wp.empty(1, dtype=wp.transformf, device=model.device)
    chase = _chase_xy(rec["base_q"][:, :2], 51)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    verdict = J.judge(rec, meta["world"]["target"])["verdict"]
    stills = {int(round(t / (float(rec["t"][1] - rec["t"][0]) * stride))): t for t in stills}
    with tempfile.TemporaryDirectory() as tmp:
        for n, i in enumerate(range(0, len(rec["t"]), stride)):
            state.body_q.assign(rec["body_q"][i])
            model.bvh_refit_shapes(state)
            eye = np.array([chase[i, 0] - 1.2, chase[i, 1] - 3.6, 1.5])
            transforms.assign([_look_at(eye, (chase[i, 0] + 0.2, chase[i, 1], 0.25))])
            camera.update(state, transforms, rays, color_image=image)
            rgba = image.numpy()[0].view(np.uint8).reshape(height, width, 4)
            frame = Image.fromarray(rgba[..., :3].copy())
            draw = ImageDraw.Draw(frame)
            force = rec["obstacle_f"][: i + 1].max()
            text = f"SIMULATED  go2 upstream policy  t={rec['t'][i]:.2f}s  x={rec['base_q'][i, 0]:.2f}m  peak obstacle force={force:.0f}N  run: {verdict}"
            draw.rectangle((0, 0, width, 32), fill=(20, 20, 20))
            draw.text((10, 5), text, fill=(240, 240, 240), font=font)
            frame.save(f"{tmp}/f{n:05d}.png")
            if n in stills:
                frame.save(out.with_name(f"{out.stem}-t{stills[n]:g}.png"))
        fps = round(1.0 / (float(rec["t"][1] - rec["t"][0]) * stride))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{tmp}/f%05d.png", "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-crf", "24", str(out)], check=True)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("record")
    parser.add_argument("out")
    parser.add_argument("--stills", type=float, nargs="*", default=())
    args = parser.parse_args()
    print(render(args.record, args.out, stills=args.stills))
