"""The look: scenery the viewer draws. It feeds nothing to physics. It stays out of world.json and world.py, which the run and the bounty gate hash.

validate() is the only way into a look. It takes typed values and refuses anything else, so no CSS, shader text or code from a message or from the AI reaches the view.
parse() is the simple parser. The server uses it only when the AI call fails.
"""
import re

COLOUR_FIELDS = ("building", "glass_tint", "frames")
TIMES = ("noon", "dusk", "night")
CITIES = ("default", "dubai", "generic_desert", "generic_coast")
FIELDS = (*COLOUR_FIELDS, "time", "fog", "city", "rain", "dust_air")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# The fields back to how the scene was built: "default" for a colour, "clear" also for the glass.
_RESET = {"building": {"default"}, "frames": {"default"}, "glass_tint": {"default", "clear"}}
NAMES = {
    "black": "#0a0a0a", "white": "#f7f7f5", "grey": "#808285", "gray": "#808285", "bronze": "#8c6239", "blue": "#1f5fbf", "green": "#2e8b57", "gold": "#d4a017", "teal": "#008080", "red": "#c62828",
    "orange": "#e8741c", "yellow": "#f2c81e", "pink": "#e75480", "purple": "#6a3fa0", "brown": "#6b4423", "navy": "#14284b", "silver": "#b8bcc2", "steel": "#8a9097",
}
# More shades for naming a colour in the chat. The parser does not read these.
_SHADES = {"bronze": "#cd7f32", "gold": "#ffd700", "dark red": "#8b0000", "dark blue": "#0b2a6b", "dark green": "#0b4f2a", "dark grey": "#3a3d40", "light grey": "#c8cacc", "sky blue": "#87ceeb", "cyan": "#00bcd4", "magenta": "#c2188b"}
_FIELD_WORDS = {"building": "Building", "glass_tint": "Glass tint", "frames": "Frames"}
_CITY_WORDS = {"default": "City is back to the default scenery.", "dubai": "Scenery look named Dubai. Not the real city.",
               "generic_desert": "Scenery look named desert city. Not a real place.", "generic_coast": "Scenery look named coast city. Not a real place."}


class LookError(Exception):
    """The message is a fixed code. It never carries the value it refused."""


def validate(args):
    """A patch of checked values. A colour field set back to its default becomes None, which removes it from the look."""
    if not isinstance(args, dict):
        raise LookError("not_an_object")
    patch = {}
    for key, v in args.items():
        if key not in FIELDS:
            raise LookError("unknown_field")
        if key in COLOUR_FIELDS:
            if isinstance(v, str) and v in _RESET[key]:
                patch[key] = None
            elif isinstance(v, str) and _HEX.match(v):
                patch[key] = v.lower()
            else:
                raise LookError("bad_colour")
        elif key == "time" and v in TIMES and isinstance(v, str):
            patch[key] = v
        elif key == "city" and v in CITIES and isinstance(v, str):
            patch[key] = v
        elif key == "fog" and type(v) is int and 0 <= v <= 3:
            patch[key] = v
        elif key in ("rain", "dust_air") and type(v) is bool:
            patch[key] = v
        else:
            raise LookError("bad_value")
    return patch


def merged(look, patch):
    out = {**look, **patch}
    return {k: v for k, v in out.items() if v is not None}


def colour_name(hex_value):
    """The nearest plain colour word, or the hex when no word is close."""
    rgb = [int(hex_value[i:i + 2], 16) for i in (1, 3, 5)]
    best, dist = None, 1e9
    for name, value in [*NAMES.items(), *_SHADES.items()]:
        if name == "gray":
            continue
        d = sum((a - int(value[i:i + 2], 16)) ** 2 for a, i in zip(rgb, (1, 3, 5))) ** 0.5
        if d < dist:
            best, dist = name, d
    return best if dist <= 48 else hex_value.lower()


def words(patch, before, has_world):
    """Plain chat lines from checked values only."""
    lines = []
    for key in COLOUR_FIELDS:
        if key not in patch:
            continue
        name, v = _FIELD_WORDS[key], patch[key]
        be = "are" if key == "frames" else "is"
        if v is None:
            lines.append(f"{name} {be} back to how the scene was built." if before.get(key) else f"{name} {be} already how the scene was built.")
        elif before.get(key) == v:
            lines.append(f"{name} {be} already {colour_name(v)}.")
        else:
            verb = f"{be} now" if has_world else "will be"
            lines.append(f"{name} {verb} {colour_name(v)}{'' if has_world else ' when the world loads'}.")
    if "time" in patch:
        lines.append(f"Time is now {patch['time']}." if has_world else f"Time will be {patch['time']} when the world loads.")
    if "fog" in patch:
        lines.append("Fog is off." if patch["fog"] == 0 else f"Fog is now level {patch['fog']} of 3.")
    if "city" in patch:
        lines.append(_CITY_WORDS[patch["city"]])
    # The view does not draw these two yet, so the chat does not claim it does.
    if "rain" in patch:
        lines.append("Rain is saved with this look. The view does not draw it yet." if patch["rain"] else "Rain is off.")
    if "dust_air" in patch:
        lines.append("Dust in the air is saved with this look. The view does not draw it yet." if patch["dust_air"] else "Dust in the air is off.")
    return lines


# The simple parser. It only knows the words below, and a word it does not know stays in the leftover.
_C = "|".join(NAMES)
_BUILDING = r"(?:building|tower|facade|cladding)"
_GLASS = r"(?:glass|windows?|panes?)"
_FRAMES = r"(?:frames?|mullions?)"
_VERB = r"(?:make|turn|paint|set|change|colou?r)"
_BLOCK = re.compile(r"^\s*(?:what|why|how|which|is|are|does|did|if|when|whether)\b|\b(?:not|don'?t|never|without)\b", re.I)
_FILLER = set("a an the it to be is please can could would you i we want like let us me now make turn paint set change colour color give some with have in at of look city scene sky all so".split())


def _colour_rules(field, subject):
    return ((rf"\b{_VERB}\s+(?:the\s+)?{subject}\s+(?:to\s+|be\s+)?({_C})\b(?!\s+of)", field),
            (rf"\b({_C})\s+{subject}\b", field), (rf"\b{subject}\s+(?:is\s+|to\s+)?({_C})\b(?!\s+of)", field))


_RULES = (
    *_colour_rules("building", _BUILDING), *_colour_rules("glass_tint", _GLASS), *_colour_rules("frames", _FRAMES),
    (rf"\b(?:make|paint|turn)\s+it\s+({_C})\b", "building"),
    (r"\bclear\s+glass\b", ("glass_tint", "clear")), (r"\bglass\s+clear\b(?!\s+of)", ("glass_tint", "clear")),
    (r"\b(?:noon|midday|daytime)\b", ("time", "noon")), (r"\b(?:dusk|sunset|twilight|evening)\b", ("time", "dusk")), (r"\b(?:night\s?time|night|midnight)\b", ("time", "night")),
    (r"\bno\s+fog\b", ("fog", 0)), (r"\b(?:light|thin)\s+fog\b", ("fog", 1)), (r"\b(?:thick|heavy|dense)\s+fog\b", ("fog", 3)),
    (r"\bfog\s+(?:level\s+|to\s+)?([0-3])\b", "fog"), (r"\b(?:foggy|fog)\b(?!\s+\d)", ("fog", 2)),
    (r"\bin\s+dubai\b|\bdubai\b", ("city", "dubai")), (r"\bdesert\s+city\b|\bgeneric\s+desert\b", ("city", "generic_desert")), (r"\bcoast(?:al)?\s+city\b|\bgeneric\s+coast\b", ("city", "generic_coast")), (r"\bdefault\s+city\b", ("city", "default")),
    (r"\bno\s+rain\b|\bstop\s+the\s+rain\b", ("rain", False)), (r"\b(?:make\s+it\s+rain|rainy|raining|rain)\b", ("rain", True)),
    (r"\bno\s+dust\s+in\s+the\s+air\b", ("dust_air", False)), (r"\bdust\s+in\s+the\s+air\b|\bdusty\s+air\b|\bairborne\s+dust\b", ("dust_air", True)),
)


def parse(text):
    """(look patch, leftover text). The leftover keeps the user's words. Clauses with nothing the parser knows come back whole."""
    patch, kept = {}, []
    for clause in re.split(r"[,;.!?\n]+|\band\b|\bthen\b", text, flags=re.I):
        if not clause.strip():
            continue
        if _BLOCK.search(clause):
            kept.append(clause.strip())
            continue
        rest = clause
        for pattern, what in _RULES:
            def take(m, what=what):
                if isinstance(what, tuple):
                    patch[what[0]] = what[1]
                elif what == "fog":
                    patch["fog"] = int(m.group(1))
                else:
                    patch[what] = NAMES[m.group(1).lower()]
                return " "
            rest = re.sub(pattern, take, rest, flags=re.I)
        tokens = re.findall(r"[a-z0-9']+", rest.lower())
        if any(t not in _FILLER for t in tokens):
            kept.append(" ".join(rest.split()))
    if not patch:
        return {}, " ".join(text.split())
    return validate(patch), ". ".join(kept)
