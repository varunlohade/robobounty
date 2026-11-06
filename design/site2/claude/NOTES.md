# CrashLab site, notes

Idea: every number opens the run behind it. The only loud thing on screen is the simulation.

## Tokens
From design/claude/NOTES.md, round 5, unchanged. Surfaces #0B0C0E, #111317, #16191E, #1E2228, #262B32. Text #ECEEF1, #A3A9B3, #737A85, #4B515B. Accent #3E7BFA for action, focus and selection only. Status red #E5534B, amber #D69A2D, green #3FA66A. Failure types: slip #D3A017, detach #14A39A, false done #9A78F0, time or stall #E2574C. Passed #C9CED6. Safe holds and hidden worlds are hatched.
Type: Inter 400 and 500, JetBrains Mono for code, hashes and file names only. One added size: 56 for the home counts.
Motion: colour and hover 120ms ease-out, press scale .97 at 160ms, tooltip 150ms, detail swap 160ms, the Open CrashLab frame grows to the window in 460ms on the sheet curve. Nothing else moves. Reduced motion is honoured.

## Real against sample
Real, from docs/evidence and the brief: batch totals, all of campaign_dubai_final (per-world rows, types, re-runs, code lines), retest numbers, requirements R1 to R7, Newton and inspection results.
Sample, marked on screen: bounty pay, ledger totals, hidden world counts, submissions. Unmarked but also a design stand-in: the verified id in the sidebar and the login QR, which encodes a text note and no live request. World ID is not connected in the code today; Providers says so.
The world rows for the 33 and 34 batches are not on disk, so Data shows totals for those and details for campaign_dubai_final.

## What the references taught
Immunefi: a reward column you can scan and sort beats cards. Its art-heavy hero is what to avoid.
Kaggle: filter first, then rows.
Rerun: hard technical facts set plainly earn the trust; one code block beats a paragraph.
World ID: say what is proved and that nothing personal travels. grayswan, Linear, Vercel and Foxglove were not opened; their conventions are from memory.

## Rebuild
python3 tools/build.py, then node tools/render.mjs. Extra states are in renders/. Motion is renders/motion.mp4 (node tools/render.mjs video).
