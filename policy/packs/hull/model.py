"""The crawler and the plate as MJCF. z up, hull plane at z = 0 facing down, so the robot hangs below it. Body frame: x forward, z toward the hull.

Wheels and weld beads collide as capsules, so rolling contact stays analytic. The picture draws real wheels of the same radius and beads of the same height.
"""
import mujoco

from . import world as W

WHEEL_R = 0.065
WHEEL_HALF_W = 0.025
WHEEL_X = (0.06, -0.24)
WHEEL_Y = 0.24
AXLE_Z = 0.035  # above the chassis origin
BRUSH_X = 0.21
BRUSH_Y = 0.115
BRUSH_R = 0.125
BRUSH_Z = 0.055  # hub above the chassis origin
BRISTLE_TIP_Z = 0.112  # free tips above the chassis origin, 12 mm past the wheel tops
CHASSIS_HALF = (0.20, 0.17, 0.062)  # the skid plate's top is CHASSIS_HALF[2] above the origin
CHASSIS_CENTRE_X = -0.10
RIDE_Z = -(AXLE_Z + WHEEL_R)  # chassis origin height on flat plate
CHASSIS_KG = 17.4
WHEEL_KG = 1.2
BRUSH_KG = 1.1
VOLUME_M3 = 0.0135
BUOY_LOCAL = (-0.03, 0.0, 0.02)
SEAM_R = 0.04  # bead cross-section radius
TIMESTEP = 0.002
CASTER_Y = 0.20
CASTER_TRAIL = 0.045  # the rear wheel trails its swivel axis by this much
WHEELS = ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr")
DRIVEN = ("wheel_fl", "wheel_fr")  # Front pair driven. Rear pair on swivels, so a pivot does not scrub the magnets sideways.
CASTERS = ("caster_rl", "caster_rr")
BRUSHES = ("brush_l", "brush_r")
BODIES = ("chassis", *WHEELS, *CASTERS, *BRUSHES)


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
    cur = world["current"]
    import math
    wx, wy = cur["speed_ms"] * math.cos(math.radians(cur["dir_deg"])), cur["speed_ms"] * math.sin(math.radians(cur["dir_deg"]))
    tyre = f'type="capsule" size="{WHEEL_R} {WHEEL_HALF_W}" euler="90 0 0" mass="{WHEEL_KG}" priority="1" friction="0.5 0.005 0.0001" solref="0.006 1" solimp="0.95 0.99 0.001" contype="1" conaffinity="0"'
    wheels = ""
    for name, side in zip(DRIVEN, (1, -1)):
        wheels += f"""
      <body name="{name}" pos="{WHEEL_X[0]} {side * WHEEL_Y} {AXLE_Z}">
        <joint name="{name}" type="hinge" axis="0 -1 0" damping="0.02" armature="0.02"/>
        <geom name="{name}" {tyre}/>
      </body>"""
    for name, caster, side in zip(WHEELS[2:], CASTERS, (1, -1)):
        wheels += f"""
      <body name="{caster}" pos="{WHEEL_X[1] + CASTER_TRAIL} {side * CASTER_Y} {AXLE_Z}">
        <joint name="{caster}" type="hinge" axis="0 0 1" damping="0.15"/>
        <geom type="box" size="0.03 0.03 0.02" mass="0.3" contype="0" conaffinity="0"/>
        <body name="{name}" pos="{-CASTER_TRAIL} 0 0">
          <joint name="{name}" type="hinge" axis="0 -1 0" damping="0.02"/>
          <geom name="{name}" {tyre}/>
        </body>
      </body>"""
    brushes = ""
    for name, side in zip(BRUSHES, (1, -1)):
        brushes += f"""
      <body name="{name}" pos="{BRUSH_X} {side * BRUSH_Y} {BRUSH_Z}">
        <joint name="{name}" type="hinge" axis="0 0 1" damping="0.01"/>
        <geom type="cylinder" size="{BRUSH_R} 0.02" mass="{BRUSH_KG}" contype="0" conaffinity="0"/>
      </body>"""
    beads = "".join(
        f'<geom name="{n}" type="capsule" size="{SEAM_R} {half}" pos="{c[0]} {c[1]} {c[2]}" euler="{"90 0 0" if axis == "y" else "0 90 0"}" contype="0" conaffinity="1" friction="0.5 0.005 0.0001"/>'
        for n, c, half, axis in seams(world))
    acts = "".join(f'<velocity name="{n}" joint="{n}" kv="60" forcerange="-30 30"/>' for n in DRIVEN)
    acts += "".join(f'<velocity name="{n}" joint="{n}" kv="1.5" forcerange="-12 12"/>' for n in BRUSHES)
    return f"""<mujoco model="hull_crawler">
  <option timestep="{TIMESTEP}" gravity="0 0 -9.81" density="{world['water']['density']}" viscosity="{world['water']['viscosity']}" wind="{wx} {wy} 0" integrator="implicitfast" cone="elliptic" impratio="4"/>
  <worldbody>
    <geom name="hull" type="plane" size="0 0 1" euler="180 0 0" contype="0" conaffinity="1" friction="0.5 0.005 0.0001"/>
    {beads}
    <body name="chassis" pos="{start[0]} {start[1]} {RIDE_Z}">
      <freejoint name="root"/>
      <geom name="skid" type="box" size="{CHASSIS_HALF[0]} {CHASSIS_HALF[1]} {CHASSIS_HALF[2]}" pos="{CHASSIS_CENTRE_X} 0 0" mass="{CHASSIS_KG}" friction="0.2 0.005 0.0001" contype="1" conaffinity="0"/>{wheels}{brushes}
    </body>
  </worldbody>
  <actuator>{acts}</actuator>
</mujoco>"""


def start_pose(world):
    p = world["patch"]
    return p["x0"] - BRUSH_X - BRUSH_R - 0.05, p["y0"] + 0.2


def load_model(world):
    return mujoco.MjModel.from_xml_string(_xml(world, start_pose(world)))
