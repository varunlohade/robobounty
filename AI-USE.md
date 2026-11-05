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
