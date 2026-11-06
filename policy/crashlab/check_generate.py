"""Checks of the generated-object path with no GPU and no AI: policy/.venv-gen/bin/python crashlab/check_generate.py, from policy/. A GLB is hostile data, every Claude value is clamped, and with the GPU off nothing is faked."""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "server")]
os.environ["CRASHLAB_GPU_URL"] = "http://127.0.0.1:9"
import generate_loop as L
import generate_object as GO

failed = 0


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))


def refused(data):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "x.glb"
        path.write_bytes(data)
        try:
            GO.process(path, "a test object")
        except GO.BadGlb as bad:
            return str(bad)
    return "accepted"


check("a file that is not a GLB refuses", refused(b"#!/bin/sh\nrm -rf /\n") == "not_glb")
check("a broken GLB refuses", refused(b"glTF" + struct.pack("<II", 2, 12)) in ("unreadable", "no_mesh"))
for bad in ("0" * 63, "../../etc/passwd", None, 5, "f" * 64):
    try:
        GO.load(bad)
        check(f"a bad sha refuses: {bad}", False)
    except GO.BadGlb:
        check(f"a bad sha refuses: {bad}", True)
plan = L.clamp_plan({"image_prompt": "a pump; rm -rf / `x` <b>$(y)</b>", "real_size_m": 999, "density_word": "plutonium"}, "a pump")
check("a size outside the list goes to the nearest listed size", plan["real_size_m"] == max(L.SIZES_M), plan["real_size_m"])
check("an unknown density word gets the default", plan["density_kg_m3"] == GO.DEFAULT_DENSITY)
check("the prompt keeps only the safe charset", not set("`<>$&|") & set(plan["prompt"]), plan["prompt"])
check("a bad size type gets a listed size", L.clamp_plan({"image_prompt": "x", "real_size_m": True, "density_word": 3}, "a pump")["real_size_m"] == 1.0)
said = []
made = L.make("a model nobody made", lambda line, fail=False: said.append((line, fail)), lambda *a: None)
check("with the GPU off, the chat says so plainly", made["state"] == "off" and "GPU server is off" in said[0][0] and said[0][1], json.dumps(said))
check("with the GPU off, no Claude call is spent", made["stats"]["claude_calls"] == 0)
check("the word lookup finds a held description only", GO.find("xyzzy") is None and GO.find("") is None and GO.find(None) is None)
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
