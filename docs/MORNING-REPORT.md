# Morning report, Fri 6 Nov 2026

**The whole loop works end to end in the app, with a labelled local ledger instead of a chain.** Nothing is pushed, published or paid. About 27 hours remain until Sat 09:00.

## See it first
1. App, instant recorded run: http://localhost:5199/app.html?recorded=1 (needs the dev server: `npx vite --port 5199`, and the run server in `policy/server/` for live mode).
2. Site draft: `design/site-draft/index.html`.
3. Film concept stills: `design/film/keyframes/_sheet.png`.
4. Blender clips: `design/render/clip.mp4` (older run), `design/render/clip_slip.mp4`. See status below.

## Results (simulated; hand-built physics; not checked against real hardware)
Dubai brief, campaign_dubai_final, sim 0e36d3bf. `policy/crashlab/check_numbers.py` recomputes 97 numbers and they all match.

| Result | Count |
|---|---|
| Worlds the AI chose | 52 |
| Failed | 31 |
| Stopped and held on | 13 |
| Flaky, excluded | 5 |
| Passed | 3 |
| Normal controls | 10 of 10 |

**AI fix:** no fix is proven safe to apply.
- Larger pre-planned test on 104 fresh worlds: passes rose from 11 to 17, 67 failures fell to 60, 0 worse, p 0.0078. "7 better" is 6 passes plus 1 stalled-to-battery-stop.
- The catch: the patch only helps by removing the low-pressure guard during cleaning. It is not applied.
- A later live AI attempt in the app: 0 better.

**Bounty:** gate needs 7 of 8 re-runs. In the app, a bad file and a passing world get rejected, and a new slip failure gets accepted and paid on a local ledger. A world failing 70% of the time still clears about 1 time in 4.

**Contract:** `contracts/src/FailureBounty.sol`, 41 local tests pass. Not deployed.

**Security:** review found no Critical or High that it could prove, but it mostly read code. A runtime sandbox escape test did not run. `docs/security/REVIEW-2026-11-06.md`.

## What went wrong overnight
- First results used a physics error (wind blowing out of a wall). An audit caught it. Numbers before that are void. `docs/security/SIM-AUDIT-2026-11-06.md`.
- Tuning happened after seeing results, before the final freeze. It is recorded in `policy/highrise/PARAMETERS.md`. So "no planted bug" holds for the code, with that caveat.
- One worker deleted earlier AI-fix attempts before I made a rule against it, including a run with 184 result files. It listed them in `fix/attempts/2026-11-06_discarded/record.json` and says no valid fix test was lost.
- The gate's check uses test worlds searched to give the wanted results, so it proves the logic, not how well it sorts real worlds.
- I told you numbers were frozen when one campaign was on an older sim. It is re-run now. The drift came from seeds, not the sim.

## Do not claim
"Scientifically accurate", "real failures", any pass rate as reliability, sandstorm physics, "first", or "AI robot" (the robot runs a scripted controller we wrote; the AI is in the test loop). The reactor and tower film stills are concept art, not product footage.

## Decisions for you
1. **Sponsors: Arc, 0G, World.** My pick is Arc for USDC. Please ask the Arc booth first: does a contract written outside Arc Studio qualify? Steps: `docs/research/sponsors.md`.
2. **Accounts and keys.** The contract, 0G and World ID need accounts, a testnet wallet and tokens from you. I can't create them. Without them, the demo stays on the local ledger. Plan's latest start: about 14:00 for the contract, 20:00-22:00 for the others.
3. **Bounty scope.** You said anything untested can go to a bounty. A tester can only submit worlds the sim can run, so airborne sand can't be judged yet. For Saturday the site says this plainly. OK?
4. **Bounty rule.** 7 of 8 pays more flaky worlds. 8 of 8 is stricter (a 70% world clears 5.8%) but rejects many real ones (a 90% world clears only 43%). I kept 7 of 8.
5. **Veo film.** Blender is free and real motion. True cinematic motion for the concept film needs Veo, your spending limit and your key. Skip it if the Blender clips are good enough for you.
6. **Public repo.** ETHGlobal judges read the repo. Check the rules before charging for this later. `design/BRIEF-round3.md:5` and `.gitignore:23` name the reference company: your call.
7. **Name.** "CrashLab" has had no name check.

## Next if you say go
Sponsor integrations once keys exist, a security re-check of them, the demo script and video, README and limits, then submission by 07:30 Saturday.
