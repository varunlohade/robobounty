# CrashLab — round 5

**One-line idea:** A quiet engineering workbench where every failure has an inspectable world behind it.

Six standalone screens: `login.html`, `home.html`, `crashlab.html`, `bounties.html`, `data.html`, `providers.html`. All use `styles.css`, local fonts and supplied simulation frames. `app.js` supplies local interactions only. No external requests, authentication, submissions, payments or persistence are implemented.

## Tokens

- Canvas: 1440 × 900, fixed. App sidebar 200px; content column 1240px; content gutters 32px. Top breadcrumb 48px; persistent simulation status 24px. The site chrome differs from the simulator’s 40px title bar; the simulator is not modified.
- Surfaces: app `#0B0C0E`, panel `#111317`, raised `#16191E`, hover `#1E2228`, active `#262B32`.
- Dividers: white at 7%; strong separators at 12%. Borders separate functional regions rather than enclosing every item.
- Text: primary `#ECEEF1`, secondary `#A3A9B3`, muted `#737A85`, disabled `#4B515B`.
- Action: `#3E7BFA`; hover `#5089FB`; press `#2F6AE6`; selected text `#7DA7FF`; focus ring blue at 45%.
- Status: red text `#F27B73`, amber text `#E3B04F`, green text `#5CC186`. Icon and text accompany status where used. Charts include numeric labels and legends.
- Failure categories: suction `#E2574C`, slip `#D3A017`, edge detach `#14A39A`, tether slack `#9A78F0`.
- Outcomes: passed `#C9CED6`, failed `#E2574C`, safe hold `#2A2F37`. Campaign distributions use the exact supplied totals.
- Typography: local Inter, weights 400/500, tabular numbers. JetBrains Mono only for world filenames and identifiers. Primary interface scale 11/16, 12/20, 13/20, 14/20, 16/24, 20/28. Supporting chrome uses 10/16; login headline uses 36/44 and summary totals use 32/40.
- Space: 4, 8, 12, 16, 24; page gutter 32. Controls 28–36px; sign-in action 44px. Dense result rows 42px; campaign rows 64px; inventory rows 80px to accommodate secondary descriptions.
- Radius: 4px badges and inner controls, 6px controls, 8px major image panels and dialogs.
- Icons: inline SVG using Lucide-style geometry and a consistent 1.25px stroke; 14px controls and 12px badges. No external icon dependencies.
- Shadows only on dialogs and feedback: `0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.4)`.
- Motion follows the referenced art direction’s motion section: 160ms press scale to .97; feedback opacity/transform at 180ms using `cubic-bezier(.23,1,.32,1)`. Keyboard selection and filtering are immediate. Reduced motion removes transitions. No decorative looping motion.

## Content and interaction

- Window campaign: 33 run, 2 passed, 27 failed, 4 safe holds. Inspection: 34 run, 16 passed, 18 failed, 0 holds. Combined totals are derived: 67 run, 18 passed, 45 failed, 4 safe holds.
- Wind readings (20.9 m/s, pause above 10, resume below 7, 0.7% cleaned) are transcribed from `assets/lab-3.png`.
- Bounties, IDs, rewards, open work and failure-library boundary rows are explicitly marked Sample. They do not imply measured results or funded contracts. The supplied stills illustrate the sample bounty workflow; they are not a verified mapping from bounty IDs to recorded failures.
- Providers distinguish real named engines from connected integrations. MuJoCo and Newton are not connected in the preview. ANYmal C, upstream policy and Claude are visible in supplied frame metadata; no unspecified model version or author is invented.
- World ID sign-in starts with a visible waiting-state example; clicking the primary action shows the pending preview without sending anything. Wording is based on the official [World ID page](https://world.org/world-id): unique-human proof without revealing identity. The home screen separately represents the post-login state.
- Robot selection updates the frame, world name, description, campaign total and simulator link. Bounty tabs filter, the reward control sorts, and row selection updates the detail. Search filters failure-library rows; `/` focuses it. Replay actions open the original full frame in a dismissible modal, explicitly labeled a still preview. Requirements open a read-only dialog. Native Escape and focus behavior are provided by `<dialog>`.
- `Open CrashLab` links to `lab.html` as requested. That file is not supplied in this folder. The orchestrator must mount the existing simulator at that path. The inspection link carries `?robot=inspection`; robot-specific routing depends on the host simulator.
- Real frames are cropped with CSS for the overview and launcher; the full, unmodified source is available from the frame preview. Inspection imagery has a replaceable, stable frame slot.

## Checks and rendering handoff

- JavaScript syntax checked with `node --check app.js`.
- All six HTML documents parsed, IDs checked for duplicates, local image/font/script references checked. Only the explicitly requested `lab.html` handoff is absent.
- Fixed-width grids sum to 1176px, the exact content width. Vertical budgets were reviewed in source and tightened so content fits above the bottom status bar. The stylesheet intentionally fixes the desktop canvas; this is not a responsive production build.
- No browser rendering was attempted, as instructed. PNGs and two visual critique passes remain pending the orchestrator’s rendered images. Source-level reviews are not represented as visual verification.
