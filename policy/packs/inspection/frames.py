"""Small frames of an inspection run, from real state: a separate picture model of the same world, drawn by Newton's CPU camera with the pack's own look. Picture only: it reads the state and never writes to the sim."""
import numpy as np
import warp as wp
from PIL import Image

import newton
from newton.sensors import SensorCamera

import pack_job

from . import model as M
from . import render as R

WIDTH, HEIGHT = 200, 150
CHASE_WINDOW = 75
FOV_DEG = 45.0


class Camera:
    def __init__(self, world):
        self.model, _ = M.load_model(world, picture=True)
        self.state = self.model.state()
        self.camera = SensorCamera(self.model)
        R._dress(self.camera, self.model, world)
        self.camera.default_render_config.enable_shadows = True
        self.camera.default_render_config.enable_textures = True
        self.camera.default_clear_data = SensorCamera.ClearData(clear_color=0xFF23211F, clear_albedo=0xFF000000)
        device = self.model.device
        self.rays = SensorCamera.compute_camera_rays_pinhole(WIDTH, HEIGHT, camera_fov=np.radians(FOV_DEG), device=device)
        self.image = self.camera.allocate_image_color(1, WIDTH, HEIGHT)
        self.normals = self.camera.allocate_image_normal(1, WIDTH, HEIGHT)
        self.at = wp.empty(1, dtype=wp.transformf, device=device)
        self.fk_q, self.fk_qd = wp.clone(self.state.joint_q), wp.clone(self.state.joint_qd)

    def _draw(self, x, y):
        self.model.bvh_refit_shapes(self.state)
        self.at.assign([R._look_at(np.array([x - 2.2, y - 4.0, 2.7]), (x + 0.2, y + 0.5, 0.55))])
        self.camera.update(self.state, self.at, self.rays, color_image=self.image, normal_image=self.normals)
        rgba = self.image.numpy()[0].view(np.uint8).reshape(HEIGHT, WIDTH, 4)
        return Image.fromarray(R._fill_holes(rgba[..., :3], self.normals.numpy()[0].reshape(HEIGHT, WIDTH, 3)))

    def live(self, q, qd):
        self.fk_q.assign(q)
        self.fk_qd.assign(qd)
        newton.eval_fk(self.model, self.fk_q, self.fk_qd, self.state)
        return self._draw(float(q[0]), float(q[1]))

    def film(self, rec):
        """Evenly through the recorded run, with its last frame."""
        count = len(rec["t"])
        chase = R._chase_xy(rec["base_q"][:, :2], CHASE_WINDOW)
        n = min(pack_job.FILM_FRAMES, count)
        for i in range(n):
            at = round(i * (count - 1) / max(1, n - 1))
            self.state.body_q.assign(rec["body_q"][at])
            yield self._draw(float(chase[at, 0]), float(chase[at, 1]))
