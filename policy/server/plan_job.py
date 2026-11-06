"""One LLM or build step, run in its own process: plan_job.py <route|plan|build|scenarios>, with a JSON request on stdin and a JSON reply on stdout.

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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brief
import brief_highrise as plugin
import engine
import llm
import mujoco
import scenarios
import scenarios_pack
from scene import SceneError

INSTRUCTION_REASONS = {"code_or_instructions", "file_or_secret_request"}
FOLLOW_UP = "This message changes a world that already exists."
ROUTE_MODEL = os.environ.get("CRASHLAB_ROUTE_MODEL", "claude-opus-5-5")  # Pinned. The route check scored this model on policy/server/check_look.py.
ROUTE_TIMEOUT_S = 90
_route_text = ""


def _recorded(prompt, schema):
    folder = Path(os.environ["CRASHLAB_RECORDED_REPLIES"])
    # Stored route replies are by exact message. Any other message fails like a dead AI call, so a check never makes a live call here.
    if "calls" in schema["properties"]:
        stored = json.loads((folder / "route.json").read_text()) if (folder / "route.json").exists() and not os.environ.get("CRASHLAB_LIVE_ROUTE") else {}
        if _route_text not in stored:
            if os.environ.get("CRASHLAB_LIVE_ROUTE"):
                return llm._claude(prompt, schema)
            raise llm.LLMError("no_stored_route")
        return stored[_route_text]
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


def route(req):
    """The AI chooses engine functions for one message. The server checks the reply with engine.check_reply before anything happens."""
    global _route_text
    _route_text = req["text"]
    t0 = time.perf_counter()
    os.environ["CRASHLAB_LLM_MODEL"] = ROUTE_MODEL
    llm.TIMEOUT_S = ROUTE_TIMEOUT_S
    try:
        raw = llm.complete_json(engine.prompt(req["text"], req.get("look"), req.get("has_world")), engine.reply_schema())
    except llm.LLMError as e:
        return {"ok": False, "rejection": f"llm_{e}", "seconds": round(time.perf_counter() - t0, 1)}
    return {"ok": True, "reply": raw, "seconds": round(time.perf_counter() - t0, 1), "model": ROUTE_MODEL}


AGENT_TIMEOUT_S = 200


def agent(req):
    """One model call for policy/highrise5/agent5.py. The reply is data, and engine5 checks every call in it. A check reads stored replies from agent5.json, by message and round."""
    t0 = time.perf_counter()
    folder = os.environ.get("CRASHLAB_RECORDED_REPLIES")
    if folder and not os.environ.get("CRASHLAB_LIVE_ROUTE"):
        path = Path(folder) / "agent5.json"
        stored = json.loads(path.read_text()) if path.exists() else {}
        if req["text"] not in stored:
            return {"ok": False, "rejection": "llm_no_stored_reply", "seconds": 0.0}
        rounds = stored[req["text"]]
        return {"ok": True, "reply": rounds[req["round"] - 1] if req["round"] <= len(rounds) else {"calls": [], "say": ""}, "seconds": 0.0}
    llm.use_model(req["model"])
    llm.TIMEOUT_S = AGENT_TIMEOUT_S
    try:
        raw = llm.complete_json(req["prompt"], req["schema"])
    except llm.LLMError as e:
        return {"ok": False, "rejection": f"llm_{e}", "seconds": round(time.perf_counter() - t0, 1)}
    if os.environ.get("CRASHLAB_SAVE_AGENT"):  # A check keeps the replies of a live run, so later runs of it need no AI.
        path = Path(os.environ["CRASHLAB_SAVE_AGENT"])
        kept = json.loads(path.read_text()) if path.exists() else {}
        kept.setdefault(req["text"], []).append(raw)
        path.write_text(json.dumps(kept, indent=1))
    return {"ok": True, "reply": raw, "seconds": round(time.perf_counter() - t0, 1)}


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
        if req.get("llm_route"):
            llm.use_route(req["llm_route"])
        if os.environ.get("CRASHLAB_RECORDED_REPLIES"):
            llm.BACKENDS["recorded"] = _recorded
            os.environ["CRASHLAB_LLM"] = "recorded"
        reply = {"plan": plan, "build": build, "scenarios": propose, "route": route, "agent": agent, "scenarios_pack": scenarios_pack.run}[sys.argv[1]](req)
        if llm.CALLS and isinstance(reply, dict):
            reply["llm_calls"] = llm.CALLS
    json.dump(reply, sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
