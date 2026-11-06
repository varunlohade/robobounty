"""Runs policy/highrise5/run_trial5.py unchanged, and writes a heartbeat file about once a second while the sim steps: run_beat5.py <beat file> <run_trial5 arguments>.

The same as run_beat.py, for the v5 sim. The beat reads nothing from the sim and changes nothing in it.
"""
import runpy
import sys
import time
from pathlib import Path

RUN_TRIAL = Path(__file__).resolve().parent.parent / "highrise5" / "run_trial5.py"
beat_file = Path(sys.argv.pop(1))
sys.argv[0] = str(RUN_TRIAL)
sys.path[0] = str(RUN_TRIAL.parent)
import sim5

real_step = sim5.Sim.step
last, steps = 0.0, 0


def step(self, action):
    global last, steps
    steps += 1
    now = time.monotonic()
    if now - last >= 1:
        last = now
        beat_file.write_text(str(steps))
    return real_step(self, action)


sim5.Sim.step = step
runpy.run_path(str(RUN_TRIAL), run_name="__main__")
