"""Reads the gate's own constants and builds a spec, in its own process: bounty_job.py <constants|spec>, JSON on stdin and stdout.

It stays a separate process, so the long-lived server always sees the gate and sim that are on disk now.
"""
import contextlib
import hashlib
import json
import sys
from pathlib import Path

POLICY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POLICY / "bounty"))
sys.path.insert(0, str(POLICY / "highrise"))
import gate as G
import world as W


def constants(_):
    return {"reruns": G.RERUNS, "repeat_need": getattr(G, "REPEAT_NEED", G.RERUNS), "max_world_bytes": G.MAX_SUBMISSION_BYTES, "jitter_share": G.JITTER_SHARE,
            "reference_keep": G.REFERENCE_KEEP, "not_checked": G.NOT_CHECKED, "human_cap_label": getattr(G, "HUMAN_CAP_LABEL", None)}


def limits_for(groups, nominal):
    """Each field spans the moderate ranges, the plan's ranges and nominal. A field with neither stays at the schema limits."""
    moderate = json.loads((POLICY / "highrise" / "worlds" / "moderate_ranges.json").read_text())
    known = {**moderate["ranges"], "gust_count": moderate["gust_count"]}
    out, narrowed = {}, []
    for name, bounds in W.FIELDS.items():
        spans = [known[name]] if name in known else []
        spans += [(g["ranges"][name]["min"], g["ranges"][name]["max"]) for g in groups if name in g["ranges"]]
        if spans:
            narrowed.append(name)
            low, high = min(s[0] for s in spans), max(s[1] for s in spans)
            out[name] = [max(bounds[0], min(low, nominal[name])), min(bounds[1], max(high, nominal[name]))]
        else:
            out[name] = list(bounds)
    return out, narrowed


def spec(req):
    nominal = W.load(POLICY / "highrise" / "worlds" / "nominal.json")
    limits, narrowed = limits_for(req["groups"], nominal)
    if req.get("schema_limits"):  # the widest a company can set: only for local checks, whose fixture worlds sit outside the moderate ranges
        limits, narrowed = {name: list(bounds) for name, bounds in W.FIELDS.items()}, []
    body = {"schema": G.SPEC_SCHEMA, "bounty_id": 1, "limits": limits, "reference_world": nominal, "salt_commit": hashlib.sha256(bytes.fromhex(req["salt"])).hexdigest(), "frozen": G.current_frozen()}
    if req.get("preview"):
        return {"limits": limits, "narrowed": narrowed}
    Path(req["out"]).write_text(json.dumps(body, indent=1))
    return {"spec_hash": "0x" + G.sha256_hex(G.canonical(body)), "limits": limits, "narrowed": narrowed}


def main():
    req = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        reply = {"constants": constants, "spec": spec}[sys.argv[1]](req)
    json.dump(reply, sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
