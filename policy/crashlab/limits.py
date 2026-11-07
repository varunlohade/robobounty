"""Operating limits: where a company says its robot must work, per pack. Standard library only, so every Python here can import it. Results are simulated.

A factor reads one number from a world. Its allowed range is what the pack's physics accepts, and its low and high are the company's limits, edited through set_limits.
Scenarios stay inside the limits, and one outside is dropped with a reason. A bounty's ranges come from a campaign's own worlds, so they stay inside too.
Coverage counts how much of each range the campaign's finished runs touched. It says tested. It never says safe.
"""
import copy
import json
from pathlib import Path

BANDS = 10
ENDED = ("passed", "failed", "stuck", "held")
FAILED = ("failed", "stuck")
LIMITS_FILE = "limits.json"
COVERAGE_NOTE = "Tested means a finished run touched that part of the range. It does not mean the robot is safe there. Not checked against real hardware."
DEFAULTS_NOTE = "These are the default limits. Say a new range in the chat, for example: set the wind limit to 0 to 12."
CODES = {"unknown_factor": "That is not a factor in this robot's limits.", "bad_args": "A limit needs a factor, a low number and a high number.", "low_above_high": "The low number must be below the high number.",
         "out_of_range": "That range is outside what this robot's physics can model."}
# Solids a robot must step over, with the field that sets each height and that field's range in world.py. A taller box is a thing to walk around, so it stays out.
STEP_OVER = {"box": ("sz", 0.02, 0.5), "cable_tray": ("height", 0.03, 0.2), "valve": ("size", 0.05, 0.2), "grating": ("bar_height", 0.005, 0.1)}


def _factor(key, label, words, unit, allowed, default, step):
    return {"key": key, "label": label, "words": words, "unit": unit, "allowed": list(allowed), "default": list(default), "step": step}


FACTORS = {
    "window": [
        _factor("wind", "Wind", "wind", "m/s", (0.0, 25.0), (0.0, 15.0), 0.5),
        _factor("gust", "Gust", "gust", "m/s", (0.0, 60.0), (0.0, 30.0), 1.0),
        _factor("wetness", "Wet glass", "wet glass", "", (0.0, 1.0), (0.0, 1.0), 0.05),
        _factor("dust", "Dust", "dust", "g/m2", (0.0, 60.0), (0.0, 30.0), 1.0),
        _factor("temperature", "Temperature", "temperature", "C", (-20.0, 50.0), (-10.0, 45.0), 1.0),
        _factor("suction", "Suction", "suction", "Pa", (500.0, 5000.0), (1500.0, 4500.0), 50.0),
        _factor("leak", "Seal leak", "seal leak", "mm2", (20.0, 2000.0), (100.0, 800.0), 20.0),
    ],
    "inspection": [
        _factor("friction", "Floor grip", "floor grip", "", (0.02, 2.0), (0.15, 2.0), 0.01),
        _factor("obstacle", "Obstacle height", "obstacle height", "m", (0.0, 0.5), (0.0, 0.25), 0.005),
        _factor("step", "Step height", "step height", "m", (0.0, 0.5), (0.0, 0.25), 0.005),
        _factor("payload", "Payload", "payload", "kg", (0.0, 40.0), (0.0, 25.0), 0.5),
    ],
}
WINDOW_FIELDS = {"wind": ("wind", "steady_ms"), "gust": ("wind", "gust_ms"), "wetness": ("weather", "wetness"), "dust": ("weather", "dust_gm2"), "temperature": ("weather", "temperature_c"), "suction": ("robot", "suction_pa"), "leak": ("robot", "seal_leak_mm2")}


def factors(pack):
    """A pack with no factors yet has no limits: nothing is dropped, and coverage is empty."""
    return FACTORS.get(pack, [])


def factor(pack, key):
    return next(f for f in factors(pack) if f["key"] == key)


def defaults(pack):
    return {f["key"]: list(f["default"]) for f in factors(pack)}


def catalog_row(pack):
    """set_limits as one more typed function, in the shape the world functions use."""
    return {"name": "set_limits", "rerun": False, "note": "Sets where the company says this robot must work. Changes no world and starts no run.",
            "args": {"type": "object", "required": ["factor", "low", "high"], "additionalProperties": False,
                     "properties": {"factor": {"type": "string", "enum": [f["key"] for f in factors(pack)]}, "low": {"type": "number"}, "high": {"type": "number"}}}}


def set_limits(pack, current, args):
    """Untrusted input. Returns {"result", "limits"}: result is ok or cannot_set:<code>, and limits never changes on a refusal."""
    refused = lambda code: {"result": f"cannot_set:{code}", "limits": current}
    if not isinstance(args, dict) or set(args) != {"factor", "low", "high"}:
        return refused("bad_args")
    if not isinstance(args["factor"], str) or args["factor"] not in current:
        return refused("unknown_factor")
    low, high = args["low"], args["high"]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) for v in (low, high)):
        return refused("bad_args")
    if low >= high:
        return refused("low_above_high")
    lo, hi = factor(pack, args["factor"])["allowed"]
    if low < lo or high > hi:
        return refused("out_of_range")
    return {"result": "ok", "limits": {**current, args["factor"]: [float(low), float(high)]}}


def refusal_words(result):
    return CODES.get(result.split(":", 1)[-1], "That limit was refused.")


def _obstacle_height(obj):
    if obj["kind"] == "pipe":
        return 2.0 * obj["radius"] if obj.get("clearance", 0.05) == 0.0 else None  # A pipe with a gap under it is overhead, not a thing on the floor.
    rule = STEP_OVER.get(obj["kind"])
    if not rule:
        return None
    height = obj.get(rule[0], {"cable_tray": 0.08, "valve": 0.08, "grating": 0.02}.get(obj["kind"]))
    return height if height <= rule[2] or obj["kind"] != "box" else None


def _grips(world):
    """Every surface the robot may walk on, with the grip each has."""
    out = [(None, world["floor"]["friction"])]
    for o in world["objects"]:
        if o["kind"] == "wet_patch":
            out.append((o, o.get("friction", 0.05)))
        elif "friction" in o:
            out.append((o, o["friction"]))
    return out


def value(pack, key, world):
    """One factor's value in a world. A harsher local thing counts: the wettest patch, the lowest grip, the tallest thing to step over."""
    if pack == "window":
        if key == "wetness":
            return max([world["weather"]["wetness"]] + [o["props"]["wetness"] for o in world["objects"] if o["kind"] == "wet_patch"])
        section, field = WINDOW_FIELDS[key]
        return world[section][field]
    if key == "friction":
        return min(grip for _, grip in _grips(world))
    if key == "payload":
        return world["payload"]["mass_kg"]
    if key == "step":
        return max([o["rise"] for o in world["objects"] if o["kind"] == "steps"], default=0.0)
    return max([h for h in map(_obstacle_height, world["objects"]) if h is not None], default=0.0)


def with_value(pack, key, world, v):
    """A copy of the world with one factor at v, on whatever sets it. The caller checks the result through the pack's validate. A floor value on an object uses the smallest size that object allows."""
    w = copy.deepcopy(world)
    if pack == "window":
        if key == "wetness":
            patches = [o for o in w["objects"] if o["kind"] == "wet_patch"]
            if patches and max(o["props"]["wetness"] for o in patches) > w["weather"]["wetness"]:
                max(patches, key=lambda o: o["props"]["wetness"])["props"]["wetness"] = v
                return w
        section, field = WINDOW_FIELDS[key]
        w[section][field] = v
    elif key == "friction":
        target = min(_grips(w), key=lambda row: row[1])[0]
        if target is None:
            w["floor"]["friction"] = v
        else:
            target["friction"] = v
    elif key == "payload":
        w["payload"]["mass_kg"] = v
    elif key == "step":
        tall = max((o for o in w["objects"] if o["kind"] == "steps"), key=lambda o: o["rise"], default=None)
        if tall:
            tall["rise"] = max(v, 0.01)
    else:
        tall = max((o for o in w["objects"] if _obstacle_height(o) is not None), key=_obstacle_height, default=None)
        if tall and tall["kind"] == "pipe":
            tall["radius"] = max(v / 2.0, 0.01)
        elif tall:
            field, low, _ = STEP_OVER[tall["kind"]]
            tall[field] = max(v, low)
    return w


def plain(v, f=None):
    """A number as a person writes it."""
    text = f"{round(v, 4):g}" if abs(v) < 10000 else f"{v:.0f}"
    return f"{text} {f['unit']}" if f and f["unit"] else text


def outside(pack, world, limits):
    """Each factor of this world that is outside its limit."""
    out = []
    for f in factors(pack):
        low, high = limits[f["key"]]
        v = value(pack, f["key"], world)
        if not low <= v <= high:
            side = f"above the high limit of {plain(high, f)}" if v > high else f"below the low limit of {plain(low, f)}"
            out.append({"factor": f["key"], "value": v, "low": low, "high": high, "words": f"{f['label']} {plain(v, f)} is {side}."})
    return out


def prompt_text(pack, limits):
    """The limits for the scenario agent's prompt. Code drops anything outside, whatever the AI writes."""
    lines = [f"- {f['words']}: {plain(limits[f['key']][0])} to {plain(limits[f['key']][1], f)}" for f in factors(pack)]
    return "Operating limits. Each world must stay inside these, and code drops a world outside them. Spread the values across these ranges:\n" + "\n".join(lines)


def load(folder, pack):
    """A session's limits. Defaults until someone sets them."""
    path = Path(folder) / LIMITS_FILE
    try:
        stored = json.loads(path.read_text())
        return {**defaults(pack), **{k: v for k, v in stored.items() if k in defaults(pack)}}
    except (OSError, ValueError):
        return defaults(pack)


def save(folder, limits):
    path = Path(folder) / LIMITS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(limits))
    tmp.replace(path)


def _band(v, low, high):
    return min(BANDS - 1, max(0, int((v - low) / (high - low) * BANDS)))


def coverage(pack, plan, rows, base=None):
    """For each factor, how much of its limit range the finished runs touched, from the plan's stored limits. rows are the grid's. A held-back world has not run, so it does not count."""
    limits, stored = plan.get("limits"), bool(plan.get("limits"))
    limits = limits or defaults(pack)
    base = base or plan.get("base_world")
    by_index = {r["index"]: r for r in rows}
    ran = [(w, by_index[w["index"]]) for w in plan["worlds"] if not w["held_back"] and by_index.get(w["index"], {}).get("status") in ENDED]
    out, touched_total = [], 0
    for f in factors(pack):
        low, high = limits[f["key"]]
        start = value(pack, f["key"], base) if base else None
        values, bands, moved, outside_n = [], [{"runs": 0, "failed": 0, "moved": False} for _ in range(BANDS)], 0, 0
        for w, row in ran:
            v = value(pack, f["key"], w["world"])
            if not low <= v <= high:
                outside_n += 1
                continue
            values.append(v)
            band = bands[_band(v, low, high)]
            band["runs"] += 1
            if start is not None and v != start:
                moved += 1
                band["moved"] = True
                band["failed"] += row["status"] in FAILED
        touched = sum(b["runs"] > 0 for b in bands)
        touched_total += touched
        name = f"{f['label']}"
        if not values:
            words = f"{name}: no finished run yet."
        elif len(set(values)) == 1:
            words = f"{name}: not varied. Every run used {plain(values[0], f)}, in a limit of {plain(low)} to {plain(high, f)}."
        else:
            words = f"{name}: tested {plain(min(values))} to {plain(max(values), f)} of {plain(low)} to {plain(high, f)}, in {touched} of {BANDS} bands."
        out.append({"key": f["key"], "label": f["label"], "unit": f["unit"], "low": low, "high": high, "base": start, "tested_low": min(values, default=None), "tested_high": max(values, default=None), "values": sorted(set(values)),
                    "bands_touched": touched, "bands": BANDS, "band_rows": bands, "worlds_moved": moved, "runs": len(values), "outside": outside_n, "words": words})
    return {"pack": pack, "factors": out, "runs": len(ran), "bands_touched": touched_total, "bands_total": BANDS * len(factors(pack)), "limits_stored": stored, "limits": limits, "dropped": plan.get("off_limits", []), "note": COVERAGE_NOTE,
            "limits_words": "Limits stored with this campaign." if stored else "This campaign is from before limits, so these are today's default limits."}
