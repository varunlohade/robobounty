"""Small frames of a window run, from real state: a separate MuJoCo model of the same world, drawn by MuJoCo's offscreen Renderer. Picture only: it copies the state in and never writes to the sim."""
import gzip
import json

import mujoco
from PIL import Image

from . import pack as P

WIDTH, HEIGHT = 200, 150
FRAME_MARGIN = 1.3  # Camera distance per metre of the larger side of the work area.
AZIMUTH_DEG, ELEVATION_DEG = 90.0, -4.0


class Camera:
    def __init__(self, world):
        world = P.W.validate(world)
        self.m = mujoco.MjModel.from_xml_string(P.C.compile(world)[1])
        self.d = mujoco.MjData(self.m)
        self.renderer = mujoco.Renderer(self.m, HEIGHT, WIDTH)
        a = P.W.area_rect(world)
        self.view = mujoco.MjvCamera()
        self.view.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.view.lookat[:] = [(a["x0"] + a["x1"]) / 2, 0.0, (a["z0"] + a["z1"]) / 2]
        self.view.distance, self.view.azimuth, self.view.elevation = FRAME_MARGIN * max(a["x1"] - a["x0"], a["z1"] - a["z0"]), AZIMUTH_DEG, ELEVATION_DEG

    def _draw(self, qpos, mocap):
        self.d.qpos[:] = qpos
        if self.m.nmocap and mocap is not None:
            self.d.mocap_pos[:] = mocap
        mujoco.mj_kinematics(self.m, self.d)
        self.renderer.update_scene(self.d, camera=self.view)
        return Image.fromarray(self.renderer.render())

    def live(self, sim_data):
        return self._draw(sim_data.qpos, sim_data.mocap_pos)

    def film(self, folder):
        """Evenly through the recorded run, with its last frame."""
        import pack_job
        with gzip.open(folder / "qpos.json.gz", "rt") as f:
            record = json.load(f)
        frames, mocap = record["frames"], record.get("mocap_frames")
        n = min(pack_job.FILM_FRAMES, len(frames))
        for i in range(n):
            at = round(i * (len(frames) - 1) / max(1, n - 1))
            yield self._draw(frames[at], mocap[min(at, len(mocap) - 1)] if mocap else None)
