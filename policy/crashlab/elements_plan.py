"""Scene elements in an LLM plan. The allowlist is SPECS in policy/highrise/elements.py, reached through world.py, and is passed in as E.

A plan holds, per allowlisted element type, a count range and number ranges only. Our code samples the elements, and world.py validates every one.
"""
NOTE = ("The controller knows nothing about scene elements, so it drives into them and most of these worlds are expected to fail. "
        "That is known in advance and is not a finding. Worlds with elements are labelled and stay out of headline numbers.")
PLACE = {"x_m": (0.2, 2.2), "below_top_m": (0.6, 2.8)}
MEANING = {
    "pane_grid": "glazing grid with its own pane size and joint depth",
    "ledge": "solid ledge across the glass",
    "sill": "shallow window sill",
    "fin": "vertical fin standing off the glass",
    "sign": "sign mounted on the glass",
    "balcony": "balcony slab",
    "frame_step": "raised frame or cladding step",
    "vent": "open vent that leaks suction",
    "corner": "the glass ends at a building corner",
    "setback": "the glass top ends at a terrace setback",
    "wet_patch": "local wet patch",
    "dirt_patch": "local dirty patch",
    "cradle": "moving maintenance cradle",
}


def token(kind):
    return f"element_{kind}"


def default_range(name, limits):
    lo, hi = limits
    if name in PLACE:
        return max(lo, PLACE[name][0]), min(hi, PLACE[name][1])
    span = hi - lo
    return lo + 0.1 * span, lo + 0.5 * span


def plan_schema(E):
    def bounds(name, limits):
        kind = "integer" if name in E.INTEGER_FIELDS else "number"
        limit = {"type": kind, "minimum": limits[0], "maximum": limits[1]}
        return {"type": "object", "additionalProperties": False, "required": ["min", "max"], "properties": {"min": limit, "max": limit}}
    types = {}
    for kind, spec in E.SPECS.items():
        count = {"type": "integer", "minimum": 1, "maximum": spec["cap"]}
        types[kind] = {"type": "object", "additionalProperties": False, "required": ["count"], "properties": {
            "count": {"type": "object", "additionalProperties": False, "required": ["min", "max"], "properties": {"min": count, "max": count}},
            "fields": {"type": "object", "additionalProperties": False, "properties": {n: bounds(n, f) for n, f in spec["fields"].items()}}}}
    return {"type": "object", "additionalProperties": False, "properties": types}


def _range(raw, is_int, lo, hi, error):
    if not isinstance(raw, dict) or set(raw) != {"min", "max"}:
        raise error("element_range_wrong")
    out = []
    for v in (raw["min"], raw["max"]):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise error("element_range_not_a_number")
        if is_int and type(v) is not int:
            raise error("element_range_not_an_integer")
        if not lo <= v <= hi:  # NaN fails this too
            raise error("element_range_over_limit")
        out.append(v)
    if out[0] > out[1]:
        raise error("element_range_reversed")
    return {"min": out[0], "max": out[1]}


def validate(raw, E, error):
    """`error` takes a fixed code. Nothing from the plan reaches an error message."""
    if not isinstance(raw, dict) or not raw:
        raise error("elements_wrong")
    plan, total = {}, 0
    for kind, entry in raw.items():
        if type(kind) is not str or kind not in E.SPECS:
            raise error("element_type_unknown")
        spec = E.SPECS[kind]
        if not isinstance(entry, dict) or "count" not in entry or not set(entry) <= {"count", "fields"}:
            raise error("element_entry_wrong")
        count = _range(entry["count"], True, 1, spec["cap"], error)
        total += count["max"]
        fields = entry.get("fields", {})
        if not isinstance(fields, dict) or not set(fields) <= set(spec["fields"]):
            raise error("element_field_unknown")
        plan[kind] = {"count": count, "fields": {n: _range(r, n in E.INTEGER_FIELDS, *spec["fields"][n], error) for n, r in fields.items()}}
    if total > E.MAX_ELEMENTS:
        raise error("too_many_elements")
    return plan


def sample(plan, E, rng):
    """A list of element specs. world.py validates the result, and a start pose that an element blocks gets resampled by the caller."""
    out = []
    for kind, entry in plan.items():
        spec = E.SPECS[kind]["fields"]
        for _ in range(rng.randint(entry["count"]["min"], entry["count"]["max"])):
            element = {"type": kind}
            for name, limits in spec.items():
                chosen = entry["fields"].get(name)
                if name in E.INTEGER_FIELDS:
                    low, high = (chosen["min"], chosen["max"]) if chosen else limits
                    v = rng.randint(low, high)
                    if kind == "corner" and name == "side" and v == 0:
                        v = 1
                    element[name] = v
                else:
                    low, high = (chosen["min"], chosen["max"]) if chosen else default_range(name, limits)
                    element[name] = min(limits[1], max(limits[0], round(rng.uniform(low, high), 4)))
            out.append(element)
    return out


def catalog_lines(E):
    lines = [f"Scene elements. Add one only when the text asks for that feature. A plan entry gives a count range and, if the text says so, number ranges. {NOTE}"]
    for kind, spec in E.SPECS.items():
        fields = ", ".join(f"{n} {f[0]} to {f[1]}" for n, f in spec["fields"].items())
        lines.append(f"- {kind}: {MEANING[kind]}. At most {spec['cap']}. x_m runs from the left edge of the work area, below_top_m down from its top. Fields: {fields}.")
    return lines


def describe(elements):
    counts = {}
    for e in elements:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
