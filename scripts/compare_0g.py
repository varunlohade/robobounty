#!/usr/bin/env python3
"""Compares 0G with Claude: one scenario list and the phrase test in policy/server/check_look.py. It makes real, paid AI calls, so it runs only with --yes, after credentials exist.

policy/.venv/bin/python scripts/compare_0g.py [--yes] [--only 0g|claude] [--model M]. It saves the result in policy/runs/compare_0g/.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POLICY = REPO / "policy"
SERVER = POLICY / "server"
PY = str(POLICY / ".venv" / "bin" / "python")
WORLD = POLICY / "highrise" / "worlds" / "nominal.json"
PHRASES = 33  # check_look.py holds this many. The brief calls it the 30 phrase test.
WORDS = "Test this window cleaning robot in harder weather and on dirty glass."


def scenarios(env):
    with tempfile.TemporaryDirectory() as out:
        request = {"pack": "window", "world": json.loads(WORLD.read_text()), "words": [WORDS], "out": out, "limit": 12, "limits": None}
        started = time.time()
        done = subprocess.run([PY, str(SERVER / "plan_job.py"), "scenarios_pack"], input=json.dumps(request).encode(), capture_output=True, env=env, timeout=900)
    if done.returncode != 0:
        return {"ok": False, "why": "process died", "seconds": round(time.time() - started, 1)}
    reply = json.loads(done.stdout)
    return {"ok": not reply.get("rejection"), "why": reply.get("rejection"), "seconds": round(time.time() - started, 1), "count": reply.get("count"), "dropped": reply.get("dropped"), "groups": [g if isinstance(g, str) else g.get("name") for g in reply.get("groups", [])], "request_ids": [r.get("request_id") for r in reply.get("llm_calls", [])]}


def phrases(env, model):
    done = subprocess.run([PY, str(SERVER / "check_look.py"), "--live", model], capture_output=True, text=True, env=env, timeout=1800)
    lines = done.stdout.splitlines()
    return {"right": sum(l.startswith("RIGHT") for l in lines), "wrong": [l for l in lines if l.startswith("WRONG")], "summary": lines[-1] if lines else "no output"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--only", choices=("0g", "claude"))
    ap.add_argument("--model", default="claude-opus-5-5")
    a = ap.parse_args()
    backends = [a.only] if a.only else ["claude", "0g"]
    if "0g" in backends and not (os.environ.get("ZG_API_KEY") and os.environ.get("ZG_MODEL")):
        print("ZG_API_KEY and ZG_MODEL are not set, so 0G cannot run. Nothing was called.")
        return 1
    print(f"Plan: {len(backends)} backend(s): {', '.join(backends)}. Each makes {PHRASES} phrase calls and 1 scenario call. These are real AI calls, and they spend credits.")
    if not a.yes:
        print("Nothing was called. Add --yes to run it.")
        return 0
    results = {}
    for backend in backends:
        env = {**os.environ, "CRASHLAB_LLM": backend}
        results[backend] = {"scenarios": scenarios(env), "phrases": phrases(env, os.environ.get("ZG_MODEL") if backend == "0g" else a.model)}
        print(backend, json.dumps(results[backend], indent=1), flush=True)
    folder = POLICY / "runs" / "compare_0g"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(results, indent=1))
    print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
