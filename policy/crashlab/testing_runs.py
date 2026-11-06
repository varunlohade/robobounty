"""Runs a short list of worlds for the boundary search and the regression suite, each in its own child, under the campaign loop. Results are simulated.

Frames stay off, since no square shows these runs. Only job_result.json and job.log stay, since these runs have no replay.
"""
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import pack_campaign
import pack_job

KEPT = {"job_result.json", "job.log"}
NO_FRAMES = ["/usr/bin/env", f"{pack_job.NO_FRAMES_ENV}=1"]
LOCAL_RULE = SimpleNamespace(quiet_s=60, silent_s=660)
INFRA = ("froze", "process_crashed")  # No judge read these. They say nothing about the robot.


def plain_argv(pack):
    return lambda folder, world: [*NO_FRAMES, *pack_job.argv(pack, "run")]


def _tidy(folder):
    for path in Path(folder).iterdir():
        if path.name not in KEPT:
            shutil.rmtree(path) if path.is_dir() else path.unlink()


def run_jobs(pack, jobs, folder, spawn, finish, kill_group, rule, argv_for=None, beat=None, on_rows=None, max_procs=None):
    """jobs: world, seed, name, outline, t_limit. Returns one row per job, in order, with the judge's numbers. A crashed child is a row with its own verdict, and nothing retries it."""
    argv_for = argv_for or plain_argv(pack)
    folder = Path(folder)
    plan = {"worlds": [{"index": i, "name": j["name"], "group": j.get("group", ""), "reason": "", "held_back": False, "seed": j["seed"], "world": j["world"], "outline": j["outline"], "t_limit": j["t_limit"], "marks": []} for i, j in enumerate(jobs)]}
    campaign = pack_campaign.Campaign(pack, "testing", plan, folder, max_procs or pack_job.PACKS[pack]["max_procs"], rule, spawn, finish, kill_group,
                                      argv_for=lambda world: argv_for(folder, world), on_grid=lambda grid: on_rows(grid["rows"]) if on_rows else None, beat=beat)
    rows = campaign.run()["rows"]
    out = []
    for i, row in enumerate(rows):
        run = folder / f"w{i:03d}"
        result = pack_campaign.read_json(run / "job_result.json") or {}
        out.append({"status": row["status"], "verdict": row["verdict"], "reason": row["verdict_reason"], "numbers": result.get("numbers", {}), "seed": jobs[i]["seed"], "label": result.get("label"), "wall_s": result.get("wall_s")})
        if run.exists():
            _tidy(run)
    return out


def local_kit():
    """Children for a check or a command line, with no server."""
    import os
    import signal

    def spawn(argv, **kw):
        return subprocess.Popen(["nice", "-n", "5", *argv], start_new_session=True, **kw)

    def kill_group(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return {"spawn": spawn, "finish": lambda p: p.wait(), "kill_group": kill_group, "rule": LOCAL_RULE}
