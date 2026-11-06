"""Turns a company's partial limits into a full gate spec. Fields the company does not name keep the schema range.

"wind_ms" is shorthand: it sets the same limit on steady_wind_ms and gust_speed_ms, so a wind limit also holds for gusts.
The limits are the company's choice. A world inside them is not shown to be physically possible.
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate as G

W = G.W
NOMINAL = HERE.parent / "highrise" / "worlds" / "nominal.json"
ALIASES = {"wind_ms": ("steady_wind_ms", "gust_speed_ms")}


def expand(partial):
    if not isinstance(partial, dict):
        raise G.Rejected("bad_limits", "The limits must be an object of field names and [low, high] pairs.")
    out = {}
    for name, row in partial.items():
        targets = ALIASES.get(name) or ((name,) if name in W.FIELDS else None)
        if targets is None:
            raise G.Rejected("bad_limits", "One limit names a field that the world schema does not have.")
        for target in targets:
            if target in out:
                raise G.Rejected("bad_limits", f"The limits set {target} twice.")
            out[target] = row
    return out


def build(bounty_id, partial, salt_hex):
    """Returns (spec, narrowed field names). G.check_spec refuses limits outside the schema, or limits that exclude the reference world."""
    named = expand(partial)
    limits = {name: named.get(name, list(bounds)) for name, bounds in W.FIELDS.items()}
    spec = {"schema": G.SPEC_SCHEMA, "bounty_id": bounty_id, "limits": limits, "reference_world": W.load(NOMINAL),
            "salt_commit": hashlib.sha256(bytes.fromhex(salt_hex)).hexdigest(), "frozen": G.current_frozen()}
    G.check_spec(spec)
    return spec, sorted(named)
