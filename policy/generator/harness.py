"""Starts worker.py under sandbox-exec with CPU, memory, wall-time and file limits. Pattern copied from policy/crashlab/fix.py."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import gate as G

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
PY = POLICY / ".venv" / "bin" / "python"
CHECK = {"cpu_s": 120, "wall_s": 300, "rss_mb": 2048, "file_mb": 8}
TRIAL = {"cpu_s": 1500, "wall_s": 2400, "rss_mb": 2048, "file_mb": 64}


def _profile(run_dir):
    run_dir = os.path.realpath(run_dir)
    prefix = os.path.realpath(subprocess.run([str(PY), "-c", "import sys;print(sys.base_prefix)"], capture_output=True, text=True, check=True).stdout.strip())
    reads = [run_dir, prefix, os.path.realpath(POLICY / ".venv"), os.path.realpath(POLICY / "highrise"), os.path.realpath(HERE), "/System", "/usr/lib",
             "/usr/share", "/private/var/db/timezone", "/private/etc", "/opt/homebrew/opt", "/opt/homebrew/Cellar", "/Library/Preferences"]
    subpaths = "\n".join(f'  (subpath "{p}")' for p in reads)
    return f"""(version 1)
(deny default)
(allow process-exec (literal "{os.path.realpath(PY)}") (subpath "{prefix}"))
(allow file-read-metadata)
(allow file-map-executable)
(allow file-read*
{subpaths}
  (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (subpath "{run_dir}") (literal "/dev/null"))
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo") (global-name "com.apple.system.logger"))
(allow ipc-posix-shm-read-data ipc-posix-shm-write-data)
(allow signal (target self))
"""


def run_worker(argv, run_dir, limits):
    """Returns (exit code, the limit that killed it or None)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    profile = run_dir / "sandbox.sb"
    profile.write_text(_profile(run_dir))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(run_dir), "TMPDIR": str(run_dir), "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
           "VECLIB_MAXIMUM_THREADS": "1", "MUJOCO_LOG": "0", "GENERATOR_CPU_S": str(limits["cpu_s"]), "GENERATOR_FILE_MB": str(limits["file_mb"])}
    with (run_dir / "stderr.txt").open("wb") as err:
        p = subprocess.Popen(["sandbox-exec", "-f", str(profile), str(PY), str(HERE / "worker.py"), *argv], cwd=run_dir, env=env, stdout=subprocess.DEVNULL, stderr=err,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        t0 = time.time()
        while p.poll() is None:
            time.sleep(0.25)
            why = None
            if time.time() - t0 > limits["wall_s"]:
                why = "wall_time"
            else:
                rss = subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip()
                if rss and int(rss) / 1024 > limits["rss_mb"]:
                    why = "memory"
            if why:
                try:
                    os.killpg(p.pid, 9)
                except OSError:  # macOS refuses killpg while the group is mid-exec
                    p.kill()
                p.wait()
                return -9, why
    return p.returncode, "cpu_time" if p.returncode in (-24, 152) else None


def full_gate(text, work_dir, limits=CHECK):
    """Static gate, then compile and physics checks in the sandbox. Returns a report with ok, stage, code and plain."""
    try:
        canonical = G.check(text)
    except G.Reject as e:
        return {"ok": False, "stage": "gate", "code": e.code, "plain": e.plain}
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "canonical.xml").write_text(canonical)
    code, why = run_worker(["check", "canonical.xml"], work_dir, limits)
    path = work_dir / "report.json"
    if why:
        return {"ok": False, "stage": "compile", "code": f"limit_{why}", "plain": f"The compile and check step hit its {why.replace('_', ' ')} limit."}
    if code != 0 or not path.exists():
        return {"ok": False, "stage": "compile", "code": "worker_crashed", "plain": "The compile and check step crashed."}
    return json.loads(path.read_text())


def run_trial(canonical_path, seed, out):
    """A real trial and its replay in the sandbox. out holds result.json and replay.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(canonical_path, out / "input_scene.xml")
    code, why = run_worker(["trial", "input_scene.xml", str(seed), "."], out, TRIAL)
    if code != 0 or not (out / "result.json").exists():
        return {"status": "worker_failed", "limit": why, "code": code}
    r = json.loads((out / "result.json").read_text())
    code, why = run_worker(["replay", "."], out, TRIAL)
    rep = json.loads((out / "replay.json").read_text()) if (out / "replay.json").exists() else {"match": False}
    return {"status": "ran", "outcome": r["outcome"], "passed": r["passed"], "failure": r["failure"], "coverage": r["coverage"], "time_s": r["time_s"], "wall_s": r["wall_s"],
            "replay_match": bool(rep.get("match")), "replay_limit": why}
