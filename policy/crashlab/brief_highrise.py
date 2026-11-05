"""High-rise world schema for brief.py. It conforms to policy/highrise/world.py and reads its limits from there.

A world file holds numbers only, so it has no place to hold text. A field the brief does not mention stays in a
small range around the nominal world, and the LLM cannot move it without citing a brief phrase.
"""
import importlib.util
import json
import random
from pathlib import Path

from world import WorldError, _integer, _number

_spec = importlib.util.spec_from_file_location("highrise_world", Path(__file__).resolve().parent.parent / "highrise" / "world.py")
hw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hw)

FIELDS = hw.FIELDS
FACTORS = tuple(FIELDS)
# field: (default low, default high, meaning for the planner). Defaults sit around policy/highrise/worlds/nominal.json.
GUIDE = {
    "steady_wind_ms": (1.0, 3.0, "steady wind. Calm 0-1, windy 6-10, very windy 10-15."),
    "gust_speed_ms": (3.0, 7.0, "gust speed. Calm 0-3, moderate 8-13, strong 15-25, storm 25-40."),
    "gust_start_s": (20.0, 60.0, "time of the first gust."),
    "gust_duration_s": (4.0, 8.0, "length of each gust."),
    "gust_count": (1, 3, "number of gusts."),
    "gust_period_s": (30.0, 60.0, "time between gust starts."),
    "wind_dir_deg": (0.0, 40.0, "0 runs along the wall, 90 blows into the wall, -90 pulls away from the wall."),
    "wetness": (0.1, 0.3, "water on the glass. It mixes dry and wet friction. Dry 0, damp 0.3-0.6, fully wet 1."),
    "mullion_depth_m": (0.003, 0.007, "how far pane joints stand proud of the glass. Flush 0-0.003, proud 0.01-0.02, deep 0.03-0.04."),
    "mullion_spacing_m": (1.4, 1.6, "distance between joints. Tight 0.8-1.1, wide 2.2-3.0."),
    "mullion_offset_m": (0.7, 0.8, "sideways shift of the joint grid."),
    "joint_gap_m": (0.003, 0.005, "open width of the sealant joint next to a mullion. Closed 0, wide 0.01-0.03."),
    "edge_margin_m": (0.8, 1.2, "glass that continues past the work area. Tight 0.4-0.6, roomy 2-3."),
    "area_width_m": (2.2, 2.6, "width of the work area. Narrow 0.8-1.5, wide 4-5."),
    "area_height_m": (2.8, 3.2, "height of the work area. Short 1-2, tall 5-6."),
    "drop_below_roof_m": (21.0, 22.5, "how far below the roof the work area starts, which sets the tether length. It does not change the tower height. Near the roof 5-10, far down 50-80."),
    "suction_pa": (2600.0, 3000.0, "impeller shut-off pressure at full speed. Weak 500-1500, strong 3500-5000."),
    "seal_leak_mm2": (150.0, 250.0, "leak area of the skirt on clean flat glass. New 20-100, worn 400-2000."),
    "battery_start_frac": (0.9, 1.0, "battery charge at the start. Low 0.02-0.3."),
    "pad_force_n": (20.0, 30.0, "total cleaning pad force on the glass. Light 5-15, hard 50-90."),
    "dirt_level": (0.5, 0.7, "how dirty the glass is. Light 0.1-0.4, heavy 1.2-2.0."),
    "ledge_depth_m": (0.04, 0.06, "how far the ledge stands out. Shallow 0.01-0.03, deep 0.15-0.25."),
    "ledge_below_top_m": (7.0, 9.0, "ledge distance below the top of the work area. A value above the work area height puts it below the work."),
    "ledge_x_m": (-0.5, 0.5, "sideways position of the ledge centre."),
    "ledge_width_m": (1.5, 2.5, "width of the ledge."),
    "temperature_c": (10.0, 20.0, "air and battery temperature. Freezing -20-0, hot 35-50."),
    "humidity_pct": (40.0, 60.0, "relative humidity. Dry 0-20, humid 70-100. With temperature it can set condensation on the glass."),
    "dust_gm2": (0.5, 1.5, "dust load on the glass. Light 0-2, heavy 15-60. Airborne sand has no physics."),
    "sun_level": (0.6, 0.8, "sun brightness only. Dusk or low evening sun 0.2-0.35, noon 0.9-1.0. It changes the picture only. When the brief names a sun position such as low sun, also cite that phrase as light_direction_or_colour."),
}
VOCABULARY = {
    "steady_wind_ms": ("wind", "breez", "calm", "still", "storm", "gale"),
    "gust_speed_ms": ("gust", "wind", "storm", "gale", "squall", "calm", "still"),
    "gust_start_s": ("gust", "start", "time", "after", "early", "late", "second", "minute", "sudden"),
    "gust_duration_s": ("gust", "long", "short", "last", "second", "minute", "brief", "sustained"),
    "gust_count": ("gust", "repeated", "many", "single", "one", "two", "three", "four", "five", "six", "several", "few"),
    "gust_period_s": ("gust", "every", "repeated", "frequent", "apart", "second", "minute"),
    "wind_dir_deg": ("wind", "gust", "cross", "head", "side", "direction", "along", "into", "away", "wall"),
    "wetness": ("wet", "damp", "water", "rain", "dry", "slick", "slippery", "moist"),
    "mullion_depth_m": ("mullion", "joint", "deep", "shallow", "fin", "flush", "proud"),
    "mullion_spacing_m": ("mullion", "joint", "spacing", "wide", "narrow", "tight", "close", "panel", "pane"),
    "mullion_offset_m": ("mullion", "joint", "offset", "shift"),
    "joint_gap_m": ("joint", "gap", "sealant", "seam", "open", "wide"),
    "edge_margin_m": ("edge", "margin", "border", "tight", "corner"),
    "area_width_m": ("area", "width", "wide", "narrow", "panel", "pane", "metre", "meter"),
    "area_height_m": ("area", "height", "tall", "short", "panel", "pane", "metre", "meter"),
    "drop_below_roof_m": ("cable", "tether", "below", "roof", "metre", "meter", "down", "high", "top", "low", "floor"),
    "suction_pa": ("suction", "fan", "vacuum", "impeller", "pressure", "weak", "strong"),
    "seal_leak_mm2": ("seal", "skirt", "leak", "worn", "suction"),
    "battery_start_frac": ("battery", "charge", "power", "low"),
    "pad_force_n": ("pad", "brush", "pressure", "force", "scrub", "hard", "gentle", "light"),
    "dirt_level": ("dirt", "grime", "filth", "clean", "soil", "stain", "smear"),
    "ledge_depth_m": ("ledge", "sill", "step", "lip", "deep", "shallow"),
    "ledge_below_top_m": ("ledge", "sill", "step", "lip", "below", "low", "high"),
    "ledge_x_m": ("ledge", "sill", "step", "lip", "left", "right", "centre", "center", "side"),
    "ledge_width_m": ("ledge", "sill", "step", "lip", "wide", "narrow"),
    "temperature_c": ("temperature", "heat", "hot", "cold", "freez", "summer", "winter", "degree"),
    "humidity_pct": ("humid", "moisture", "condens", "fog", "muggy", "dry"),
    "dust_gm2": ("dust", "sand", "dirt", "grit", "powder"),
    "sun_level": ("light", "sun", "evening", "dusk", "dark", "night", "noon", "dawn", "bright", "dim", "morning", "glare"),
}
LIMITS = [
    f"The tower is fixed: roof at {hw.ROOF_Z:.0f} m, floors {hw.TRANSOM_SPACING} m apart, so about {hw.ROOF_Z / hw.TRANSOM_SPACING:.0f} floors. A brief cannot change it.",
    "sun_level changes the picture only, not the physics.",
    "Each world compiles in MuJoCo. No robot ran, so whether it survives or cleans in these values is unknown.",
    "Most physics numbers are assumptions, listed in policy/highrise/PARAMETERS.md. Nothing is calibrated to a real robot.",
    "Airborne sand has no physics. Only dust already on the glass does.",
]


def plan_schema():
    def bounds(name, f):
        kind = "integer" if name in hw.INTEGER_FIELDS else "number"
        limit = {"type": kind, "minimum": f[0], "maximum": f[1]}
        return {"type": "object", "additionalProperties": False, "required": ["min", "max"], "properties": {"min": limit, "max": limit}}
    return {"type": "object", "additionalProperties": False, "properties": {name: bounds(name, f) for name, f in FIELDS.items()}}


def catalog_text():
    lines = ["Catalog: one suction robot on a safety tether cleans an area of glass on one fixed tower, with pads. Set a min and a max only for "
             "the fields the brief asks about, and leave out every other field."]
    lines += [f"- {name}: limits {f[0]} to {f[1]}. {GUIDE[name][2]}" for name, f in FIELDS.items()]
    lines.append(f"Fixed and not in the plan: the tower has its roof at {hw.ROOF_Z:.0f} m and floors {hw.TRANSOM_SPACING} m apart. A tower height or "
                 "storey count is fixed, so cite it as unbuildable with reason fixed_in_this_world and do not set drop_below_roof_m from it.")
    lines.append("Also absent: rain, snow, ice, airborne sand, salt, birds, people, other robots, sun direction or angle, light colour, cameras, building shape.")
    return "\n".join(lines)


def vocabulary(factor):
    return VOCABULARY[factor]


def unbacked(plan, factor):
    return factor not in plan


def _check(name, f, value):
    return _integer(value, name, f[0], f[1]) if name in hw.INTEGER_FIELDS else _number(value, name, f[0], f[1])


def validate_plan(raw, mapped):
    if not isinstance(raw, dict) or not set(raw) <= set(FIELDS):
        raise WorldError("plan fields wrong")
    cited = {s["factor"] for s in mapped}
    plan = {}
    for name, f in FIELDS.items():
        if name not in raw:
            continue
        entry = raw[name]
        if name not in cited:
            raise WorldError("plan moved a field that no brief phrase cites")
        if not isinstance(entry, dict) or set(entry) != {"min", "max"}:
            raise WorldError("plan range wrong")
        low, high = _check(name, f, entry["min"]), _check(name, f, entry["max"])
        if low > high:
            raise WorldError("plan range reversed")
        plan[name] = {"min": low, "max": high}
    if not plan:
        raise WorldError("plan sets no field")
    return plan


def validate(raw):
    """Their validator decides. A failure carries no text from it, because its errors echo field names."""
    try:
        world = hw.validate(raw)
    except hw.WorldError:
        raise WorldError("world failed policy/highrise validation") from None
    if world["gust_duration_s"] > world["gust_period_s"]:
        raise WorldError("gusts overlap")
    return world


def expand(plan, seed):
    index = 0
    while True:
        rng = random.Random(f"{seed}/{index}")
        index += 1
        spec = {"schema": hw.SCHEMA}
        for name in FIELDS:
            low, high = (plan[name]["min"], plan[name]["max"]) if name in plan else GUIDE[name][:2]
            spec[name] = rng.randint(low, high) if name in hw.INTEGER_FIELDS else round(rng.uniform(low, high), 4)
        yield spec


def open_builder(out):
    import mujoco
    folder = Path(out) / "worlds"
    folder.mkdir(parents=True, exist_ok=True)

    def build(spec, index):
        world = validate(spec)
        try:
            mujoco.MjModel.from_xml_string(hw.build_xml(world))
        except ValueError:
            return None, "failed_mujoco_compile"
        path = folder / f"world_{index:03d}.json"
        path.write_text(json.dumps(world, indent=1, sort_keys=True, allow_nan=False))
        return {"path": str(path), "world_hash": hw.world_hash(world), **world}, None
    return build


def finish(worlds, plan, out):
    """Per field: the values sampled against the default range, so a reader sees what the brief moved."""
    table = {}
    for name in FIELDS:
        values = [r[name] for r in worlds]
        if not values:
            continue
        low, high = GUIDE[name][:2]
        mean = sum(values) / len(values)
        table[name] = {"default_range": [low, high], "plan_range": [plan[name]["min"], plan[name]["max"]] if name in plan else None,
                       "world_min": min(values), "world_mean": round(mean, 4), "world_max": max(values),
                       "moved": "default" if name not in plan else "above default" if mean > high else
                                "below default" if mean < low else "within default"}
    lines = [f"{'field':20} {'default':>16} {'worlds min..max':>20}  moved"]
    for name, row in table.items():
        lines.append(f"{name:20} {row['default_range'][0]:>7}..{row['default_range'][1]:<7} "
                     f"{row['world_min']:>9.3f}..{row['world_max']:<9.3f}  {row['moved']}")
    (Path(out) / "values.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return table
