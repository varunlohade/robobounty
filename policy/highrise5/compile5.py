"""Compiles a v5 world to physics_xml, view_xml and one effect per object.

compile() validates first and builds from the validated copy. No text reaches the XML except names that
match world5.NAME_RE, and each of those goes after a fixed prefix. physics_xml holds no colour, light or
scenery, so a picture edit cannot change its bytes. view_xml holds the same solids plus the picture.
"""
import hashlib
import json
import math

import world5 as W


def _f(v):
    return f"{v:.6f}"


def _material(view, name):
    return f' material="{name}"' if view else ""


def _solid(view, material):
    return f'conaffinity="1" friction="0.3 0.005 0.0001"{_material(view, material)}'


def _vis(material):
    return f'class="vis" material="{material}"'


def _box(name, x0, x1, z0, z1, y0, y1, attrs):
    return (f'<geom name="{name}" type="box" size="{_f((x1 - x0) / 2)} {_f((y1 - y0) / 2)} {_f((z1 - z0) / 2)}" '
            f'pos="{_f((x0 + x1) / 2)} {_f((y0 + y1) / 2)} {_f((z0 + z1) / 2)}" {attrs}/>')


def _shape(obj):
    s = obj["size"]
    if obj["shape"] == "box":
        return f'type="box" size="{_f(s[0] / 2)} {_f(s[1] / 2)} {_f(s[2] / 2)}"'
    if obj["shape"] == "sphere":
        return f'type="sphere" size="{_f(s[0])}"'
    kind = "cylinder" if obj["shape"] == "cyl" else "capsule"
    return f'type="{kind}" size="{_f(s[0])} {_f(s[1] / 2)}"'


def _object_geom(world, obj, attrs):
    x, y, z = W.object_center(world, obj)
    euler = obj["euler_deg"]
    rot = f' euler="{_f(euler[0])} {_f(euler[1])} {_f(euler[2])}"' if any(euler) else ""
    return f'<geom name="obj_{obj["name"]}" {_shape(obj)} pos="{_f(x)} {_f(y)} {_f(z)}"{rot} {attrs}/>'


def _object_extras(world, obj):
    """Picture-only parts of a legacy kind."""
    if obj["kind"] not in ("balcony", "vent"):
        return []
    x, _, z = W.object_center(world, obj)
    w, d, h = obj["size"]
    name = obj["name"]
    steel = _vis("el_steel")
    if obj["kind"] == "balcony":
        rail = z + h / 2 + 1.0
        out = [_box(f"obj_{name}.rail", x - w / 2, x + w / 2, rail - 0.03, rail + 0.03, -d, -d + 0.05, steel)]
        for i, side in enumerate((-1, 1)):
            out.append(_box(f"obj_{name}.post{i}", x + side * w / 2 - 0.03, x + side * w / 2 + 0.03, z, rail, -d, -d + 0.05, steel))
        return out
    bars = W.vent_bar_count(obj)
    out = []
    for i in range(bars):
        bz = z - h / 2 + (i + 0.5) * h / bars
        out.append(_box(f"obj_{name}.bar{i}", x - w / 2 + 0.01, x + w / 2 - 0.01, bz - 0.008, bz + 0.008, -d - 0.002, -d, steel))
    return out


def _cradle(world, obj, view):
    x, y, z = W.object_center(world, obj)
    w, d, h = obj["size"]
    rail = ""
    if view:
        rail = (f'<geom name="obj_{obj["name"]}.rail" class="vis" type="box" size="{_f(w / 2 + 0.02)} 0.02 0.03" '
                f'pos="0 -0.28 {_f(h / 2 + 0.5)}" material="el_steel"/>')
    return (f'<body name="cradle" mocap="true" pos="{_f(x)} {_f(y)} {_f(z)}">'
            f'<geom name="obj_{obj["name"]}" type="box" size="{_f(w / 2)} {_f(d / 2)} {_f(h / 2)}" {_solid(view, obj["material"])}/>'
            f'{rail}</body>')


def _assets(world):
    rows = []
    for name, m in world["materials"].items():
        r, g, b, a = m["rgba"]
        reflect = ' reflectance="0.25"' if name == "glass" else ""
        rows.append(f'<material name="{name}" rgba="{r} {g} {b} {a}" specular="{m["metal"]}" shininess="{round(1 - m["roughness"], 6)}"{reflect}/>')
    return "\n    ".join(rows)


def _picture_world(world, glass, area):
    """Tower, parapet, ground, city and light. Only the view gets these."""
    t = world["tower"]
    roof = t["height_m"]
    half = t["width_m"] / 2
    cx = (glass["x0"] + glass["x1"]) / 2
    x0, x1 = cx - half, cx + half
    if t["corner"]:
        cut = area["x0"] + t["corner"]["x_m"]
        if t["corner"]["side"] > 0:
            x1 = cut
        else:
            x0 = cut
    tower_top = area["z1"] + t["setback"]["above_top_m"] if t["setback"] else roof
    geoms = ['<geom name="ground" class="vis" type="plane" size="900 900 1" pos="0 -300 0" material="ground"/>',
             f'<geom name="tower" class="vis" type="box" size="{_f((x1 - x0) / 2)} 14 {_f(tower_top / 2)}" pos="{_f((x0 + x1) / 2)} 14.2 {_f(tower_top / 2)}" material="tower"/>']
    if t["setback"]:
        d = t["setback"]["depth_m"]
        geoms.append(f'<geom name="tower_upper" class="vis" type="box" size="{_f((x1 - x0) / 2)} {_f(14 - d / 2)} {_f((roof - tower_top) / 2)}" '
                     f'pos="{_f((x0 + x1) / 2)} {_f(14.2 + d / 2)} {_f((roof + tower_top) / 2)}" material="tower"/>')
        geoms.append(f'<geom name="terrace" class="vis" type="box" size="{_f((x1 - x0) / 2)} {_f(d / 2)} 0.12" '
                     f'pos="{_f((x0 + x1) / 2)} {_f(d / 2)} {_f(tower_top)}" material="concrete"/>')
    geoms.append(f'<geom name="parapet" class="vis" type="box" size="{_f(half)} 0.6 0.5" pos="{cx} 0 {roof + 0.5}" material="concrete"/>')
    geoms.append(f'<geom name="anchor_post" class="vis" type="box" size="0.08 0.3 0.08" pos="{cx} {W.ANCHOR_Y + 0.25} {roof}" material="alu"/>')
    for n, (ix, iy, h) in enumerate(W.city_blocks(world)):
        geoms.append(f'<geom name="city{n}" class="vis" type="box" size="28 28 {h / 2}" pos="{ix * 95} {-iy * 110 - 30} {h / 2}" material="city{n % 2}"/>')
    return "\n      ".join(geoms)


def _view_settings(world, cx, area):
    light = world["light"]
    az = math.radians(light["azimuth_deg"])
    level = light["sun_level"] / 0.7
    fog_end = max(50.0, 520.0 - 480.0 * light["haze"])
    top, bottom = world["sky"]["top"], world["sky"]["bottom"]
    sky = (f'<texture type="skybox" name="sky" builtin="gradient" rgb1="{top[0]} {top[1]} {top[2]}" '
           f'rgb2="{bottom[0]} {bottom[1]} {bottom[2]}" width="256" height="512"/>')
    sun = (f'<light name="sun" directional="true" pos="60 -80 240" dir="{_f(0.75 * math.sin(az))} {_f(0.75 * math.cos(az))} -0.66" '
           f'diffuse="{_f(0.9 * level)} {_f(0.85 * level)} {_f(0.78 * level)}" specular="0.3 0.3 0.3" castshadow="true"/>')
    head = f"""<statistic extent="4" center="{cx} -1 {area['z1']}"/>
  <visual>
    <global offwidth="1280" offheight="720" fovy="35"/>
    <quality shadowsize="4096"/>
    <map znear="0.01" zfar="500" fogstart="40" fogend="{_f(fog_end)}"/>
    <rgba fog="0.80 0.76 0.72 1" haze="0.92 0.80 0.68 1"/>
  </visual>"""
    return head, sky, sun


def _build(world, view):
    g = W.glass_rect(world)
    a = W.area_rect(world)
    roof = world["tower"]["height_m"]
    d = world["panes"]["joint_depth_m"]
    h = max(d, W.MULLION_MIN_H)
    R = W.MULLION_ROUND_R
    hw, hh = (g["x1"] - g["x0"]) / 2, (g["z1"] - g["z0"]) / 2
    cx, cz = (g["x1"] + g["x0"]) / 2, (g["z1"] + g["z0"]) / 2
    mullions = "\n    ".join(
        f'<geom name="mullion{i}" class="joint" type="capsule" size="{R} {hh}" pos="{x:.5f} {R - h:.5f} {cz:.4f}"/>'
        for i, x in enumerate(W.mullion_xs(world)))
    transoms = "\n    ".join(
        f'<geom name="transom{i}" class="joint" type="capsule" size="{R} {hw}" pos="{cx:.4f} {R - h:.5f} {z:.5f}" euler="0 90 0"/>'
        for i, z in enumerate(W.transom_zs(world)))
    sx, sz = W.start_pose(world)
    start_len = math.sqrt((sx - cx) ** 2 + W.ANCHOR_Y ** 2 + (roof - sz) ** 2) + 0.5
    mu = W.friction(world)

    solids, pictures, moving, effects = [], [], [], []
    patches = False
    for o in world["objects"]:
        effect = W.effect_of(o)
        effects.append({"name": o["name"], "kind": o["kind"], "effect": effect, "gap_m": round(W.gap_m(o), 6)})
        if o["kind"] in W.SURFACE_KINDS:
            patches = True
            if view and o["kind"] == "wet_patch":
                pictures.append(_object_geom(world, o, _vis(o["material"])))
        elif o["kind"] == "cradle":
            moving.append(_cradle(world, o, view))
        elif effect == "physics":
            solids.append(_object_geom(world, o, _solid(view, o["material"])))
            if view:
                pictures.extend(_object_extras(world, o))
        elif view:
            pictures.append(_object_geom(world, o, _vis(o["material"])))

    rollers = []
    for side, y in (("l", W.ROLLER_Y), ("r", -W.ROLLER_Y)):
        for end, x in (("f", W.ROLLER_X), ("b", -W.ROLLER_X)):
            rollers.append(
                f'<body name="roller_{side}{end}" pos="{x} {y} {W.ROLLER_RADIUS}">'
                f'<joint name="drive_{side}{end}" type="hinge" axis="0 1 0" armature="0.01" damping="0.002"/>'
                f'<geom name="roller_{side}{end}" class="roller"/></body>')
    drive = "\n    ".join(
        f'<velocity name="drive_{n}" joint="drive_{n}" kv="20" forcerange="-1.5 1.5" forcelimited="true"/>'
        for n in ("lf", "lb", "rf", "rb"))
    zc = W.RIDE_CLEARANCE + W.BODY_HEIGHT / 2
    half = W.BODY_SIDE / 2
    robot_picture = []
    if view:
        robot_picture = [
            f'<geom name="robot_stripe" class="vis" type="box" size="{half + 0.002} 0.03 {W.BODY_HEIGHT / 2 + 0.001}" pos="0 0 {zc}" material="burgundy"/>',
            f'<geom name="robot_hub" class="vis" type="cylinder" size="0.09 0.012" pos="0 0 {zc + W.BODY_HEIGHT / 2 + 0.01}" material="alu"/>',
            f'<geom name="robot_track_l" class="vis" type="capsule" size="0.03 0.15" pos="0 {W.ROLLER_Y} {W.ROLLER_RADIUS}" euler="0 90 0" material="rubber"/>',
            f'<geom name="robot_track_r" class="vis" type="capsule" size="0.03 0.15" pos="0 {-W.ROLLER_Y} {W.ROLLER_RADIUS}" euler="0 90 0" material="rubber"/>',
            f'<geom name="robot_pads" class="vis" type="box" size="0.04 0.16 0.004" pos="{W.PAD_X} 0 0.006" material="burgundy"/>',
        ]
    # Roller friction wins over the glass when patches exist, so the sim can set it per roller.
    roller_priority = ' priority="2"' if patches else ""
    head, asset, sun, scenery = "", "", "", ""
    if view:
        head, sky, sun = _view_settings(world, cx, a)
        asset = f"<asset>\n    {sky}\n    {_assets(world)}\n  </asset>"
        scenery = f'<body name="scenery">\n      {_picture_world(world, g, a)}\n    </body>'
    pictures_xml = "\n    ".join(pictures)
    solids_xml = "\n    ".join(solids)
    moving_xml = "\n    ".join(moving)
    robot_xml = "\n      ".join(robot_picture + rollers)
    tether_material = _material(view, "tether")
    vis_class = '<default class="vis"><geom/></default>' if view else ""
    xml = f"""<mujoco model="highrise5">
  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="1" noslip_iterations="3" solver="Newton" iterations="20" ls_iterations="6"/>
  {head}
  <default>
    <geom contype="0" conaffinity="0" density="0" group="1"/>
    {vis_class}
    <default class="joint"><geom conaffinity="1" priority="1" friction="{mu} 0.005 0.0001"{_material(view, "alu")}/></default>
    <default class="roller">
      <geom type="sphere" size="{W.ROLLER_RADIUS}" contype="1"{roller_priority} density="400"{_material(view, "rubber")} solref="-20000 -300"/>
    </default>
  </default>
  {asset}
  <worldbody>
    {sun}
    <geom name="glass" type="box" size="{hw} 0.05 {hh}" pos="{cx} 0.05 {cz}"
          contype="0" conaffinity="1" priority="1" friction="{mu} 0.005 0.0001"{_material(view, "glass")}/>
    {mullions}
    {transoms}
    {solids_xml}
    {pictures_xml}
    {scenery}
    <site name="anchor" pos="{cx} {W.ANCHOR_Y} {roof}" size="0.03"/>
    {moving_xml}
    <body name="robot" pos="{sx} 0 {sz}" quat="-0.5 -0.5 -0.5 0.5">
      <freejoint name="robot_free"/>
      <inertial pos="0 0 0.05" mass="{W.BODY_MASS_KG}" diaginertia="0.045 0.045 0.086"/>
      <geom name="chassis" type="box" size="{half} {half} {W.BODY_HEIGHT / 2}" pos="0 0 {zc}" contype="1"
            friction="0.3 0.005 0.0001"{_material(view, "cream")}/>
      <site name="tether_point" pos="0 0 {W.TETHER_ATTACH_Z}" size="0.01"/>
      {robot_xml}
    </body>
  </worldbody>
  <tendon>
    <spatial name="tether" limited="true" range="0 {start_len:.4f}" width="0.004"{tether_material}
             solreflimit="-8000 -60" solimplimit="0.95 0.99 0.001">
      <site site="anchor"/><site site="tether_point"/>
    </spatial>
  </tendon>
  <actuator>
    {drive}
  </actuator>
</mujoco>
"""
    return xml, effects


def compile(world):
    checked = W.validate(world)
    physics_xml, effects = _build(checked, False)
    view_xml, _ = _build(checked, True)
    return physics_xml, view_xml, effects


def physics_inputs(world):
    """What the sim will read beyond physics_xml. Weather sets glass friction in the XML, but the sim also reads it."""
    checked = W.validate(world)
    props = [{"name": o["name"], "kind": o["kind"], "props": o["props"], "pos": o["pos"], "size": o["size"]}
             for o in checked["objects"] if W.effect_of(o) == "physics"]
    return {"wind": checked["wind"], "weather": checked["weather"], "robot": checked["robot"], "robot_start": checked["robot_start"],
            "dirt_level": checked["area"]["dirt_level"], "joint_gap_m": checked["panes"]["joint_gap_m"], "objects": props}


def physics_hash(world):
    """A picture edit leaves this unchanged. Any edit that needs a new run changes it, even with no XML change, such as wind."""
    physics_xml, _, _ = compile(world)
    inputs = json.dumps(physics_inputs(world), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((physics_xml + inputs).encode()).hexdigest()
