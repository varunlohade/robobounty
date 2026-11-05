# AI use disclosure

- Claude Code (Claude Opus 5.5) wrote the first MJCF scene (public/robots/acme-arm.xml),
  the inverse-kinematics test (scripts/pick.mjs) and the smoke test (scripts/smoke.mjs),
  directed and reviewed by the human builder.
- Claude Code wrote the shared simulation core (src/sim/core.ts: episode runner, IK, safety clamps,
  judging, evaluation) and the seed challenge controllers (src/challenges/acme.ts), plus scripts/eval.ts
  and scripts/trace.ts used to debug them.
- Claude Code wrote the browser viewer (index.html, src/main.ts, src/view/scene3d.ts) and Vite/TS config.
