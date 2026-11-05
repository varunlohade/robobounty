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

## Product decision (owner, 2026-11-06)
Owner's words: "I think we can have AI fix those failures, or the user can also ask a user can also ask a experienced engineer do it. Like, yeah, they can have a bounty saying, hey, we are not able to fix it, can you figure"

Flow: the AI tries a fix first. If the fix does not pass, the company posts a bounty for experienced engineers, with the failure pack attached. A solver's fix runs through the same worlds. The contract pays only on a passing result, after the dispute window.
This makes the bounty the escalation path, not an add-on.

## Demo change (owner, 2026-11-06)
Owner's words: "let's have a AI robot cleaning the mirrors of a high-rise building ... why would there be an arm in a kitchen, right? ... Use that video which they have on their website as a reference and try to build something similar."
The hero demo moves from the LIBERO kitchen arm to a simulated high-rise glass-cleaning robot in MuJoCo. The SmolVLA batch is stopped at the scenes it finished; results stay on disk and it can resume.
Google is the owner's video service for the concept film.

## Product shape (owner, 2026-11-06)
Owner's words: "The split window thing would be the main software. I'm okay with it being a paid software, by the way, just saying like a macOS software ... it's something I want to continue building."
Main software: a split window. One side takes a prompt and shows code. The other side shows the live simulation. "Test it" spawns many worlds. A bounty invites other people to find test cases that break the robot.
For Saturday: a web app in the split-window layout, for one robot, wrapped as a Mac app only if time allows. The public website is the marketing page.

## Re-cut task list for the high-rise demo (planner agent, Fri 01:55; edited by steve)
Steve's edits: the planner wrote this before the split-window decision, so tasks A and 8 replace its site-first order and its solver-code gate. Its draft line "a real neural policy ran by link, 6 of 60" was wrong: SmolVLA ran locally, and the batch had 40 scenes with 6 finished. Use the true facts in the README.

Honest wording: "a simulated robot we built in MuJoCo for this hackathon, with a scripted Python controller we wrote. The AI is in the test loop, not in the robot."

1. High-rise world + controller (running) | 20 headless episodes, seconds per episode measured | by 02:00 start
2. llm.py + brief.py on high-rise schema (running) | 3 briefs give 20+ valid worlds; injection gives schema only
3. Commit controller BEFORE any campaign, as no-plant proof; campaign report with counts, Wilson interval, fingerprints, code hash | check passes on 20 worlds | start by 05:00
4. Glass judge + per-step metrics; controller logs phase and line | replay matches; 3 distinct reasons | 06:00
5. Campaign 1, 100-300 worlds | report with counts | 08:00
6. Diagnose to line with factor table; prose numbers checked against the table | real file:line with counts | 09:00
7. AI fix on controller.py only: import allowlist, sandbox-exec, limits, paired A/B, human approves the diff | `import os` diff rejected; A/B counts | 11:00
A. Split-window app (main product): prompt + code on one side, live browser sim on the other, worlds grid, failure view, bounty panel | design bake-off for layout, then junior-dev | full flow with real data, recorded states | start by 09:00
8. Test-world bounty gate (if owner confirms): numeric world file, limits set by company, reference passes, repeat 3 of 3, new failure fingerprint | security-researcher | hostile world files rejected | 13:00
9. Contract: propose, dispute window, finalize, pull claim, 6-decimal USDC, testnet | needs owner keys | txs shown | 14:00
10. CLI or app end to end on 2 briefs | 17:00
11. Security review of 7-9 | Criticals fixed | 19:00
12. Campaign 2 with the fix and a submitted world | before and after counts | 20:00
13. Marketing site with real numbers | every number traces to a report | 21:00
14. 0G backend and World IDKit | needs owner keys | 22:00
15. README, AI-USE, limits | Sat 03:00
16. Video | Sat 04:30
17. Submission | Sat 07:30

Cut order: 14, then 9 (local ledger, labelled undeployed), browser live sim (use rendered video), concept film, diagnose-to-line falls back to phase.
Top risks: controller never or always fails; AI patch does not pass; last-10-hour crunch across contract and app.
Unknown: seconds per episode; MuJoCo 3.16 wheel for Python; sandbox-exec network block on macOS 26; testnet USDC.

## Plan v2 changes (planner, Fri 02:10; steve's edits)
Adds: primitives-only MJCF readable in Python MuJoCo 3.8.1 and browser 3.16.0 (steve: real arm meshes may replace primitives if they load in both); per-step recorded qpos; App v1 split window by 06:00; local run server labelled as a demo shortcut (10:00); bounty = numeric world files only; pay per new failure fingerprint, with a cap and a top prize, pending owner confirmation. Cut order: Mac wrapper, 0G/World, contract to labelled local ledger, live streaming, diagnose-to-line falls back to phase.
Demo, all inside the app: brief -> Test it -> failure at file:line -> AI diff and retest -> someone else's world file breaks it and gets paid -> limits.
Robot basis changed by owner request: real arm-in-cradle facade robots. See docs/research/facade-robots.md.
