"""The tracked crawler and the plate as MJCF. z up, hull plane at z = 0 facing down, so the robot hangs below it. Body frame: x forward, z toward the hull.

Each track is seven sprung contact rollers along its length, all driven at the track's speed. Skid steer comes from the difference between the two tracks. The picture draws the belt and shoes over these rollers.
Rollers and weld beads collide as capsules, so rolling contact stays analytic.
"""
import mujoco
import numpy as np

from . import world as W

ROLLERS = 7
ROLLER_R = 0.03
ROLLER_HALF_W = 0.03  # capsule half length; the track shoe is 0.09 m wide
TRACK_Y = 0.21  # half the gauge
TRACK_X = (-0.25, 0.10)  # rear and front contact points
ROLLER_XS = tuple(float(x) for x in np.linspace(TRACK_X[0], TRACK_X[1], ROLLERS))
AXLE_Z = 0.06
SPRING_K = 20000.0  # N/m per contact point, the belt and bogie compliance
SPRING_D = 300.0
SPRING_TRAVEL_M = 0.02
DRUM_X = 0.235
DRUM_Z = 0.032
DRUM_TIP_R = 0.07  # free bristle tips, 12 mm past the track face
DRUM_HALF_W = 0.23
CHASSIS_HALF = (0.20, 0.15, 0.05)  # skid box; its top is 40 mm off the plate
CHASSIS_CENTRE_X = -0.075
RIDE_Z = -(AXLE_Z + ROLLER_R)
CHASSIS_KG = 19.0
ROLLER_KG = 0.25  # a share of the track's mass
DRUM_KG = 2.5
VOLUME_M3 = 0.0135
BUOY_LOCAL = (-0.05, 0.0, 0.02)
SEAM_R = 0.04  # bead cross-section radius
TIMESTEP = 0.002
LEFT = tuple(f"roller_l{i}" for i in range(ROLLERS))
RIGHT = tuple(f"roller_r{i}" for i in range(ROLLERS))
DRUM = "drum"
BODIES = ("chassis", *LEFT, *RIGHT, DRUM)


def seams(world):
    """Weld beads as (name, centre, half length, axis). Beads protrude height_m below the plate."""
    h = world["seam"]["height_m"]
    if h <= 0:
        return []
    z = SEAM_R - h
    x0, x1 = W.PLATE_X
    y0, y1 = W.PLATE_Y
    out = [(f"seam_t{i}", (x, (y0 + y1) / 2, z), (y1 - y0) / 2, "y") for i, x in enumerate(W.TRANSVERSE_SEAMS_X)]
    out += [(f"seam_l{i}", ((x0 + x1) / 2, y, z), (x1 - x0) / 2, "x") for i, y in enumerate(W.LONGITUDINAL_SEAMS_Y)]
    return out


def _xml(world, start):
    import math
    cur = world["current"]
    wx, wy = cur["speed_ms"] * math.cos(math.radians(cur["dir_deg"])), cur["speed_ms"] * math.sin(math.radians(cur["dir_deg"]))
    rollers = ""
    for names, side in ((LEFT, 1), (RIGHT, -1)):
        for name, x in zip(names, ROLLER_XS):
            rollers += f"""
      <body name="{name}" pos="{x} {side * TRACK_Y} {AXLE_Z}">
        <joint name="{name}_s" type="slide" axis="0 0 1" stiffness="{SPRING_K}" damping="{SPRING_D}" range="{-SPRING_TRAVEL_M} {SPRING_TRAVEL_M}" limited="true"/>
        <joint name="{name}" type="hinge" axis="0 -1 0" damping="0.005" armature="0.002"/>
        <geom name="{name}" type="capsule" size="{ROLLER_R} {ROLLER_HALF_W}" euler="90 0 0" mass="{ROLLER_KG}" priority="1" friction="0.5 0.005 0.0001" solref="0.006 1" solimp="0.95 0.99 0.001" contype="1" conaffinity="0"/>
      </body>"""
    beads = "".join(
        f'<geom name="{n}" type="capsule" size="{SEAM_R} {half}" pos="{c[0]} {c[1]} {c[2]}" euler="{"90 0 0" if axis == "y" else "0 90 0"}" contype="0" conaffinity="1" friction="0.5 0.005 0.0001"/>'
        for n, c, half, axis in seams(world))
    acts = "".join(f'<velocity name="{n}" joint="{n}" kv="12" forcerange="-8 8"/>' for n in (*LEFT, *RIGHT))
    acts += f'<velocity name="{DRUM}" joint="{DRUM}" kv="2" forcerange="-25 25"/>'
    return f"""<mujoco model="hull_crawler">
  <option timestep="{TIMESTEP}" gravity="0 0 -9.81" density="{world['water']['density']}" viscosity="{world['water']['viscosity']}" wind="{wx} {wy} 0" integrator="implicitfast" cone="elliptic" impratio="4"/>
  <worldbody>
    <geom name="hull" type="plane" size="0 0 1" euler="180 0 0" contype="0" conaffinity="1" friction="0.5 0.005 0.0001"/>
    {beads}
    <body name="chassis" pos="{start[0]} {start[1]} {RIDE_Z}">
      <freejoint name="root"/>
      <geom name="skid" type="box" size="{CHASSIS_HALF[0]} {CHASSIS_HALF[1]} {CHASSIS_HALF[2]}" pos="{CHASSIS_CENTRE_X} 0 0" mass="{CHASSIS_KG}" friction="0.2 0.005 0.0001" contype="1" conaffinity="0"/>{rollers}
      <body name="{DRUM}" pos="{DRUM_X} 0 {DRUM_Z}">
        <joint name="{DRUM}" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="cylinder" size="0.05 {DRUM_HALF_W}" euler="90 0 0" mass="{DRUM_KG}" contype="0" conaffinity="0"/>
      </body>
    </body>
  </worldbody>
  <actuator>{acts}</actuator>
</mujoco>"""


def start_pose(world):
    p = world["patch"]
    return p["x0"] - DRUM_X - 0.30, p["y0"] + 0.2


def load_model(world):
    return mujoco.MjModel.from_xml_string(_xml(world, start_pose(world)))
