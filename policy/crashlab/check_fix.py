"""Pass or fail check of fix.py with no LLM. Exits 0 on pass. Hostile controllers run in the real sandbox.

check_fix.py [--keep DIR]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fix
import run_trial
import world as W

BASE_TEXT = fix.BASE.read_text()
IMPORT_MATH = "import math\n"
NOMINAL = W.load(fix.HIGHRISE / "worlds" / "nominal.json")


def with_change(old, new):
    assert old in BASE_TEXT
    return BASE_TEXT.replace(old, new, 1)


BAD = {
    "import os": with_change(IMPORT_MATH, "import math\nimport os\n"),
    "import subprocess": with_change(IMPORT_MATH, "import math, subprocess\n"),
    "import socket": with_change(IMPORT_MATH, "import math\nimport socket\n"),
    "from os import path": with_change(IMPORT_MATH, "import math\nfrom os import path\n"),
    "from math import star": with_change(IMPORT_MATH, "import math\nfrom math import *\n"),
    "numpy submodule": with_change(IMPORT_MATH, "import math\nimport numpy.ctypeslib\n"),
    "relative import": with_change(IMPORT_MATH, "import math\nfrom . import sim\n"),
    "open": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        open('/tmp/x', 'w')\n"),
    "eval": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        eval('1')\n"),
    "exec": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        exec('1')\n"),
    "dunder import": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        __import__('os')\n"),
    "getattr": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        getattr(self, 'x')\n"),
    "dunder attribute": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        x = ().__class__\n"),
    "dunder in a string": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        x = '{0.__class__}'\n"),
    "numpy load": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        np.load('x')\n"),
    "numpy tofile": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        a.tofile('x')\n"),
    "str format": with_change("        t = o[\"t\"]\n", "        t = o[\"t\"]\n        x = 'a'.format(1)\n"),
    "no step": BASE_TEXT.replace("def step(self, o):", "def walk(self, o):"),
    "syntax error": BASE_TEXT + "\ndef (\n",
}
HOSTILE_PROBES = """
import json, os, socket, subprocess
res = {}
home = os.path.realpath(os.path.expanduser('~varun')) if False else OWNER_HOME
def attempt(name, fn):
    try:
        fn(); res[name] = 'ALLOWED'
    except PermissionError:
        res[name] = 'blocked'
    except socket.gaierror:
        res[name] = 'blocked' if name == 'network_dns' else 'gaierror'
    except BaseException as e:
        res[name] = type(e).__name__
attempt('network_connect', lambda: socket.create_connection(('1.1.1.1', 53), timeout=3))
attempt('network_dns', lambda: socket.getaddrinfo('example.com', 80))
attempt('write_outside', lambda: open(OUTSIDE, 'w').write('x'))
attempt('read_ssh', lambda: os.listdir(home + '/.ssh'))
attempt('read_repo_file', lambda: open(REPO + '/AI-USE.md').read())
attempt('read_policy_runs', lambda: os.listdir(REPO + '/policy/runs'))
attempt('run_process', lambda: subprocess.run(['/bin/echo', 'x'], check=True, capture_output=True))
attempt('edit_controller', lambda: open(CONTROLLER, 'a').write('# x'))
json.dump(res, open('probes.json', 'w'))
class Controller:
    phase, estimate = "hostile", 0.0
    def __init__(self, mission): pass
    def step(self, o): return [0.0, 0.0, 1.0, 0.0, 1.0, 0.0]
"""
LOOP = "class Controller:\n    def __init__(self, mission): pass\n    def step(self, o):\n        while True: pass\n"
MEMORY = "class Controller:\n    def __init__(self, mission): pass\n    def step(self, o):\n        x = [bytearray(2**24) for _ in range(100000)]\n"


def run_one(ctl, tmp, name, wall=fix.TRIAL_WALL_S, rss=fix.TRIAL_RSS_MB):
    out = Path(tmp) / name
    out.mkdir(parents=True)
    world_path = out / "input_world.json"
    world_path.write_text(json.dumps(NOMINAL))
    return out, fix.run_sandboxed([str(HERE / "sandbox_worker.py"), "trial", str(ctl), str(world_path), "1000", str(out)], out, ctl, wall_s=wall, rss_mb=rss)


def main():
    failures = []
    before = hashlib.sha256(fix.BASE.read_bytes()).hexdigest()
    if fix.validate_source(BASE_TEXT):
        failures.append(f"the base controller fails the validator: {fix.validate_source(BASE_TEXT)}")
    ok = with_change("WIND_RESUME_MS = 7.0", "WIND_RESUME_MS = 8.0")
    ok = with_change(IMPORT_MATH, "import math\nimport numpy as np\n").replace("WIND_RESUME_MS = 7.0", "WIND_RESUME_MS = 8.0")
    if fix.validate_source(ok):
        failures.append(f"a harmless diff was rejected: {fix.validate_source(ok)}")
    for name, text in BAD.items():
        if not fix.validate_source(text):
            failures.append(f"validator accepted: {name}")
    print(f"validator: {len(BAD)} hostile sources rejected, import os reasons = {fix.validate_source(BAD['import os'])}")

    keep = sys.argv[2] if sys.argv[1:2] == ["--keep"] else None
    tmp = keep or tempfile.mkdtemp(prefix="crashlab_check_fix_")
    tmp = os.path.realpath(tmp)
    if keep:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
    outside = Path(tempfile.gettempdir()) / "crashlab_outside_probe.txt"
    outside.unlink(missing_ok=True)
    (Path(tmp) / "ctl").mkdir()
    hostile = Path(tmp) / "ctl" / "hostile.py"
    hostile.write_text(f"OWNER_HOME = {str(Path.home())!r}\nOUTSIDE = {str(outside)!r}\nREPO = {str(fix.ROOT)!r}\nCONTROLLER = {str(fix.BASE)!r}\n" + HOSTILE_PROBES)
    out, (code, why) = run_one(hostile, tmp, "hostile")
    probes = json.loads((out / "probes.json").read_text()) if (out / "probes.json").exists() else {}
    print("sandbox probes:", probes, "exit", code, why, (out / "stderr.txt").read_text()[-200:])
    if len(probes) != 8 or any(v != "blocked" for v in probes.values()):
        failures.append(f"sandbox probes: {probes}; stderr {(out / 'stderr.txt').read_text()[-400:]}")
    if outside.exists():
        failures.append("a write escaped the run dir")

    loop = Path(tmp) / "ctl" / "loop.py"
    loop.write_text(LOOP)
    _, (code, why) = run_one(loop, tmp, "loop", wall=5)
    print("infinite loop:", code, why)
    if why != "wall_time":
        failures.append(f"loop not stopped: {code} {why}")
    mem = Path(tmp) / "ctl" / "mem.py"
    mem.write_text(MEMORY)
    _, (code, why) = run_one(mem, tmp, "mem", wall=60, rss=400)
    print("memory bomb:", code, why)
    if why != "memory":
        failures.append(f"memory bomb not stopped: {code} {why}")

    # The base controller gives the same hash chain inside and outside the sandbox, so the sandbox does not bias A or B.
    outs, (code, why) = run_one(fix.BASE, tmp, "base")
    inside = json.loads((outs / "result.json").read_text()) if code == 0 else None
    plain = run_trial.run(NOMINAL, 1000)
    same = inside is not None and inside["action_chain_head"] == plain["action_chain_head"]
    print("sandbox chain equals plain chain:", same, "exit", code, why)
    if not same:
        failures.append(f"sandbox changed the run: {code} {why} {(outs / 'stderr.txt').read_text()[-400:]}")
    if code == 0:
        rcode, rwhy = fix.run_sandboxed([str(HERE / "sandbox_worker.py"), "replay", str(outs)], outs, fix.BASE)
        rep = json.loads((outs / "replay.json").read_text()) if rcode == 0 else {}
        print("replay in sandbox:", rep.get("match"), rcode, rwhy)
        if not rep.get("match"):
            failures.append("replay in the sandbox failed")
        # A forged pass: the stored result says pass, the actions say otherwise.
        forged = json.loads((outs / "result.json").read_text())
        forged["failure"], forged["passed"], forged["coverage"] = None, True, 1.0
        (outs / "result.json").write_text(json.dumps(forged))
        fix.run_sandboxed([str(HERE / "sandbox_worker.py"), "replay", str(outs)], outs, fix.BASE)
        if json.loads((outs / "replay.json").read_text()).get("match"):
            failures.append("a forged result passed replay")
        print("forged result caught by replay: True")

    # accept refuses with no human at a terminal, and the file stays the same.
    tdir = Path(tmp) / "try"
    tdir.mkdir()
    (tdir / "report.json").write_text(json.dumps({"status": "awaiting_human", "base_controller_sha256": before, "diff_sha256": "0" * 64, "ab": {}}))
    (tdir / "patch.diff").write_text("x")
    shutil.copyfile(fix.BASE, tdir / "controller.py")
    done = subprocess.run([sys.executable, str(HERE / "fix.py"), "accept", str(tdir)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    print("accept with no terminal:", done.stdout.strip(), done.returncode)
    if done.returncode != 2:
        failures.append("accept ran with no terminal")
    if hashlib.sha256(fix.BASE.read_bytes()).hexdigest() != before:
        failures.append("controller.py changed")
    if not keep:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n".join(failures) or "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
