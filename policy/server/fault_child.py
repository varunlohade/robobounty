"""A child that fails on purpose, for policy/server/check_hang.py and src/lab/tools/check_hang.mjs: fault_child.py <sleep|spin|crash|slow|diverge> [run_beat arguments]."""
import runpy
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOW_S = 30  # Past the check's 20 s limit, so only the heartbeat keeps this one alive.
mode = sys.argv[1]
if mode == "sleep":
    time.sleep(10 ** 6)
elif mode == "spin":
    while True:
        pass
elif mode == "crash":
    sys.exit(3)
elif mode == "slow":
    beat = Path(sys.argv[2])
    for n in range(SLOW_S):
        beat.write_text(str(n))
        time.sleep(1)
    sys.argv = [str(HERE / "run_beat.py"), *sys.argv[2:]]
    runpy.run_path(str(HERE / "run_beat.py"), run_name="__main__")
elif mode == "diverge":
    # The real run with a huge speed forced at one step, so the sim's own check calls the divergence.
    highrise = HERE.parent / "highrise"
    sys.path[0] = str(highrise)
    import sim
    real_step, steps = sim.Sim.step, [0]

    def step(self, action):
        steps[0] += 1
        if steps[0] == 300:
            self.d.qvel[0] = 1e6
        return real_step(self, action)
    sim.Sim.step = step
    sys.argv = [str(highrise / "run_trial.py"), *sys.argv[3:]]
    runpy.run_path(str(highrise / "run_trial.py"), run_name="__main__")
