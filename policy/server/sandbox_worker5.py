"""Runs inside sandbox-exec, started by fix.py. Results are simulated.

run <pack> <controller.py> <request.json>     one world with a session copy of the controller. Writes job_result.json and progress.json, like the pack's own job.
trace <controller.py> <run folder> <line_trace.json>    the window robot only: the run again under linetrace, so its line is an executed line. The hash chain must match the record.
"""
import hashlib
import importlib.util
import json
import os
import re
import resource
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

# Hard limits, set before any controller code loads. A process cannot raise its own hard limits.
try:
    os.nice(10)
except PermissionError:  # the parent is already at the lowest priority macOS allows
    pass
_cpu, _file = int(os.environ["CRASHLAB_CPU_S"]), int(os.environ["CRASHLAB_FILE_MB"]) * 2**20
resource.setrlimit(resource.RLIMIT_CPU, (_cpu, _cpu))
resource.setrlimit(resource.RLIMIT_FSIZE, (_file, _file))
resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

POLICY = Path(__file__).resolve().parent.parent


def quiet_import(name):
    """mujoco's import asks sysctl about Rosetta, and the sandbox forbids new processes. Answer "not translated"; the check only guards x86_64 builds."""
    real = subprocess.run
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"0", stderr=b"")
    try:
        return importlib.import_module(name)
    finally:
        subprocess.run = real


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_shared():
    """By file, because the sandbox hides the listing of policy/ and policy/server/."""
    spec = importlib.util.spec_from_file_location("packs", POLICY / "packs" / "__init__.py", submodule_search_locations=[str(POLICY / "packs")])
    packs = importlib.util.module_from_spec(spec)
    sys.modules["packs"] = packs
    spec.loader.exec_module(packs)
    return load(POLICY / "server" / "pack_job.py", "pack_job")


def window_hooks(controller):
    quiet_import("mujoco")
    job = importlib.import_module("packs.window.job")
    job.P.R.controller_module = load(controller, "controller_under_test")
    job.P.controller_files = lambda: [controller]
    return job


def inspection_hooks(controller):
    quiet_import("mujoco")
    import warp as wp
    wp.config.kernel_cache_dir = os.environ["CRASHLAB_WARP_CACHE"]
    wp.config.verbose = False
    importlib.import_module("packs.inspection")
    load(controller, "packs.inspection.controller")
    model = importlib.import_module("packs.inspection.model")
    model.asset_dir = lambda: os.environ["CRASHLAB_NEWTON_ASSET"]  # Newton's own lookup starts git, and the sandbox forbids new processes.
    job = importlib.import_module("packs.inspection.job")
    job.HERE = Path(controller).parent
    return job


def crash_result(controller, error, req):
    """The session copy raised. That is a result about this code, and the line comes from the real traceback."""
    frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == str(controller)]
    line = frames[-1].lineno if frames else None
    words = f"The controller raised {type(error).__name__} at line {line}: {str(error)[:200]}" if line else f"The run could not finish: {type(error).__name__}: {str(error)[:200]}"
    return {"verdict": "controller_crashed", "passed": False, "reason": words, "numbers": {}, "events": [], "safe_hold": False, "seed": req["seed"], "label": "session copy", "note": "Simulated.",
            "code": {"file": Path(controller).name, "line": line, "why": words, "traced": True} if line else None}


def run(pack, controller, request):
    req = json.loads(Path(request).read_text())
    sha = hashlib.sha256(Path(controller).read_bytes()).hexdigest()
    out = Path(req["out"])
    pack_job = load_shared()
    try:
        hooks = {"window": window_hooks, "inspection": inspection_hooks}[pack](controller)
        result = pack_job.run(hooks, req)
    except Exception as error:  # noqa: BLE001 Any error in the session copy is that copy's result. The run's log keeps the traceback.
        traceback.print_exc()
        result = crash_result(controller, error, req)
        print(f"verdict {result['verdict']}: {result['reason']}", file=sys.stderr, flush=True)
    result.update(controller_sha256=sha, label=f"{result['label']}, controller copy {sha[:8]}")
    (out / "job_result.json").write_text(json.dumps(result, indent=1, allow_nan=False) + "\n")


def trace(controller, run_folder, target):
    """The controller line that was active when the first rule fired. Reported as traced only if the traced run has the same hash chain as the record."""
    run_folder = Path(run_folder)
    stored = json.loads((run_folder / "result.json").read_text())
    load_shared()
    hooks = window_hooks(controller)
    sys.path.insert(0, str(POLICY / "highrise"))
    linetrace = importlib.import_module("linetrace")
    made = []
    cls = linetrace.traced(hooks.P.R.controller_module)

    def build(mission):
        made.append(cls(mission))
        return made[-1]
    hooks.P.R.controller_module = SimpleNamespace(Controller=build)
    result = hooks.P.R.run(hooks.W.load(run_folder / "world.json"), stored["seed"])
    same = result["action_chain_head"] == stored["action_chain_head"]
    fired = stored["fired"]
    reply = {"same_chain": same, "traced": False, "line": None, "phase": None, "t": None, "rule": None}
    if same and fired:
        rule, first = min(fired.items(), key=lambda kv: kv[1]["t"])
        step = int(first["t"] * hooks.P.R.S.CONTROL_HZ) - 1
        rows = [r for r in made[-1].log["runs"] if r[0] <= step] or made[-1].log["runs"][:1]
        _, phase, line, _ = rows[-1]
        reply.update(traced=line is not None, line=line, phase=phase, t=first["t"], rule=rule)
    Path(target).write_text(json.dumps(reply))


if __name__ == "__main__":
    {"run": run, "trace": trace}[sys.argv[1]](*sys.argv[2:])
