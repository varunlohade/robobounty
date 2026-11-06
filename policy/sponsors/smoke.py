"""The one test command per sponsor, for after the owner supplies keys: smoke.py 0g | world | arc. docs/SWITCH-ON.md says what each one costs.

0g: one small real LLM call and its receipt. world: signs one request and checks the signal hash, and sends nothing. arc: reads the chain and prints the bounty and balances, and sends nothing.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sponsor_status as status


def zero_g():
    state = status.llm_status()
    print(state["label"])
    if not state["zg_on"]:
        raise SystemExit(f"0G is off. Set CRASHLAB_LLM=0g, {', '.join(status.ZG_NEEDS)}.")
    sys.path.insert(0, str(HERE.parent / "crashlab"))
    import llm
    import zg_receipts
    with tempfile.TemporaryDirectory() as folder:
        path = os.environ["CRASHLAB_LLM_RECEIPTS"] = str(Path(folder) / "receipts.jsonl")
        reply = llm.complete_json('Return {"ok": true}.', {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}})
        print("reply", json.dumps(reply))
        print(json.dumps(zg_receipts.summary(path), indent=1))


def world():
    state = status.world_status()
    print(state["label"])
    if not state["on"]:
        raise SystemExit(f"World ID is off. Missing: {', '.join(state['missing'])}.")
    import world_id
    with tempfile.TemporaryDirectory() as folder:
        os.environ["WORLD_DB"] = str(Path(folder) / "smoke.sqlite")
        wallet = "0x" + "11" * 20
        ctx = world_id.request_context(wallet)
        print(json.dumps({"action": ctx["action"], "signal": ctx["signal"], "nonce": ctx["rp_context"]["nonce"], "expires_at": ctx["rp_context"]["expires_at"], "signature_bytes": (len(ctx["rp_context"]["signature"]) - 2) // 2}))


def arc():
    state = status.arc_status()
    if not state["on"]:
        raise SystemExit(state.get("reason") or f"Arc is off. Missing: {', '.join(state['missing'])}.")
    import chain
    print(json.dumps(chain.Chain().snapshot(), indent=1))


if __name__ == "__main__":
    {"0g": zero_g, "world": world, "arc": arc}[sys.argv[1]]()
