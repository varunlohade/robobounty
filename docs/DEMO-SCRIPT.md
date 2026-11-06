# CrashLab demo script

Finalist slot: 4 minutes of demo, then 3 minutes of Q&A. Judges score Technicality, Originality, Practicality, Usability and WOW, in that order.

This script has 521 spoken words. At 140 words a minute that is about 3:43. Read it aloud once with a timer before the slot, because the word count is only an estimate. If you run long, cut the lines marked (cut first).

Open before you start:

- `http://localhost:5199/app.html?recorded=1`. It needs only `npx vite --port 5199`.
- `design/render/clip_slip.mp4` in a muted player.
- If you show the bounty live, walk the live flow first with the first 12 worlds. That took 5 to 7 minutes here, with 25 to 69 s for the gate and 60 s for the dispute window. `design/video/draft.mp4` has the same scene, so you can play that part instead.

## The script

### 0:00 Cold open (25 s)

*Show: `clip_slip.mp4`. Say the first line over the slide.*

> Wind near 36 metres a second. A window robot on a glass tower. Watch it go.
>
> That robot does not exist. This is a recorded simulator run, drawn again in Blender. This world slid in 2 of 3 repeats. The third came off the glass.
>
> We want you to find this on a laptop, before anyone hangs hardware on a tower.

### 0:25 Brief (30 s)

*Show: app, chat scrolled to the top.*

> This is CrashLab. Chat on the left, simulation on the right. You describe the robot and the place in plain English.
>
> Here the brief says glass towers in Dubai: strong wind, humidity, low and high friction, odd edges, heat. The AI turns those words into numbers. Our code checks every number before it builds anything.
>
> Seven pass or fail rules go down before any run.

### 0:55 Worlds (30 s)

*Show: `52 worlds` tab, the map at the top. Point at the group names and the "Not tested" list.*

> A scenario agent reads the chat and picks the tests. Here it chose 52 worlds in 8 groups. We didn't set that number. It gives its reason too.
>
> A factor counts only if it changes the physics in code. Airborne sand has no model here, so it goes on this list: not tested. It never gets a fake pass.

### 1:25 Test (25 s)

*Show: the map, then the Report tab.*

> The robot is a scripted controller we wrote. The AI sits in the test loop, and it does not drive the robot. The same code runs in every world.
>
> Of 52: 31 failed, 13 stopped and held on, 5 were flaky, 3 passed. Normal runs passed 10 of 10. We picked these worlds to be harsh, so this count says nothing about reliability.

### 1:50 Find (45 s)

*Show: replay world_016, then the failure table, then `controller.py`.*

> Each failure gets three repeats. The 5 flaky ones are out, in plain view. This replay shows states recorded in Python MuJoCo.
>
> Failures fall into 5 types, each with a count and a code line. One finding held up in audit. The low-pressure guard goes blind once fan speed passes 0.896. All 9 times the robot came off the glass, its estimate read safe while true pressure sat under the limit.
>
> Better sensing alone did not solve it. With true pressure in 29 re-runs, it came off 8 times, not 9. (cut first)

### 2:35 Fix (35 s)

*Show: Fix tab with the diff in the chat.*

> The AI tried a fix: one constant, suction while cleaning, 0.85 to 0.9.
>
> We wrote the test plan down first, then ran 104 fresh worlds. Passes went from 11 to 17. Failures went from 67 to 60. Zero got worse.
>
> We did not apply it. That speed takes the guard away while cleaning, and the test can't measure that loss. A later live AI try got 0 better. So no fix is proven safe.

### 3:10 Bounty (30 s)

*Show: Bounty tab, or the bounty part of `draft.mp4`.*

> What the AI can't fix goes to a bounty. A tester sends a world file that breaks the robot. Our gate re-runs it 8 times with hidden jitter, and 7 must fail alike.
>
> A passing world gets rejected. A new failure gets accepted, waits out a dispute window, and pays once.

*Say the next line if the ledger is on screen. If you switched on a chain, say what you switched on and show the transaction.*

> This one runs on a local ledger with test units. The contract is written with 41 tests, and it is not deployed.

### 3:40 Limits (20 s)

*Show: Report tab, or the "Not tested" list.*

> So, the limits. One robot. Hand-built physics, not checked against real hardware. Every number here holds in this simulator only. Use it to find questions to ask, not to prove a robot safe.
>
> Thank you.

## Likely questions

**Why not just use an existing tool?**
Mature robot simulators and commercial test products exist, and our idea and structure drew on that category. For a real robot program, use them first. They have calibrated physics and we don't. Our bet is a smaller one: plain English in, a plain list of what was and was not tested out, and an open bounty for the gaps. We have not compared ourselves head to head, so we can't tell you we're better.

**Is the physics real?**
The equations are standard: adhesion from pressure times area, a fan curve, orifice leak, air density, dew point, battery sag. The engine is MuJoCo. Most constants are assumptions, marked as such in `policy/highrise/PARAMETERS.md`. Nothing is calibrated to hardware. Sand and dust are simplified: dust changes leak, friction and sensor noise, and airborne sand has no model. A fresh AI audit (`docs/security/SIM-AUDIT-2026-11-06.md`) found wind blowing out of a solid wall. We clamped it and voided the numbers from before. The audit also says the 10 m/s pause rule causes `time_limit`, and a threshold sets the `false_done` count. No human has reviewed it.

**Did you plant the bug?**
We didn't write the guard to fail, but you can't take that on trust. `controller.py` is frozen at commit `af0424f`, before the final campaigns, and its hash is in every result. The audit found no world-keyed or seed-keyed branch. Now the caveats. We tuned physics and world ranges after seeing results, and that list is in `PARAMETERS.md`. Some of that tuning came before the freeze, and git can't fully confirm its order. The 3 replays on screen repeated 3 of 3. The opening clip repeated 2 of 3.

**Why on-chain?**
A company should not be both the payer and the judge of a claim that its own robot broke. Escrow and a dispute window let a stranger trust the payout rules before doing the work. That is the only reason. The test loop needs no chain. Today it is `contracts/src/FailureBounty.sol` with 41 local tests, no outside audit, and no deployment unless we say otherwise on stage. The gate itself runs on one machine, so the chain does not prove the sim ran fairly. The named arbiter and the company's limits do much of that work.

**Is 3 of 52 your pass rate?**
No. We chose those worlds to stress the robot, and the physics is uncalibrated. It is a count for this set of worlds.

**What does the AI actually do?**
It turns chat into numbers, proposes scenario groups and counts, words the diagnosis, and proposes controller edits. Our code validates all of it. Our code does the judging, the failure grouping and the bounty verdict, with no model involved. `AI-USE.md` lists it file by file. Most of the code was written with Claude Code, under our direction.

**Can a tester game the bounty?**
Partly. A world that fails 70% of the time still clears 7 of 8 about 1 time in 4. A world at 90% clears about 4 times in 5. The gate can't prove a world is fair. World ID isn't connected, so the per-human cap trusts numbers from the caller. The test worlds for the gate came from a search, so its check proves the logic and not how well it sorts new worlds.

**Could an AI patch hurt you?**
It edits a copy, runs under `sandbox-exec`, and passes an import allowlist. `sandbox-exec` is not a VM. A runtime escape test did not run. The review found no Critical or High issue it could prove, but it mostly read code.

**Does replay work across machines?**
Unknown. We have not tested it.

**Why was the slip clip not one of your 3-of-3 replays?**
It looks clearer on camera. It is a real entry in the campaign, world_010, with an extreme gust, and it met the rule of 2 of 3 repeats. We say so when we show it.

## Fallbacks

- Run server down: `app.html?recorded=1` needs only vite. It shows no bounty, because a recorded run takes none.
- Bounty too slow on stage: play that part of `design/video/draft.mp4`. It shows a real gate run with the waits cut, and says so.
- Do not start a live AI fix on stage. It takes minutes, and the recorded try found 0 better.
