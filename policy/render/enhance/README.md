# Testing an AI restyle of a recorded clip

Physics stays the source of truth. These tools make a restyle test ready to run, and they check the result against the recording. The choice of tool and its costs are in `docs/research/video-enhance.md`.

1. `export_passes.py` renders per-frame labels, depth and control videos with Blender, at low priority. Output goes to `design/render/enhance/<shot>/`. Blender stops if its camera or robot differs from the clip's pose log. It needs the v1 `scene.py` shots, and a clip with a pose log.
2. `run_cosmos.py` sends one control to a Cosmos3-Nano-Sim-Transfer server. It reads the host from env vars only, and it refuses to start without `--clip` and `--cost-estimate-usd`.
3. `faithful_check.py` compares an output video with the recorded robot path. It prints the rules in its header, a verdict, and writes a per-frame CSV.
4. `check_faithful.py` proves the check works. It builds faulty copies of the clip and compares verdicts with expected ones.

A FAIL means the video does not ship as faithful. A PASS means the robot's path and the main outlines match. It does not mean the dirt, cleaning or physics in the picture are true. Label any output as AI-restyled from recorded motion, and keep the Blender clip as the record.
