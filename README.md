# CrashLab

CrashLab tests a robot in simulated worlds that it builds from plain English. You describe the robot and where it works. An AI agent proposes the worlds, our code runs and judges them in MuJoCo, and failures are traced to a line of the controller. An AI tries a fix, and what stays unsolved can go to a bounty for outside testers.

The demo robot is a window cleaner for glass towers. It is a fictional robot we built for this hackathon, and it runs a scripted Python controller we wrote. AI works in the test loop and does not control the robot. All results are simulated. The physics is hand-built and has not been checked against real hardware.

Built at ETHGlobal Mumbai, 5 to 7 November 2026. The first commit is dated 5 Nov, 23:03 IST.

The idea and structure drew on an existing commercial product category, simulation-based robot testing. The code, words and visuals here are our own. See "AI disclosure" for who wrote what.

## Run it

Tested on macOS on Apple Silicon, with Node 26 and Python 3.12.

### Recorded run (fastest)

This needs no Python, no AI and no run server. It loads the finished Dubai campaign from a file.

```
git clone <this repo> crashlab
cd crashlab
npm ci
npx vite --port 5199
```

Open `http://localhost:5199/app.html?recorded=1`. The app labels this mode "Recorded run". It has no bounty, because a recorded run takes no submissions.

### Live run

Set up Python once. Use Python 3.12: the pinned numpy has no ready-made wheel for 3.14.

```
python3.12 -m venv policy/.venv
policy/.venv/bin/pip install mujoco==3.8.1 numpy==2.2.6 pillow
```

Keep vite running. In a second terminal, start the run server. Choose one line:

```
policy/.venv/bin/python policy/server/server.py --recorded policy/server/fixtures
policy/.venv/bin/python policy/server/server.py
```

The first line uses stored AI replies, so it makes no AI call. The second makes real calls through the `claude` command-line tool, which must be installed and logged in. It has a limit of 10 calls a session and 40 an hour.

Open `http://localhost:5199/app.html`. The simulations, the judging and the bounty gate run for real in both modes.

### Checks

```
python3 policy/crashlab/check_numbers.py --evidence
policy/.venv/bin/python policy/highrise/run_trial.py policy/highrise/worlds/nominal.json --seed 1 --out /tmp/crashlab-nominal
```

The first line recomputes every headline number from `docs/evidence/` and needs only Python's standard library. The second line runs one world.

The contract tests need Foundry:

```
cd contracts
forge install foundry-rs/forge-std@v1.17.0 --no-git
forge test
```

## The loop

1. **Brief.** You type what the robot is and where it works. The AI asks one or two questions and returns numbers from a fixed schema. Our code checks them.
2. **World.** The browser builds and shows the world. The robot runs once and you confirm the scene.
3. **Requirements.** Seven numbered pass or fail rules go down before the campaign.
4. **Worlds.** A scenario agent reads the chat and proposes groups, ranges and a world count, with reasons. You review it before anything runs. Anything with no physics goes on a "Not tested" list.
5. **Test.** The same controller runs in every world. Failures are re-run three times, and any that come back fewer than 2 times are marked flaky and left out, in plain view.
6. **Find.** Failures are grouped into types, each with a count, a worst world and a code line. Any failed world with a replay can be opened in the browser.
7. **Fix.** An AI edits a copy of the controller. Our code tests the copy against the original on the same worlds and on held-back worlds. Accepting a fix writes a session copy only. `policy/highrise/controller.py` never changes.
8. **Bounty.** Open failures and gaps can go to a bounty. A tester submits a numeric world file. The gate runs it once, then 8 times with hidden jitter. At least 7 must end in the same failure, and a nearby reference world must pass.

## Architecture

| Part | Path | What it does |
|---|---|---|
| App | `app.html`, `src/app/` | Chat, world view, worlds map, fix and bounty pages. TypeScript, Three.js |
| Browser MuJoCo | `src/app/replay.ts` | MuJoCo 3.16 in WASM. It sets recorded states and never steps physics |
| Run server | `policy/server/` | Local chat flow on 127.0.0.1:5198. Refuses other origins. Runs at most 4 sim or AI processes at once |
| Simulator | `policy/highrise/` | MuJoCo 3.8.1 in Python: world builder, suction, wind and battery models, controller, judge, campaign runner |
| AI layer | `policy/crashlab/llm.py`, `brief_highrise.py`, `scenarios.py`, `diagnose.py`, `fix.py` | Headless Claude Code calls. Replies are schema-checked numbers, or wording checked against our tables |
| Bounty gate | `policy/bounty/gate.py` | Validates a world, re-runs it and writes a verdict. No model takes part |
| Ledger | `policy/server/ledger.py` | Local copy of the contract's states |
| Contract | `contracts/src/FailureBounty.sol` | Escrow, propose, dispute window, finalize, claim, refund, in a 6-decimal token |
| Renders | `policy/render/` | Blender re-renders of recorded runs |
| Evidence | `docs/evidence/`, `policy/crashlab/check_numbers.py` | JSON summaries of the runs, and the check that recomputes the numbers |

`index.html`, `src/main.ts`, `src/challenges/` and the LIBERO tools in `policy/crashlab/` are earlier prototypes under the old working name, RoboBounty. They are not part of the CrashLab flow.

## What is real

- MuJoCo runs every world, with the physics in `policy/highrise/sim.py`. The sim hash is in each result.
- `controller.py` has not changed since commit `af0424f`, before the final campaigns. Its hash is in each result, and `check_numbers.py` compares it.
- The judge is code. No model decides a pass or a failure.
- The AI calls are real in a live run. The stored replies in `policy/server/fixtures/` came from such calls.
- Replays in the browser show states recorded in Python.
- The gate runs real simulations for each submission.
- The contract has 41 passing tests on a local test EVM.

## What is a labelled shortcut

- **Run server.** The live app talks to a Python server on your own machine. It is a demo shortcut, not a hosted service.
- **Recorded run.** `app.html?recorded=1` loads results from a file. No AI and no simulation run.
- **Stored fix.** In a live run, "Show the recorded result" shows the stored report for the fix. It came from an earlier campaign, and the app labels it "Recorded result". That button reads `policy/runs/`, which is not in git, so it fails on a fresh clone. The Recorded run shows the same result, and the summaries are in `docs/evidence/`.
- **Local ledger.** By default the bounty writes to a local file, labelled "Local ledger. Not on chain." Amounts are test units and no money moves.
- **Contract.** It is not deployed. No human or outside firm has audited it.
- **Blender clips.** The robot's pose and the dirt come from recorded runs. Sky, city, haze, camera and grade are art. They are labelled "Re-render of recorded physics".
- **Concept stills.** `design/film/` holds AI concept images, not simulation output.

## Limits

- One robot. Most constants are assumptions, marked in `policy/highrise/PARAMETERS.md`. Nothing is calibrated.
- Not tested, because no physics covers it: airborne sand, wind by height, sun and glare, rain, ice, snow, salt, and real motors, sensors and tether wear. Dust is modelled only as added leak, friction change and sensor noise, with assumed values.
- We tuned parameters and world ranges after seeing results, before the freeze. The list is in `PARAMETERS.md`. Git cannot fully confirm the order.
- A fresh AI audit (`docs/security/SIM-AUDIT-2026-11-06.md`) found wind blowing out of a solid wall. We clamped it and voided earlier numbers. The audit also found that the 10 m/s pause rule causes `time_limit`, that a threshold sets the `false_done` count, and that physics after a detach is unreliable. No human reviewed it.
- The gate's own test worlds came from a search, so its check proves the logic and not how well it sorts new worlds. A world that fails 70% of the time still clears about 1 time in 4.
- World ID is not connected. The per-human cap trusts numbers from the caller.
- `sandbox-exec` is one layer and is not a VM. A runtime escape test did not run. The security review (`docs/security/REVIEW-2026-11-06.md`) found no Critical or High issue that it could prove, but it mostly read code.
- Replay across machines is untested.
- The repo has no licence file yet.

## Results

All from one campaign, `campaign_dubai_final`, on sim `0e36d3bf`. These count what happened in worlds chosen to stress the robot. They are not a measure of reliability.

| Result | Count | Evidence |
|---|---|---|
| Worlds the agent chose, in 8 groups | 52 | `docs/evidence/scenarios.json` |
| Failed | 31 | `docs/evidence/results.jsonl` |
| Stopped and held on | 13 | same |
| Flaky, left out | 5 | `docs/evidence/diagnosis.json` |
| Passed | 3 | same |
| Normal control runs passed | 10 of 10 | `docs/evidence/results.jsonl` |

Failure types: 17 slid too far, 9 came off the glass, 3 reported done when not done, 1 stalled, 1 ran out of time.

**One finding.** The low-pressure guard goes blind above fan speed 0.896 (`controller.py:36`, `controller.py:108`). In all 9 detaches, the estimate read safe while true pressure was under the limit. Better sensing alone did not solve it: given true pressure in 29 re-runs, the robot came off 8 times, not 9. In 5 of the 9 it had already stopped with suction at full.

**The AI fix: not applied.** One change, suction while cleaning from 0.85 to 0.9, on 104 fresh worlds under a plan written first (`docs/evidence/retest_PLAN.md`, `docs/evidence/retest_report.json`).

| | Before | After |
|---|---|---|
| Passed | 11 | 17 |
| Failed | 67 | 60 |
| Normal runs passed | 20 of 20 | 20 of 20 |

Six worlds went from failed to passed. One went from stalled to a battery stop, which is not a pass. One moved from a slide to a stall. None got worse. The patch also removes the low-pressure guard while cleaning, and this test does not measure that loss. A later live AI try, on 11 check worlds and 12 held-back worlds, got 0 better and 0 worse (`docs/evidence/live_fix_report.json`).

## Third-party software and assets

| Item | Licence | Use |
|---|---|---|
| MuJoCo (Python 3.8.1, `@mujoco/mujoco` 3.16.0) | Apache-2.0 | Physics |
| three.js 0.180.0 | MIT | Browser 3D |
| Vite 7.1.12, esbuild | MIT | Dev server, build |
| TypeScript 5.9.3 | Apache-2.0 | Language |
| NumPy 2.2.6 | BSD-3-Clause | Python numbers |
| Pillow | MIT-CMU | Images |
| forge-std v1.17.0 | MIT or Apache-2.0 | Contract tests, installed by the command above |
| Foundry | MIT or Apache-2.0 | Contract test tool, not bundled |
| Blender | GPL | Renderer, not bundled |
| "Overcast Soil (Pure Sky)" by Sergej Majboroda, with sky edits by Jarod Guest (Poly Haven) | CC0 | Sky in renders. Downloaded at render time, not in git |

The earlier prototype used LIBERO and the model HuggingFaceVLA/smolvla_libero. Neither is ours or in the CrashLab flow.

## AI disclosure

AI wrote most of this code and these documents, directed and reviewed by the human builder. [AI-USE.md](AI-USE.md) lists which tools wrote which files. Plans and specs are in `docs/`.
