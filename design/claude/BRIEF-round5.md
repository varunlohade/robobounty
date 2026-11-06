# CrashLab design brief, round 5: a professional app interface

Owner's words: "Still don't like the UI though, it looks very unprofessional ... it should look like a professionalized thing. All you did for UI was make it black in color. That doesn't make sense." Earlier: "it should look familer". "left window can look like cursor side window exacctly".

He is right. Build a real design system first. Do not recolour the old screens.

## What is wrong now (see design/final/app/app-3-term.png and the real app screens)
- Pure black with thin white outlines around everything. No surface levels, so nothing has depth.
- A serif (Palatino) inside a software tool. Large serif headings read as a magazine.
- Buttons are all outlined rectangles, with no primary or secondary hierarchy.
- No icons. No real tree, tabs, table, badge or toolbar components.
- Raw JSON dumped as the main content.
- Inconsistent spacing and type sizes. Long sentences where a tool would use a label and a value.

## The target
Should look like a product from a serious, well-funded developer tools company. Think of the craft in Cursor, Linear, Vercel, Foxglove, Rerun, Figma, or a well-made pro Mac app. Reference pictures: inspiration/rerun.png, inspiration/foxglove.png. Build from your knowledge of those tools' conventions. Do not copy any logo, name, wording, or exact layout.

## The design system (write it first, as tokens in NOTES.md)
- Neutral dark UI with real surface levels, such as #0B0C0E app, #111317 panel, #16191E raised, #1E2228 hover, hairline borders at low contrast. Not pure black. One restrained accent colour for primary actions and focus. Semantic red, amber and green for status, used sparingly.
- One excellent sans for all interface text: Inter or the system font, with tabular numbers, and a real mono for code. No serif anywhere in the app.
- A strict type scale (11, 12, 13, 14, 16, 20) and a 4px spacing grid. Compact density like a pro tool. 13px body text is right for this app. The earlier 16px rule is lifted here.
- Consistent radii (4, 6, 8). Real icons: inline SVG from an open icon set such as Lucide, one stroke weight.
- Components, each with hover, active, focus, disabled states where shown: title bar, activity bar or tabs, primary and secondary and ghost buttons, inputs, select, segmented control, badge, tooltip, table with sorted header, tree or list row, progress, timeline, empty state, toast, command palette hint, code block with line numbers and syntax colours, diff view.

## Screens (static HTML, 1440x900 each, inline CSS and SVG, no JavaScript)
Layout: AI chat panel on the left, like a modern AI code editor's side panel. Workspace on the right with tabs: World, Test run, Fix, Bounty, controller.py.
- `pro-1.html`: World tab. Chat with a compact step list ("Built world", "Ran 1 test"), an approval card. Right: a real render as a viewport (use real-frames-hd or render/still.png if available in your folder), with a viewport toolbar, an inspector panel of properties (wind, suction, wetness, each label and value), and a timeline with scrub and transport controls.
- `pro-2.html`: Test run tab: pipeline status, a clean results table of worlds with status badge, group, failure type, key metric, and a compact heat map. A filter bar and summary stats.
- `pro-3.html`: Failure detail: replay viewport, event timeline with markers, signal charts for suction and grip, the code line, an inline diff with Accept and Reject in chat.
- `pro-4.html`: Bounty tab: bounty summary, submissions table with statuses, a verdict panel, ledger state with a stepper, and a clear "Local ledger. Not on chain." badge.

## Content
Use real values, where given: 52 worlds, 31 failed, 13 held, 5 flaky, 3 passed, controls 10/10; fix 11 to 17 passes on 104 fresh worlds, 0 worse, not applied, removes a guard; gate 7 of 8. Mark others as sample. Keep "Simulated" visible, calmly, as a badge. Say "Replay of recorded run". Plain, short labels.

## Banned
Gradients as decoration, glows, glass, status dots used as decoration, tracked ALL-CAPS eyebrows, "A · B · C" meta strings, an arrow on every button, identical rounded cards with soft shadows, any serif, outlined boxes around everything, raw JSON as main content. No real company logos or names.

## Output
pro-1.html to pro-4.html, plus NOTES.md with tokens and a one-line idea.
