"""World schema and MJCF builder for a suction window robot on one high-rise facade.

A world file holds numbers only. Every field is required, finite and in range. No text from a
world file reaches the MJCF. The MJCF uses primitives only, so it also loads in browser MuJoCo.
"""
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "highrise.world.v3"

# name: (min, max). SI units unless the name says otherwise.
FIELDS = {
    "steady_wind_ms": (0.0, 25.0),
    "gust_speed_ms": (0.0, 60.0),
    "gust_start_s": (0.0, 500.0),
    "gust_duration_s": (0.5, 60.0),
    "gust_count": (0, 6),
    "gust_period_s": (5.0, 200.0),
    "wind_dir_deg": (-180.0, 180.0),  # 0 runs along the wall to +x, 90 blows into the wall, -90 away from it
    "wetness": (0.0, 1.0),  # 0 dry glass, 1 fully wet, mixes the two friction values
    "mullion_depth_m": (0.0, 0.04),  # how far the pane joints stand proud of the glass
    "mullion_spacing_m": (0.8, 3.0),
    "mullion_offset_m": (0.0, 3.0),
    "joint_gap_m": (0.0, 0.03),  # open width of the sealant joint next to a mullion
    "edge_margin_m": (0.4, 3.0),  # glass that continues past the assigned area on each side and above
    "area_width_m": (0.8, 5.0),
    "area_height_m": (1.0, 6.0),
    "drop_below_roof_m": (5.0, 80.0),  # top of the assigned area below the roof anchor
    "suction_pa": (500.0, 5000.0),  # impeller shut-off pressure at full speed
    "seal_leak_mm2": (20.0, 2000.0),  # leak area of the skirt on clean flat glass
    "battery_start_frac": (0.02, 1.0),
    "pad_force_n": (5.0, 90.0),  # total pad force on the glass when the robot sits flat
    "dirt_level": (0.1, 2.0),
    "ledge_depth_m": (0.01, 0.25),
    "ledge_below_top_m": (0.5, 14.0),
    "ledge_x_m": (-6.0, 6.0),
    "ledge_width_m": (0.2, 12.0),
    "temperature_c": (-20.0, 50.0),  # air and battery temperature
    "humidity_pct": (0.0, 100.0),
    "dust_gm2": (0.0, 60.0),  # dust load on the glass
    "sun_level": (0.2, 1.0),  # render only, no effect on physics
}
INTEGER_FIELDS = {"gust_count"}

BODY_SIDE = 0.36
BODY_MASS_KG = 4.0
BODY_HEIGHT = 0.08
RIDE_CLEARANCE = 0.02  # chassis underside above the glass
ROLLER_RADIUS = 0.035
ROLLER_X = 0.12
ROLLER_Y = 0.15
PAD_X = -0.13
PAD_Y = (-0.10, 0.0, 0.10)
PAD_REACH_M = 0.006  # pad springs compress this much when the body sits flat on the glass
TETHER_ATTACH_Z = 0.09
MULLION_ROUND_R = 0.04  # radius of the rounded joint cap
MULLION_MIN_H = 0.0005
ANCHOR_Y = -0.30
ROOF_Z = 160.0
START_ABOVE_TOP = 0.13  # body centre start above the area top, so the pads reach the top edge
MU_DRY = 0.75
MU_WET = 0.30
MU_DUST = 0.40
DUST_FRICTION_SCALE_GM2 = 5.0
AIR_PRESSURE_PA = 101325.0
GLASS_BELOW_AIR_C = 3.0
CONDENSATION_RAMP_C = 3.0
LEDGE_THICKNESS = 0.12
TRANSOM_SPACING = 3.6  # floor height, fixed for the tower


class WorldError(ValueError):
    pass


def _reject_constant(name):
    raise WorldError(f"non-finite number {name}")


def validate(raw):
    if not isinstance(raw, dict):
        raise WorldError("world must be an object")
    expected = set(FIELDS) | {"schema"}
    if set(raw) != expected:
        raise WorldError(f"bad fields: missing {sorted(expected - set(raw))}, extra {sorted(set(raw) - expected)}")
    if raw["schema"] != SCHEMA:
        raise WorldError("bad schema")
    world = {"schema": SCHEMA}
    for name, (lo, hi) in FIELDS.items():
        v = raw[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise WorldError(f"{name} must be a number")
        if name in INTEGER_FIELDS and not isinstance(v, int):
            raise WorldError(f"{name} must be an integer")
        if not math.isfinite(v) or not lo <= v <= hi:
            raise WorldError(f"{name}={v} outside [{lo}, {hi}]")
        world[name] = int(v) if name in INTEGER_FIELDS else float(v)
    return world


def load(path):
    return validate(json.loads(Path(path).read_text(), parse_constant=_reject_constant))


def world_hash(world):
    return hashlib.sha256(json.dumps(world, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def air(world):
    """Moist air density from the ideal gas mix, and the dew point. Saturation pressure from the Magnus form."""
    t = world["temperature_c"]
    kelvin = t + 273.15
    e_s = 610.94 * math.exp(17.625 * t / (t + 243.04))
    e = world["humidity_pct"] / 100.0 * e_s
    rho = (AIR_PRESSURE_PA - e) / (287.05 * kelvin) + e / (461.5 * kelvin)
    if e <= 0:
        return rho, -273.15
    x = math.log(e / 610.94)
    return rho, 243.04 * x / (17.625 - x)


def effective_wetness(world):
    """The larger of the stated wetness and condensation, when the glass is colder than the dew point."""
    _, dew = air(world)
    glass = world["temperature_c"] - GLASS_BELOW_AIR_C
    return max(world["wetness"], min(1.0, max(0.0, (dew - glass) / CONDENSATION_RAMP_C)))


def friction(world):
    clean = MU_DRY + (MU_WET - MU_DRY) * effective_wetness(world)
    return clean + (MU_DUST - clean) * (1 - math.exp(-world["dust_gm2"] / DUST_FRICTION_SCALE_GM2))


def area(world):
    """The assigned rectangle of glass. Its left edge is at x=0 and the glass grows from there."""
    top = ROOF_Z - world["drop_below_roof_m"]
    return {"x0": 0.0, "x1": world["area_width_m"], "z0": top - world["area_height_m"], "z1": top}


def glass_rect(world):
    a = area(world)
    m = world["edge_margin_m"]
    return {"x0": a["x0"] - m, "x1": a["x1"] + m, "z0": a["z0"] - 16.0, "z1": a["z1"] + m}


def mullion_xs(world):
    g = glass_rect(world)
    s, off = world["mullion_spacing_m"], world["mullion_offset_m"]
    k = math.ceil((g["x0"] - off) / s)
    out = []
    while off + k * s < g["x1"]:
        out.append(off + k * s)
        k += 1
    return out


def transom_zs(world):
    g = glass_rect(world)
    s = TRANSOM_SPACING
    k = math.ceil((g["z0"] + 0.01) / s)
    out = []
    while k * s < g["z1"]:
        out.append(k * s)
        k += 1
    return out


def start_pose(world):
    """Body origin on the glass at the top of lane one, heading down."""
    a = area(world)
    return a["x0"] + BODY_SIDE / 2 - 0.03, a["z1"] + START_ABOVE_TOP


def _scenery():
    """A few far blocks so the view reads as high up. No collision."""
    blocks = []
    n = 0
    for ix in range(-6, 7):
        for iy in range(1, 6):
            h = 12 + (ix * 37 + iy * 53) % 45
            blocks.append(f'<geom class="vis" type="box" size="28 28 {h / 2}" pos="{ix * 95} {-iy * 110 - 30} {h / 2}" '
                          f'material="city{n % 2}"/>')
            n += 1
    return "\n      ".join(blocks)


def build_xml(world):
    g = glass_rect(world)
    d = world["mullion_depth_m"]
    h = max(d, MULLION_MIN_H)
    R = MULLION_ROUND_R
    hw, hh = (g["x1"] - g["x0"]) / 2, (g["z1"] - g["z0"]) / 2
    cx, cz = (g["x1"] + g["x0"]) / 2, (g["z1"] + g["z0"]) / 2
    # A joint is a rounded cap: a capsule buried in the glass so only its crown stands proud by h.
    mullions = "\n    ".join(
        f'<geom name="mullion{i}" class="joint" type="capsule" size="{R} {hh}" pos="{x:.5f} {R - h:.5f} {cz:.4f}"/>'
        for i, x in enumerate(mullion_xs(world)))
    transoms = "\n    ".join(
        f'<geom name="transom{i}" class="joint" type="capsule" size="{R} {hw}" pos="{cx:.4f} {R - h:.5f} {z:.5f}" euler="0 90 0"/>'
        for i, z in enumerate(transom_zs(world)))
    a = area(world)
    lz = a["z1"] - world["ledge_below_top_m"]
    ld = world["ledge_depth_m"]
    sx, sz = start_pose(world)
    start_len = math.sqrt((sx - cx) ** 2 + ANCHOR_Y ** 2 + (ROOF_Z - sz) ** 2) + 0.5
    mu = friction(world)
    rollers = []
    for side, y in (("l", ROLLER_Y), ("r", -ROLLER_Y)):
        for end, x in (("f", ROLLER_X), ("b", -ROLLER_X)):
            rollers.append(
                f'<body name="roller_{side}{end}" pos="{x} {y} {ROLLER_RADIUS}">'
                f'<joint name="drive_{side}{end}" type="hinge" axis="0 1 0" armature="0.01" damping="0.002"/>'
                f'<geom name="roller_{side}{end}" class="roller"/></body>')
    rollers = "\n      ".join(rollers)
    drive = "\n    ".join(
        f'<velocity name="drive_{n}" joint="drive_{n}" kv="20" forcerange="-1.5 1.5" forcelimited="true"/>'
        for n in ("lf", "lb", "rf", "rb"))
    zc = RIDE_CLEARANCE + BODY_HEIGHT / 2
    half = BODY_SIDE / 2
    return f"""<mujoco model="highrise">
  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="1" noslip_iterations="3" solver="Newton" iterations="20" ls_iterations="6"/>
  <statistic extent="4" center="{cx} -1 {a['z1']}"/>
  <visual>
    <global offwidth="1280" offheight="720" fovy="35"/>
    <quality shadowsize="4096"/>
    <map znear="0.01" zfar="500" fogstart="40" fogend="280"/>
    <rgba fog="0.80 0.76 0.72 1" haze="0.92 0.80 0.68 1"/>
  </visual>
  <default>
    <geom contype="0" conaffinity="0" density="0" group="1"/>
    <default class="vis"><geom/></default>
    <default class="joint"><geom conaffinity="1" priority="1" friction="{mu} 0.005 0.0001" material="alu"/></default>
    <default class="roller">
      <geom type="sphere" size="{ROLLER_RADIUS}" contype="1" density="400" material="rubber" solref="-20000 -300"/>
    </default>
  </default>
  <asset>
    <texture type="skybox" name="sky" builtin="gradient" rgb1="0.42 0.58 0.80" rgb2="0.95 0.82 0.70" width="256" height="512"/>
    <material name="ground" rgba="0.34 0.33 0.32 1" specular="0"/>
    <material name="glass" rgba="0.20 0.30 0.40 1" specular="0.8" shininess="0.9" reflectance="0.25"/>
    <material name="alu" rgba="0.62 0.63 0.65 1" specular="0.6" shininess="0.6"/>
    <material name="concrete" rgba="0.55 0.52 0.48 1" specular="0.1"/>
    <material name="tower" rgba="0.26 0.31 0.37 1" specular="0.4" shininess="0.5"/>
    <material name="city0" rgba="0.60 0.57 0.54 1" specular="0"/>
    <material name="city1" rgba="0.46 0.48 0.52 1" specular="0"/>
    <material name="cream" rgba="0.93 0.89 0.79 1" specular="0.5" shininess="0.6"/>
    <material name="burgundy" rgba="0.42 0.07 0.13 1" specular="0.4" shininess="0.5"/>
    <material name="rubber" rgba="0.04 0.04 0.04 1" specular="0.2"/>
    <material name="tether" rgba="0.95 0.45 0.05 1"/>
  </asset>
  <worldbody>
    <light name="sun" directional="true" pos="60 -80 240" dir="-0.45 0.6 -0.66" diffuse="0.9 0.85 0.78" specular="0.3 0.3 0.3" castshadow="true"/>
    <geom name="glass" type="box" size="{hw} 0.05 {hh}" pos="{cx} 0.05 {cz}"
          contype="0" conaffinity="1" priority="1" friction="{mu} 0.005 0.0001" material="glass"/>
    {mullions}
    {transoms}
    <geom name="ledge" type="box" size="{world['ledge_width_m'] / 2} {ld / 2} {LEDGE_THICKNESS / 2}"
          pos="{world['ledge_x_m'] + a['x1'] / 2} {-ld / 2} {lz}" conaffinity="1" friction="0.3 0.005 0.0001" material="concrete"/>
    <body name="scenery">
      <geom name="ground" class="vis" type="plane" size="900 900 1" pos="0 -300 0" material="ground"/>
      <geom name="tower" class="vis" type="box" size="{hw + 12} 14 {ROOF_Z / 2}" pos="{cx} 14.2 {ROOF_Z / 2}" material="tower"/>
      <geom name="parapet" class="vis" type="box" size="{hw + 12} 0.6 0.5" pos="{cx} 0 {ROOF_Z + 0.5}" material="concrete"/>
      <geom name="anchor_post" class="vis" type="box" size="0.08 0.3 0.08" pos="{cx} {ANCHOR_Y + 0.25} {ROOF_Z}" material="alu"/>
      {_scenery()}
    </body>
    <site name="anchor" pos="{cx} {ANCHOR_Y} {ROOF_Z}" size="0.03"/>
    <body name="robot" pos="{sx} 0 {sz}" quat="-0.5 -0.5 -0.5 0.5">
      <freejoint name="robot_free"/>
      <inertial pos="0 0 0.05" mass="{BODY_MASS_KG}" diaginertia="0.045 0.045 0.086"/>
      <geom name="chassis" type="box" size="{half} {half} {BODY_HEIGHT / 2}" pos="0 0 {zc}" contype="1"
            friction="0.3 0.005 0.0001" material="cream"/>
      <geom class="vis" type="box" size="{half + 0.002} 0.03 {BODY_HEIGHT / 2 + 0.001}" pos="0 0 {zc}" material="burgundy"/>
      <geom class="vis" type="cylinder" size="0.09 0.012" pos="0 0 {zc + BODY_HEIGHT / 2 + 0.01}" material="alu"/>
      <geom class="vis" type="capsule" size="0.03 0.15" pos="0 {ROLLER_Y} {ROLLER_RADIUS}" euler="0 90 0" material="rubber"/>
      <geom class="vis" type="capsule" size="0.03 0.15" pos="0 {-ROLLER_Y} {ROLLER_RADIUS}" euler="0 90 0" material="rubber"/>
      <geom class="vis" type="box" size="0.04 0.16 0.004" pos="{PAD_X} 0 0.006" material="burgundy"/>
      <site name="tether_point" pos="0 0 {TETHER_ATTACH_Z}" size="0.01"/>
      {rollers}
    </body>
  </worldbody>
  <tendon>
    <spatial name="tether" limited="true" range="0 {start_len:.4f}" width="0.004" material="tether"
             solreflimit="-8000 -60" solimplimit="0.95 0.99 0.001">
      <site site="anchor"/><site site="tether_point"/>
    </spatial>
  </tendon>
  <actuator>
    {drive}
  </actuator>
</mujoco>
"""
