"""One LLM or build step, run in its own process: plan_job.py <plan|build|scenarios>, with a JSON request on stdin and a JSON reply on stdout.

It stays a separate process because policy/crashlab and policy/highrise each have a module named world.
Chat text arrives on stdin and goes only to the LLM layer. brief.py and scenarios.py validate what comes back.
CRASHLAB_RECORDED_REPLIES names a folder of stored LLM replies, for checks. The replies pass the same validators. A reply missing from the folder is a live call.
"""
import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crashlab"))
import brief
import brief_highrise as plugin
import llm
import mujoco
import scenarios
from scene import SceneError

INSTRUCTION_REASONS = {"code_or_instructions", "file_or_secret_request"}
FOLLOW_UP = "This message changes a world that already exists."


def _recorded(prompt, schema):
    folder = Path(os.environ["CRASHLAB_RECORDED_REPLIES"])
    path = folder / ("scenarios.json" if "groups" in schema["properties"] else "followup.json" if FOLLOW_UP in prompt and (folder / "followup.json").exists() else "brief.json")
    return json.loads(path.read_text()) if path.exists() else llm._claude(prompt, schema)


def follow_up_rules(world):
    values = ", ".join(f"{k} {v}" for k, v in world.items() if k in plugin.FIELDS)
    return f"""

{FOLLOW_UP} The numbered words above are only this message, and the current values are data.
Current values: {values}. Scene elements: {len(world.get("elements", []))}.
Set a min and a max only for the fields this message asks to change, and leave out every other field.
A relative word such as stronger, wetter or higher means a range past the current value, on the side the word asks for, inside the limits."""


def plan(req):
    t0 = time.perf_counter()
    try:
        words = brief.words_of(req["text"])
        prompt = brief.prompt_for(plugin, words) + (follow_up_rules(req["current"]) if req.get("current") else "")
        raw = llm.complete_json(prompt, brief.full_schema(plugin))
        seconds = round(time.perf_counter() - t0, 1)
        brief._check_top(raw)
        mapped = brief._spans(raw["mapped"], "factor", plugin.FACTORS, len(words))
        unbuildable = brief._spans(raw["unbuildable"], "reason", brief.REASONS, len(words))
        # A brief can name no value at all, such as "window robot for towers in Dubai". The planner calls that nothing_buildable, and the defaults stand.
        if raw["verdict"] == "reject" and raw["reject_reason"] != "nothing_buildable":
            raise brief.Rejected(f"planner_{raw['reject_reason']}")
        chosen = plugin.validate_plan(raw["plan"], mapped) if raw["verdict"] == "build" and raw["plan"] else {}
        # Text that is only instructions is not a brief.
        if not chosen and {s["reason"] for s in unbuildable} & INSTRUCTION_REASONS:
            raise brief.Rejected("planner_nothing_buildable")
        return {"ok": True, "plan": chosen, "seconds": seconds, **brief.account(plugin, words, mapped, unbuildable)}
    except brief.Rejected as e:
        return {"ok": False, "rejection": str(e), "seconds": round(time.perf_counter() - t0, 1)}
    except SceneError:
        return {"ok": False, "rejection": "plan_failed_validation", "seconds": round(time.perf_counter() - t0, 1)}
    except llm.LLMError as e:
        return {"ok": False, "rejection": f"llm_{e}", "seconds": round(time.perf_counter() - t0, 1)}


class KeepBase:
    """A follow-up samples only the fields it changed. Every other value comes from the current world, so a dropped sample or an integer draw cannot move it."""
    open_builder = staticmethod(plugin.open_builder)

    def __init__(self, base, changed):
        self.base, self.changed = base, changed

    def expand(self, plan, seed):
        for spec in plugin.expand(plan, seed):
            yield {**self.base, **{k: spec[k] for k in self.changed}, "schema": spec["schema"]}


def build(req):
    t0 = time.perf_counter()
    hw = plugin.hw
    try:
        chosen = plugin.validate_plan(req["plan"], [{"factor": f} for f in req["plan"]]) if req["plan"] else {}
        maker = KeepBase(req["base"], req["changed"]) if req.get("base") else plugin
        worlds, dropped = brief.build_batch(maker, chosen, 1, req["seed"], req["out"])
    except SceneError:
        return {"ok": False, "rejection": "plan_failed_validation"}
    if not worlds:
        return {"ok": False, "rejection": "no_world_compiled", "dropped": dropped}
    path = worlds[0]["path"]
    world = hw.load(path)
    xml = hw.build_xml(world)
    model = mujoco.MjModel.from_xml_string(xml)
    area = hw.area(world)
    density, dew = hw.air(world)
    top = area["z1"]
    ledge_z = top - world["ledge_below_top_m"]
    return {"ok": True, "path": path, "world": world, "hash": hw.world_hash(world), "xml": xml, "area": area, "moved": sorted(chosen),
            "seconds": round(time.perf_counter() - t0, 2),
            "facts": {"bodies": model.nbody, "geoms": model.ngeom, "joints_qpos": model.nq, "friction": round(hw.friction(world), 3),
                      "air_density": round(density, 3), "dew_point_c": round(dew, 1), "wetness_with_condensation": round(hw.effective_wetness(world), 3),
                      "mullions": len(hw.mullion_xs(world)), "floor_joints": len(hw.transom_zs(world)),
                      "ledge_in_work_area": area["z0"] <= ledge_z <= area["z1"], "m_below_roof": world["drop_below_roof_m"]}}


def propose(req):
    return scenarios.run(req["text"], req["out"], req["seed"])


def main():
    req = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        if os.environ.get("CRASHLAB_RECORDED_REPLIES"):
            llm.BACKENDS["recorded"] = _recorded
            os.environ["CRASHLAB_LLM"] = "recorded"
        reply = {"plan": plan, "build": build, "scenarios": propose}[sys.argv[1]](req)
    json.dump(reply, sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
