"""Runs policy/highrise/run_trial.py unchanged, and writes a heartbeat file about once a second while the sim steps: run_beat.py <beat file> <run_trial arguments>.

run_trial.py writes nothing until its run ends, so the server has no other way to tell a slow run from a stuck one. The beat reads nothing from the sim and changes nothing in it.
"""
import runpy
import sys
import time
from pathlib import Path

RUN_TRIAL = Path(__file__).resolve().parent.parent / "highrise" / "run_trial.py"
beat_file = Path(sys.argv.pop(1))
sys.argv[0] = str(RUN_TRIAL)
sys.path[0] = str(RUN_TRIAL.parent)  # The same modules a direct run finds, with no name from policy/server in front.
import sim

real_step = sim.Sim.step
last, steps = 0.0, 0


def step(self, action):
    global last, steps
    steps += 1
    now = time.monotonic()
    if now - last >= 1:
        last = now
        beat_file.write_text(str(steps))
    return real_step(self, action)


sim.Sim.step = step
runpy.run_path(str(RUN_TRIAL), run_name="__main__")
