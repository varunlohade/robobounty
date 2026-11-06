# Round 5: professional app interface

Idea: a quiet instrument for finding out how a robot fails. The only loud thing on screen is the simulation.

## Tokens
Surfaces: app #0B0C0E, panel #111317, raised #16191E, hover #1E2228, active #262B32.
Lines: hairline rgba(255,255,255,.07), strong rgba(255,255,255,.12). Depth comes from surface steps. Lines only split panels.
Text: primary #ECEEF1, secondary #A3A9B3, muted #737A85, disabled #4B515B.
Accent (primary action, focus, selection only): #3E7BFA, hover #5089FB, press #2F6AE6, text #7DA7FF, focus ring #3E7BFA at 45%.
Status (icon plus label, never colour alone): red #E5534B / text #F27B73, amber #D69A2D / text #E3B04F, green #3FA66A / text #5CC186.
Failure types, checked with the palette validator on all pairs: suction loss #E2574C, slip distance #D3A017, edge detach #14A39A, tether slack #9A78F0. Amber sits 0.06 over the lightness band; a darker amber fails colour-blind separation from red, so separation wins.
Heat map non-failures stay neutral: passed #C9CED6, held back #2A2F37, flaky hatched.
Type: Inter for all interface text with tabular numbers. JetBrains Mono for code, hashes and file names only.
Type scale: 11/16, 12/16, 13/20, 14/20, 16/24, 20/28. Weights 400 and 500 only. Body is 13.
Space: 4px grid (4, 8, 12, 16, 24). Rows: 24 compact, 28 control, 32 table.
Radii: 4 controls inside controls, 6 controls, 8 cards and floating layers.
Shadows: floating layers only, two layers: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.4).
Icons: Lucide 0.400, one 1.25px drawn stroke at every size, 14 in controls, 12 inside badges.
Chrome: title bar 40, workspace tabs 36, status bar 24, chat panel 372.

## Components
pro-system.html shows each component with its states.

---

# Directions, round 1

All pages use real simulator frames from real-frames/. All numbers and rival names are sample data.

## A. Missed
Colours: signal red #FF2A00, black #000000, marker yellow #FFE500, white #FFFFFF.
Type: Anton, Barlow.
Idea: one huge real frame, the bowl and the empty plate ringed, and a giant word that grows out of the red score band.

## B. The wall
Colours: target yellow #FFD400, black #000000.
Type: Archivo, normal and expanded widths.
Idea: 100 chart squares on a yellow field, one per run. Each failed run punches a window through to real footage, so the score becomes a thing you can see.

## C. Leaderboard
Colours: cobalt #1230F0, white #FFFFFF, marker yellow #FFE500, black #000000.
Type: Bricolage Grotesque.
Idea: a public table of crash tests. Each column is one test with its real failure on top and the top three models with score and range below.

# Round 2: normal website in Palatino

Colours: page #FFFFFF, ink #141414, secondary #555555, hairline #DCDCDC, accent bottle green #123C2F, failure #9E1B1B.
Type: Palatino only.
page-1.html: home page with the headline, one captioned frame and four open bounties.
page-2.html: one bounty on the Leaderboard tab, with a pass-mark line above rank 1 and the selected entry's failure frame.
Idea: an auction catalogue applied to a familiar competition-site structure.

# Round 3: brief to worlds

Colours: page #FFFFFF, ink #16161A, secondary #3A3A40, hairline #D6D6DA, accent ink blue #1B2A4A, failure #B3261E.
Type: Palatino for headlines and the brief, Source Sans 3 for interface text.
site-1.html: each clause of the plain-English brief runs on a leader line to the row of real worlds it built.
site-2.html: a campaign result with the brief, the world grid, one opened failure and a before-and-after.
Idea: the brief is the hero. The sentence is the interface, set like a fine-press line, not a footage poster.

# Round 4: the app

Colours: white #FFFFFF, ink #15171A, bottle green #123C2F, failure red #A61E1A, glass #EDF2F4, dust film #D3CEC3.
Type: Palatino for headings and the user's words, system sans for interface text, SF Mono for code.
Idea: chat and simulation are one sheet. Rules cross the divider.
app-1.html: three settings in the chat run on as rules into the live readings and reach the tower.
app-2.html: the "Test this on 40 worlds" card opens through the divider into the list of all 40 reasons.
app-3.html: a red trace runs from line 88 in the chat to the 4:07 event. Worlds get harder to the right, so failures stack up visibly.
Drawing: flat elevation at one scale. The pane is 240 px wide, the robot is 48 px. Build with build_app.py, check with render_app.sh.

# Round 4, dark

app-1-dark.html, app-2-dark.html, app-3-dark.html: pure black, white and grey, red for failures only.
Reads as a code editor with a simulator pane: title bar, editor tabs, side chat, playback controls, status line.
Sand and heat worlds show "Not tested yet". Suction readings are low-kPa sample data. Build with build_app_dark.py, check with render_app_dark.sh.
