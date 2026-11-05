# CrashLab campaign-loop plan (Fri 6 Nov 01:21 IST; deadline Sat 7 Nov 09:00 IST)

AI-written planning file (Claude, planner agent), directed by the human builder. Committed because ETHGlobal asks for specs and plans.

Loop: plain-English brief -> worlds -> run -> judge -> diagnose -> fix -> re-run.

## Realism gaps
- Sim only (LIBERO on MuJoCo, Panda arm). The policy is HuggingFaceVLA/smolvla_libero, not ours. No retraining.
- Diagnose means scene factor + sim state, never a line of code. A neural network has no lines to blame.
- Replay means recorded actions, not scene + seed.
- Worlds far from LIBERO's tabletop families mostly fail because the model never saw them. That is not a robustness finding, so say so.

## What a brief can build
- Today (scene.py v1): 10 stock tasks x 50 init states; move 5 objects; light; recolour; box clutter.
- Planned (schema v2 -> our BDDL writer): 6 arenas, fixtures, about 45 objects, numeric placement regions, seeded start poses, goals from LIBERO's predicates.
- Cannot build: new robots, new meshes, fluids, outdoors, deformables, humans, light direction or colour, moved cameras.
- Security: the LLM fills a JSON schema of numbers and allowlisted tokens. Our writer emits BDDL from validated values only. Never emit yaw_rotation, because bddl_utils.py:36 calls eval on it.

## Diagnose and fix
- Diagnose: factor table against matched controls, failure moment from per-step sim state, controlled re-test. The LLM only words the numbers, and a check rejects prose with numbers absent from the table.
- Fix: primary is a stall-retry wrapper, tested as paired A/B on the same scenes, reported as counts. Other knobs: instruction rewrite, n_action_steps. Fallback: report "no fix helped" and the operating envelope, with the real table.

## LLM and sponsors
- llm.py with one complete_json(prompt, schema). Backend A: Claude Code headless. Backend B: 0G Private Computer, after the owner approves a wallet and tokens.
- Sponsors stay thin: 0G PC, World IDKit, Arc or Hedera USDC. Cut order: 0G Storage library, then contract, then World.

## Tasks (owner | check | hours | latest start)
1. n_action_steps 1 vs 10 on 4 scenes | junior-dev | success and time table | 1.5 | Fri 03:00
2. Schema v2 + world builder | junior-dev | 10 generated worlds build, settle, render; bad files rejected | 5 | 09:00
3. Brief to worlds via llm.py | junior-dev | 3 briefs give 20+ valid worlds each; injection gives schema only | 3 | 11:00
4. Per-step metrics + judge | junior-dev | replay still matches | 2 | 13:00
5. Security review of 2-3 | security-researcher | 5 adversarial briefs rejected | 1.5 | 14:00
6. Diagnose | junior-dev | top factor with counts | 4 | 15:00
7. Fix flags + paired compare | junior-dev | wrapper fires on a known failure | 3 | 16:00
8. crashlab CLI | junior-dev | end to end on 2 worlds | 2 | 18:00
9. Compute: 30-world campaign (18:00), re-test 10 (21:00), A/B 2x20 (Sat 00:00) | steve
10. 0G backend (20:00), World IDKit (22:00), contract (22:00) | junior-dev + steve for keys
11. Site pages with real numbers | design | 3 | Sat 00:00
12. README, AI-USE.md, limits | steve | 1.5 | 05:00
13. Video | steve + owner | 2.5 | 04:30
14. Submission | steve | 1 | 07:30

## Top risks
1. Generated worlds all fail because they are far from training. Keep near training families and always include stock controls.
2. Compute: about 8 h of serial runs. Do task 1 first.
3. Custom BDDL on Mac is untested. Timebox 2 h, then fall back to schema v1 worlds.

Unknown: which suites the checkpoint trained on; 0G request-ID exposure; World verify without a chain; drawer and microwave goal judging.
