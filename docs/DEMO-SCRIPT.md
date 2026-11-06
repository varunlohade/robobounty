# CrashLab demo: 3 minutes

The talk is 180 seconds, with nothing spare. Cut the Open file line if you run late. Quoted lines are the words to say. `Code` is what to type. All results are simulated.

Partner judges watch the video. Finalists get 4 minutes plus 3 minutes of questions, so this script fits both.

CONFIRM: nobody has rehearsed this aloud. App waits are measured. Spoken times are estimates at about 2.5 words a second.

CONFIRM: this script enters as local guest. Change step 1 only if a real World ID scan has worked on staging.

<!-- App wait times:
design/e2e/stored/timing.json: `--stored` run, 7 Nov. 08-ai-builds 6.5 s, 10-list-scenarios 0.6 s, 12-grid-done 18.4 s, 20-ask-ai-did-not-help 147.5 s.
design/e2e/recorded/timing.json: `--recorded` run, 7 Nov. 12-grid-done 22.1 s, 13-red-square 0.5 s, 15-open-file 0.2 s, 16-ask-ai 0.1 s, 18-bounty-shows 1.1 s, 21-hidden-world-proof 120.1 s, 23-finalize 59.0 s, 25-claim 0.1 s.
Not in timing.json, measured 7 Nov with a headless Chrome script against `--stored`: brief 7.7 s, wind and wet change 17.1 s, list 0.8 s, grid on that changed world 46.7 s, a real Find the limit 43.9 s. Same method against `--recorded`, with both servers up: Find the limit 0.1 s, labelled recorded. -->

## Why two servers

Each mode can do only part of the flow.

- `--stored` runs real physics, so typed world changes work. It answers only exact stored messages. The grid on the changed world takes 47 seconds, and Ask AI re-tests for 148 seconds. In our run the bounty fix came back "Not fixed", 3 of 4 worlds, so this mode pays nothing.
- `--recorded` replays stored results. Its grid takes 22 seconds, Ask AI answers at once, and the end-to-end check pays out. It refuses world changes.

So the talk starts on `--stored`, then moves to `--recorded` for the rest, and says so aloud.

## Set up, about 8 minutes before you speak

The owner's vite may hold port 5199, so use these ports. Run each command in its own terminal.

```
npm run demo -- --stored --ports 6499,6498,6497,6496
npm run demo -- --recorded --ports 6199,6198,6297,6298 --board-root /tmp/crashlab-board
```

Delete `/tmp/crashlab-board` first if it exists. Then open five tabs, in this order.

**Tab 1, the opening.** Open `http://localhost:6499/`. Leave it on the login page.

**Tab 3, the payout. Do this one early, because it needs about 3 minutes of waiting.**

1. Open `http://localhost:6199/`, click Enter as local guest, then CrashLab, Window cleaning, Open CrashLab.
2. Click List test scenarios, then Run 34 scenarios. Wait for the grid to finish.
3. Click a red Slipped square, then Open file, then Ask AI to fix: Slipped (6).
4. Click Post a bounty. Title: `The robot slides on low suction`. Company: `Tower Services (test company)`. Click Post the bounty.
5. Click Post a bounty, top right. Choose the Stalled failure. Title: `The robot stops short near the top`. Company: `Tower Services (test company)`. Click Post the bounty.
6. Click Submit a fix. Name: `ana`. Paste all of `policy/bounty/fixtures/fix5/good_match_fan.py`. Click Run check, then simulation.
7. Wait for Accepted, about 2 minutes. Wait until Finalize lights up, about 1 more minute. Leave it unclicked.
8. Do not reload this tab. It holds the claim secret.

**Tab 2, the grid.** Open `http://localhost:6199/crashlab.html`, choose Window cleaning, click Open CrashLab, then List test scenarios. Stop at the Run 34 scenarios button.

**Tab 4, the limit.** Open CrashLab the same way. List, run, and wait. Click a red Low coverage square. Stop at the Find the limit button.

**Tab 5, the robots.** Open `http://localhost:6199/crashlab.html`.

**The film.** Open `design/shell/hull-film.mp4` in a video player, paused at the start. It runs 13 seconds and has no audio track.

## The talk

### 0:00 Login wall (10 s)

Tab 1. Click **Enter as local guest**.

> "Crash tests for robots. You describe the job, AI builds the tests, and people get paid when their fix passes. Every run behind this panel is simulated."

*Fallback: if the film wall is blank, the panel still works. Say nothing about it. If Tab 1 is dead, go to Tab 2 at 0:47 and say the world change cannot run today.*

### 0:10 Pick a robot (7 s)

Click **CrashLab**, **Window cleaning**, **Open CrashLab**.

> "We pick a robot. This window cleaner is fictional. Its controller is a script we wrote."

*Fallback: Tab 2 is already past this step.*

### 0:17 Say the job (10 s)

Type, then press Enter. The wait is about 8 seconds.

`Window robot for towers in Dubai. High floor.`

> "I say where it works. These AI replies are stored from earlier real calls. Code checks every value."

*Fallback: on a "cannot" reply, check the words. `--stored` needs the exact text.*

### 0:27 Change the world (20 s)

Type, then press Enter. The wait is about 17 seconds, while the world runs again.

`Make the wind stronger and wet the glass.`

> "Now I change the world. Wind goes up, and the glass gets wet. MuJoCo runs it again, right now, on this laptop. Look at the numbers in the chat. Cleaning falls, because the robot waits out the wind."

Point at the "Cleaned" line. In our timing run it read 95.1% to 8.2%.

*Fallback: if it takes over 20 seconds, keep talking, and move to Tab 2 at 0:47. If the server is down, show `design/e2e/stored/09-change-world.png` and say: "Here is a saved picture of a world change. That one changes the paint."*

### 0:47 List scenarios (8 s)

Click **List test scenarios**.

> "The AI lists what could go wrong. Each reason is labelled a guess. What has no physics goes on a not-tested list."

*Fallback: Tab 2 already shows a list.*

### 0:55 Run the grid (23 s)

Go to Tab 2. Click **Run 34 scenarios**. It plays for 22 seconds.

> "This changed world takes 47 seconds to run, so I am switching to the recorded batch of the plain tower. It says Recorded run on screen. Each square is one world. Red means failed or stuck. A judge written in code decides, with no model involved."

*Fallback: if the grid stalls, open Tab 4, which finished earlier. If the recorded server is down, show `design/shell/grid-video-window.mp4`.*

### 1:18 Click a red square (11 s)

Click a red **Slipped** square.

> "We replay the recorded run. The robot slid more than 30 centimetres in one slide, and the limit is 30. The panel gives the judge's reason and the log."

Read the number from the panel. World "Suction moderately reduced" reads 0.302 m.

*Fallback: show `design/e2e/recorded/13-red-square-detail-replay.png`.*

### 1:29 Open file (7 s)

Click **Open file**.

> "Open file goes to the line that ran when the limit fired. Any edit stays in a session copy."

*Fallback: show `design/e2e/recorded/15-open-file.png`.*

### 1:36 AI fix did not help (14 s)

Click **Ask AI to fix: Slipped (6)**.

> "An AI tried this earlier. It raised suction from 0.85 to 0.92. It made none of the 6 failed worlds better. So code did not apply it, and the card says Recorded result."

*Fallback: show `design/e2e/recorded/16-ask-ai-did-not-help.png`. Never start a live AI fix on stage.*

### 1:50 Post a bounty (9 s)

Click **Post a bounty**. Title: `The robot slides on low suction`. Click **Post the bounty**.

> "So a company posts a bounty. The pay is in test units. A person can now try to fix it."

*Fallback: Tab 3 already lists this bounty.*

### 1:59 Hidden proof (16 s)

Go to Tab 3. Scroll to Hidden worlds.

> "Nobody has fixed that slide yet, so this is a stall from the same batch. Before this talk I submitted a fix Claude wrote as a test. Code ran it on 45 hidden worlds for 2 minutes. The submitter sees only counts."

*Fallback: if Tab 3 failed or was reloaded, show `design/e2e/recorded/21-hidden-world-proof.png` and say "a saved picture from tonight's check".*

### 2:15 Payout (10 s)

Click **Finalize**. Type `ana` in the box. Click **Claim**.

> "A dispute window passed, so anyone can finalize. Then the submitter claims. 40 test units, on a local ledger. No chain, and no money moved."

*Fallback: show `design/e2e/recorded/25-claim.png`.*

### 2:25 Find the limit (13 s)

Go to Tab 4. Click **Find the limit**.

> "Find the limit changes one factor at a time. This stored search says failure starts between seal leak 240 and 280 square millimetres. Other searches found no clean boundary, and they say that too."

*Fallback: the search is already recorded. If the panel fails, read that line from `policy/runs/demo/window/boundary.json` and move on.*

### 2:38 Two robots (8 s)

Go to Tab 5. Point at the two cards.

> "Two robots run in this flow today. The other is an ANYmal C model with upstream's walking policy, on Newton."

*Fallback: show `design/shell/grid-video-inspection.mp4`.*

### 2:46 Hull film, as a concept (14 s)

Play the film.

> "This last one is a concept. A hull cleaner, rendered from one recorded run on a flat plate. The water and the curve are scenery. It is not in the app yet. Thank you."

*Fallback: show `design/shell/hull-still-1.png`.*

## If they ask

**Is it real?**

"The software is real and the runs really happen in a simulator. The physics is hand-built, the values are assumed, and nothing has been checked against hardware. Use it to find questions to ask. It does not prove a robot safe."

**Which parts did you run live just now?**

"The world change ran real physics, using a stored AI reply. The grid, the AI fix and the limit search replayed recorded results, and the screen labels them. The hidden proof ran real sims before the talk. The payout click wrote to a local ledger."

**Does AI drive the robot?**

"No. The window robot runs a script we wrote. The inspection robot runs upstream's walking policy, which we did not train. AI edits the world, lists scenarios and proposes fixes. Code checks all of it and decides every result."

**Would this fix work on a real robot?**

"We do not know. A pass says something about these worlds in this simulator, and nothing about a real robot."

**Are these scenarios things that really happen?**

"They are the AI's reasoned guesses, and the app labels them so."

**Is any money or chain involved?**

"No. The payout is a local file in test units. The contract has 41 passing tests on a local test chain, with no audit and no deployment. Arc is not deployed, and 0G is not connected."

**Is World ID working?**

"It is set up on staging, and a real scan is untested. The bounty board does not read it, so its cap counts names and not people."

CONFIRM: update this answer if a real scan works.

**Can a tester game the bounty?**

"Partly. A patch can fit the worlds it sees, which is why we keep some hidden. The board does not check for collusion, and the sandbox shares the kernel with the host. The page lists these under Not checked."

**Did you plant the failure?**

"You cannot take that on trust. We tuned physics and world ranges after seeing results, and `policy/highrise/PARAMETERS.md` lists that for the older campaign. The judge and sim hashes show on every bounty."

**Who wrote this?**

"AI wrote most of the code, under one builder's direction. `AI-USE.md` lists it file by file."

<!-- 41 tests: forge test, 7 Nov. 45 hidden, 40 test units, 2 minutes (122.3 s): design/e2e/recorded/21-hidden-world-proof.png, 25-claim.png. 0.85 to 0.92, 0 of 6: policy/runs/demo/window/stored_fix.json. 240 and 280: policy/runs/demo/window/boundary.json. 95.1% to 8.2%: the chat in our timing run on `--stored`, 7 Nov. Film 13 s, no audio: ffprobe design/shell/hull-film.mp4. -->
