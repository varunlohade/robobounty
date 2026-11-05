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


def _recorded(prompt, schema):
    path = Path(os.environ["CRASHLAB_RECORDED_REPLIES"]) / ("scenarios.json" if "groups" in schema["properties"] else "brief.json")
    return json.loads(path.read_text()) if path.exists() else llm._claude(prompt, schema)


def plan(req):
    t0 = time.perf_counter()
    try:
        words = brief.words_of(req["text"])
        raw = llm.complete_json(brief.prompt_for(plugin, words), brief.full_schema(plugin))
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


def build(req):
    t0 = time.perf_counter()
    hw = plugin.hw
    try:
        chosen = plugin.validate_plan(req["plan"], [{"factor": f} for f in req["plan"]]) if req["plan"] else {}
        worlds, dropped = brief.build_batch(plugin, chosen, 1, req["seed"], req["out"])
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
