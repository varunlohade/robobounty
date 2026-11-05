# Larger test of the try 2 patch

Written and committed before any run. This is the only rerun. Nothing is applied to controller.py.

Patch: fix/try_2/controller.py, sha256 8eb3238500c44e3c621c50aedc58b65f6ec1b85af87f7a33aefc3e8b1e097910. One change: SUCTION_CLEAN 0.85 to 0.9. No edits.
Base: controller.py, sha256 85e7220d4a09c7dd8c89ed5335542ede770d697c239e2d8ab9f5fd8a20f60ad6.
Sim: sim.py 0e36d3bf97fe, judge.py 135131fad826, world.py 0db7f46e3c01. The run pins to the commit that adds this file.

Worlds: the stored Dubai plan (its 8 groups, no LLM), scenario seeds 20261106 and 20261107, 52 worlds each, 104 in all. New seeds, none used before. All 104 count: none are dropped after the run. Expected baseline failures are about 60, from earlier rates. If fewer than 30 fail at baseline, I report it as too few and do not add worlds.
Controls: nominal world, 20 new sensor seeds (4000 to 4019).
Run: both controllers in the same sandbox, same world and seed, at most 3 processes, low priority. Each B run is re-judged by replay.

Primary test: one-sided sign test on the 104 pairs. Better and worse use pass over a hold over a failure. Pass rule: better > worse and p < 0.05.
Also required for "helped": controls 20 of 20, and detach and slip_distance counts do not rise.
Blind-point check, on 0.9 suction: the guard fires only if the estimate falls under 1500 Pa. I run the patched estimator at its low end, at speed 0.9. I expect about 2268 Pa, which means the low-pressure guard cannot fire in the clean phase. From the fresh traces, I also report on each side: worlds with a retreat, clean-phase steps with true pressure under 1500 Pa, and how many of those the estimate caught.

Conclusions, fixed now:
- "did not help": any required item fails.
- "helped on the counts but removed the low-pressure guard in the clean phase": all required items pass and the floor is at or over 1500 Pa. Not recommended as it stands.
- "helped on the counts and kept the guard": all required items pass and the floor is under 1500 Pa.

I report the result whatever it shows. In this simulation only. Physics uncalibrated.
