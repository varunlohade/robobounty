# AI use disclosure

- Claude Code (Claude Opus 5.5) wrote the first MJCF scene (public/robots/acme-arm.xml),
  the inverse-kinematics test (scripts/pick.mjs) and the smoke test (scripts/smoke.mjs),
  directed and reviewed by the human builder.
- Claude Code wrote the shared simulation core (src/sim/core.ts: episode runner, IK, safety clamps,
  judging, evaluation) and the seed challenge controllers (src/challenges/acme.ts), plus scripts/eval.ts
  and scripts/trace.ts used to debug them.
- Claude Code wrote the browser viewer (index.html, src/main.ts, src/view/scene3d.ts) and Vite/TS config.
- Claude Code set up the LIBERO + SmolVLA run on Apple Silicon (policy/run_ep1.sh). The model itself is HuggingFaceVLA/smolvla_libero, not ours.
- A Claude Code security agent wrote docs/security/THREAT-MODEL.md.
- Claude Code (design-builder) and GPT (Codex, gpt-6-astra) produced design explorations in design/, from briefs written by Claude Code and directed by the human builder.
- Claude Code wrote the CrashLab scene runner in policy/crashlab/ (scene schema, variation runner, action replay, scene generator). The policy is HuggingFaceVLA/smolvla_libero and the simulator is LIBERO on MuJoCo; neither is ours.
- Claude Code wrote the CrashLab world builder in policy/crashlab/ (world.py schema v2 and BDDL writer, build_world.py, check_world.py, sample_worlds/). The assets, arenas and predicates come from LIBERO; they are not ours.
- Claude Code wrote the CrashLab brief pipeline in policy/crashlab/ (llm.py, brief.py, brief_libero.py, brief_highrise.py, check_brief.py). A headless Claude Code call with no tools turns a brief into numbers and allowlisted tokens. Our code then samples, validates and builds the worlds.
- Claude Code wrote the CrashLab scenario agent in policy/crashlab/ (scenarios.py, check_scenarios.py, SCENARIO-GAPS.md). A headless Claude Code call with no tools proposes scenario groups, ranges, world counts and plain reasons from the chat. Our code validates them, samples and validates the worlds, and writes the not-tested list.
- Claude Code wrote the high-rise window robot world in policy/highrise/ (world builder, suction, wind and battery models, controller, judge, trial runner, campaign, replay, preview, PARAMETERS.md). MuJoCo is the simulator. The robot is a fictional scale-up of home window robots, not a real product, and no third-party robot model is used.
