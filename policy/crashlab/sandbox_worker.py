"""Runs inside sandbox-exec, started by fix.py. trial <controller.py> <world.json> <seed> <out> | replay <run dir>"""
import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

# Hard limits, set before any controller code loads. A process cannot raise its own hard limits.
try:
    os.nice(10)
except PermissionError:  # the parent is already at the lowest priority macOS allows
    pass
_cpu, _file = int(os.environ["CRASHLAB_CPU_S"]), int(os.environ["CRASHLAB_FILE_MB"]) * 2**20
resource.setrlimit(resource.RLIMIT_CPU, (_cpu, _cpu))
resource.setrlimit(resource.RLIMIT_FSIZE, (_file, _file))
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

# mujoco's import asks sysctl about Rosetta, and the sandbox forbids new processes. Answer "not translated"; the check only guards x86_64 builds.
_real_run = subprocess.run
subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"0", stderr=b"")
import mujoco  # noqa: E402
subprocess.run = _real_run

HIGHRISE = Path(__file__).resolve().parent.parent / "highrise"
sys.path.insert(0, str(HIGHRISE))
import replay as replay_module
import run_trial
import world as W


def trial(controller, world_path, seed, out):
    spec = importlib.util.spec_from_file_location("controller_under_test", controller)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_trial.controller_module = module
    world = W.load(world_path)
    run_trial.run(world, int(seed), out)
    path = Path(out) / "result.json"
    result = json.loads(path.read_text())
    result["code_sha256"]["controller.py"] = hashlib.sha256(Path(controller).read_bytes()).hexdigest()
    path.write_text(json.dumps(result, indent=1) + "\n")


def replay(run_dir):
    report = replay_module.replay(run_dir)
    report["world_sha"] = W.world_hash(W.load(Path(run_dir) / "world.json"))
    (Path(run_dir) / "replay.json").write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "trial":
        trial(*sys.argv[2:6])
    else:
        replay(sys.argv[2])
