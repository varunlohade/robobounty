# ETHGlobal Mumbai submission: CrashLab

Draft. Lines marked `CONFIRM:` need steve. Numbers carry their source file in an HTML comment.

## Name

CrashLab

## One-line pitch

Crash tests for robots: you describe the job, AI builds the tests, and people get paid when their fix passes.

## Short description

CrashLab tests a robot controller in simulated worlds. You pick a robot and change its world in plain English. An AI lists scenarios, and our code checks each one and runs them all at once in a grid. A red square opens the recorded run, the judge's reason and the line of code. If an AI fix does not help, you post a bounty. A person submits a fix, code tests it on hidden worlds, and a local ledger pays them in test units after a dispute window.

Everything is simulated. The physics is hand-built, the values are assumed, and nothing has been checked against hardware.

## The problem

A robot team finds out what breaks its robot by breaking the robot, or by writing test worlds by hand. Writing those worlds is slow, and a list of passed tests rarely says what was left out. When a team cannot fix a failure itself, it has no simple way to pay an outsider for a fix and check that fix on worlds the outsider never saw.

CrashLab is a small try at that loop. It does not replace a calibrated simulator or a hardware test.

## How it works

1. **Log in.** World ID or local guest. The wall behind the panel replays recorded simulated runs.
2. **Pick a robot.** A window cleaner on a tower (MuJoCo, our scripted controller) or an inspection robot in a plant (Newton, an upstream walking policy with our route code).
3. **Change the world by typing.** The AI answers with function names and arguments only. `engine5` checks every call. Nothing the model writes executes.
4. **List scenarios.** The AI proposes scenarios, and each reason is labelled a reasoned guess. Code replays each one and drops what it refuses. Some worlds are held back, so a fix can be tested on worlds it never saw. A not-tested list shows what has no physics.
5. **Run the grid.** All runs go at once. Red means failed or stuck. A judge written in code decides from recorded state.
6. **Click a red square.** It shows the replay of the recorded run, the judge's reason and the log.
7. **Open file.** An editor opens the controller at the traced line. Edits go to a session copy.
8. **Ask AI to fix.** The AI edits a copy, and code tests it in a sandbox. In the stored demo run it did not help: 0 of 6 target worlds got better, so it was not applied.
9. **Post a bounty.** A person submits a controller change. Code tests it on the failing worlds and on hidden worlds, with a judge outside the sandbox. A pass opens a dispute window, then finalize, then claim.
10. **Find the limit.** Code varies one factor of a failed world, at most 12 runs per factor, and says where failure starts or says that it found no clean boundary.

<!-- 0 of 6, policy/runs/demo/window/stored_fix.json, sets.target. 12 runs: src/lab/grid.ts, Find the limit button title. -->

## Results from the recorded batches

These count what happened in worlds chosen to stress each robot. They are not a measure of reliability.

| | Window robot | Inspection robot |
|---|---|---|
| Scenarios kept | 48 | 48 |
| Run | 34 | 34 |
| Held back | 14 | 14 |
| Passed | 13 | 16 |
| Failed or stuck | 19 | 18 |
| Safe holds | 2 | 0 |

<!-- policy/runs/demo/{window,inspection}/scenarios.json.gz (count, to_run, held_back); last frame of policy/runs/demo/{window,inspection}/timeline.json.gz (status). The login wall adds these: 68 runs, 29 passed, 37 failed, 2 safe holds. -->

Find the limit on a window failure: "In this world, this robot starts failing between seal leak 240 and 280 mm2: low coverage. 3 of 3 seeds. Just on the other side, 3 of 3 seeds did not fail." Other searches find no clean boundary and say so.

<!-- policy/runs/demo/window/boundary.json, group coverage. -->

An earlier single-robot campaign is summarised in `README.md`, with its evidence in `docs/evidence/`. `python3 policy/crashlab/check_numbers.py --evidence` recomputes those numbers. It printed ALL NUMBERS MATCH on 7 Nov.

## Tech stack

- Physics: MuJoCo 3.8.1 in Python for the window robot. Newton 1.7.0 on CPU for the inspection robot.
- Browser: TypeScript, Vite, three.js, MuJoCo WASM for replay only, CodeMirror 6.
- Server: local Python servers for runs, site and board. `scripts/demo.sh` starts them.
- AI in the app: headless Claude Code calls that return typed data. Our validators check every reply.
- Sandbox: `sandbox-exec` with an import allowlist for edited controllers.
- Contract: Solidity, Foundry, `contracts/src/FailureBounty.sol`.
- Identity: `@worldcoin/idkit-core` with server-side verification in `policy/server/site_world.py`.
- Renders: Blender Cycles, from recorded runs.
- Generated objects: Qwen-Image-2512 and Hunyuan3D-2.1 on a rented GPU, CoACD hulls.

The full list with licenses is in `docs/THIRD-PARTY.md`. `AI-USE.md` lists who wrote what.

## Real, simulated, not connected

| Part | Status |
|---|---|
| Physics runs | Simulated. They really run in MuJoCo or Newton in `--stored` and live modes. In `--recorded` the app replays stored results, labelled "Recorded run" |
| Judge, failure grouping, boundary search, regression suite | Real code, with no model involved |
| AI calls | Real in live mode. `--stored` uses stored replies from earlier real calls, matched by exact message |
| The stored AI fix | A real AI edit from an earlier campaign, tested in the sandbox. It did not help |
| Hidden-world proof for a bounty fix | Real sims in the sandbox, in all three modes |
| Payout | Local ledger file with test units. No money moves |
| Contract | Written and tested on a local test EVM only. Not deployed anywhere |
| World ID | Set up on staging. A real scan is untested |
| Arc | Not deployed |
| 0G | Not connected |
| Window robot | Fictional. Our scripted Python controller |
| Inspection robot | ANYmal C model and upstream's walking policy, in hand-built worlds. Not checked against a real robot |
| Hull robot | A separate pack on a flat plate. Not in the app. The film is a concept |

## Sponsors: what runs today

**World.** The login page uses `@worldcoin/idkit-core`. The server verifies proofs in `policy/server/site_world.py`. The repo's `.env` sets `WORLD_ENVIRONMENT=staging`, and the page says so. The checks use mock replies. No result file in the repo shows a real scan. The bounty board does not read World ID: its page says "World ID is not connected", and its per-human cap trusts numbers from the caller.

CONFIRM: has a real World ID scan worked on staging? If yes, add the date and the result, and change this section and the table above.

**Arc.** Not deployed. Deployment code sits on the unmerged `sponsors-switch-on` branch and has run on local anvil only.

**0G.** Not connected. Code for it sits on the same unmerged branch and has run on mocks only.

**Local chain.** `contracts/src/FailureBounty.sol` has 41 passing tests under `forge test`. `policy/bounty/anvil_mirror.py` mirrors one accepted fix on a local anvil chain with public dev accounts and a test token. No human or outside firm has audited the contract.

<!-- 41: forge test, run 7 Nov: "41 tests passed, 0 failed, 0 skipped". -->

CONFIRM: which partners to select, at most 3. Today only World has anything running, and only on staging. The World tracks ask for a working verified path and an alternative path, so a real scan decides this.

## From Scratch track facts

- Hacking began Thu 5 Nov 2026 at 21:00 IST.
- The first commit is `3b81663`, dated 2026-11-05 23:03:21 +0530.
- `main` had 168 commits at `bf0a6ae`, spread over the event.
- Outside the repo, event research is dated 2 Nov. The idea and structure drew on an existing commercial category, simulation-based robot testing. A reference company's film informed some concept work, and its stills are not in git.

<!-- 21:00: ~/ethglobal-mumbai-research/03-ethglobal-mumbai.md. Commits: git log. -->

CONFIRM: enter the Classic / From Scratch track, and confirm that no code or design asset in this repo existed before 21:00. The git history shows nothing earlier, but it cannot prove that alone.

## Known limits

- Hand-built physics. Most values are assumptions, marked in `policy/highrise/PARAMETERS.md` and `policy/packs/hull/PARAMETERS.md`. Nothing is calibrated, and nothing is checked against hardware.
- We tuned parameters and world ranges after seeing results. The list is in `PARAMETERS.md`.
- The window sim's physics after a detach is unreliable, so the fall is not shown. A fresh AI audit found this, along with other limits (`docs/security/SIM-AUDIT-2026-11-06.md`). No human reviewed the audit.
- Scenarios are the AI's reasoned guesses, not evidence that these cases occur in real use.
- Airborne sand, snow and ice have no physics. Rain, snow and dust on screen are partly scenery, and the chat says which part has a model.
- `--stored` answers only the exact messages stored in `policy/server/fixtures/agent5.json`. Other words get a refusal.
- `--recorded` cannot change a world or re-run one.
- No fix for the Slipped failure exists. The payout in the demo is on a Stalled failure, using `policy/bounty/fixtures/fix5/good_match_fan.py`, a fix Claude wrote as a test source.
- A passed fix says something about these worlds in this simulator. It says nothing about a real robot.
- `sandbox-exec` shares the kernel and is not a VM. A runtime escape test did not run.
- The app runs on one Mac, with local servers. It is not a hosted service. Replay across machines is untested.
- Importing your own robot is not built.
- Generated objects stay fixed, and their mass comes from a table of guesses. Hunyuan3D-2.1's license limits commercial use.
- The repo has no license file yet.

## Links to fill in

CONFIRM: team members and their ETHGlobal accounts.

CONFIRM: the demo video link. Partner judges read the video, the repo and this write-up.

CONFIRM: the repo URL. `origin` is `https://github.com/varunlohade/robobounty`, and it must be public at submission.

CONFIRM: no hosted demo exists. Say "run locally, see README" unless that changes.
