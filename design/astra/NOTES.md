# CrashLab — Round 1: footage first

Rewritten to follow `_brief/BRIEF-round1.md`. Three static 1440 × 900 pages with inline CSS, relative `real-frames/` image paths, no JavaScript, and no external dependencies. Keep the image folder alongside the HTML. All pages say “Sample data.”

## A — The verdict poster

- File: `direction-a.html`
- Palette: #FFCF00, #000000, #FFFFFF, #777777.
- Type: Arial / Helvetica / sans-serif. 260px bold score; 64px regular failure statement; tabular numbers.
- Idea: A yellow verdict column faces one enormous real frame of the robot lifting the plate instead of the bowl.

The 1020 × 566 replay is the dominant evidence. A yellow outline isolates the plate, and “It lifted the plate” states the mismatch immediately. The six-case library sits in a black band below the footage. The score, failed fix, and held 5,000 USDC remain visible together.

Critique 1: The initial library stack left too little room for its three-event timeline. Reduced thumbnail height to 80px and tightened the timeline margin; shortened vertical margins in the verdict column without reducing the 260px score.

Critique 2: Checked caption lengths, six library columns, timeline space, image paths, and the target outline against the source image. Text is at least 16px. Image cropping is intentional; no text is hidden to force a fit. Exact browser fit awaits the next PNG.

## B — The incident sequence

- File: `direction-b.html`
- Palette: #FFFFFF, #000000, #FF4A18, #FF845E.
- Type: Arial / Helvetica / sans-serif. 68px statement, 176px bold score, tabular numbers.
- Idea: Three large sequential simulator frames make the wrong-object failure legible as an action, not a report entry.

“Bowl requested. Plate lifted.” sets up the visual comparison. Approach, wrong grip, and the lifted plate fill a 350px-high film strip. Orange frames the final moment and carries the event timeline. Six compact replay entries sit below; a black outcome footer carries the bounty, threshold, scene, seed, and sample label. This footer is report content, not a navigation/tab bar.

Critique 1: A single enlarged frame would repeat A's idea. Used three sequential frames from task0 instead, so the requested object and the actual lifted object can be compared. Kept the orange emphasis on the failure sequence rather than repeating verdict badges across the library.

Critique 2: Checked the explicit 190 / 350 / 72 / 218 / 70px vertical bands, caption widths, and six library entries. Body type stays at least 16px, with no overflow hiding. No navigation, gradients, glass, shadows, or status dots. Browser wrapping still needs the next PNG review.

## C — The evidence leaderboard

- File: `direction-c.html`
- Palette: #243DFF, #FFFFFF, #000000, #FFE500, #7E8EFF.
- Type: Arial / Helvetica / sans-serif. 102px regular display title; 30px test titles; 24px model scores; tabular numbers.
- Idea: A saturated blue public leaderboard makes each test a visual claim backed by a large failure frame.

Three square-edged test columns each contain a 280px-high image, a failure caption, and three ranked models with score ± range. The leader receives one white row. SmolVLA changes rank across tests; all rival names are Model A or Model B. Ranks 1–3 represent actual ordering, not ornamental numbering. Human test design and AI scaling appear as short explanatory copy, without borrowing another company's visual design or wording.

Critique 1: A generic score table would repeat round 0's blandness. Made the blue field, oversized question, and three prominent failure images carry the identity. Removed decorative charts and repeated success chips.

Critique 2: Checked three full model rankings, explicit ranges, sample disclosure, and test-specific imagery. The 606px test columns include their borders, headings, images, ranking rows, and detail lines. Minimum declared type is 16px. The title and footer stay within the fixed page budget; final visual verification remains pending.

## Evidence and assumptions

All 16 supplied frames were inspected. The task0 sequence visibly shows the plate tilting/lifting at the gripper, making it the clearest image for the requested “put the bowl on the plate” failure story. The original 360 × 360 images are enlarged with `object-fit: cover` and `image-rendering: auto`; no sharpening, synthesized detail, filters, or replacement artwork are applied. Coloured outlines are UI annotations, not simulator detections.

The input images do not include telemetry or ground-truth outcomes. Failure categories, perturbations, times, finders, counts, thresholds, rankings, and ± ranges are illustrative sample labels. In particular, library labels such as dim light and collision are not claims verified from those frames. C's uncertainty ranges have no statistical methodology; its footer explicitly calls them illustrative. These images are replay stills, not playable videos.

## Checks and handoff

Source checks passed for all three files: every image resolves under `real-frames/`, all images have alt text, all pages carry “Sample data,” text is at least 16px, and there are no scripts, drawn-arm SVGs, gradients, shadows, glass, rounded cards, or clipping-suppression rules. No publishing or browser rendering was performed.

Next PNG review: confirm A's bottom timeline clearance, B's narrow library captions, and C's ranking alignment. Source dimension checks are not a substitute for rendered verification.

A scales into a verdict plus filtered evidence library. B scales into a synchronized incident-review workflow. C scales by adding tests and ranked models with drill-down reports. The current deliverables deliberately remain fixed-size static studies.

`build_round1.py` is the current construction source. `build_directions.py` is the earlier round 0 source and would restore that old design if executed.

## Round 1 PNG review — corrections applied

These observations are based on the user's actual 1440 × 900 Chrome renders, not inferred screenshots.

### A

**Harsh verdict:** Yes, this stops someone at three metres. The yellow field, giant score, and lifted plate finally have a clear identity. But the annotation's lower edge ran straight across “It lifted the plate,” visibly damaging the strongest sentence. The library is a secondary reading layer, not something all viewers can read instantly from the back of a room.

**Fix:** Shortened the plate outline from 27% to 16% of the frame height and widened/repositioned it around the plate. Its bottom now ends at approximately 419px, above the headline beginning around 448px. Put the headline and replay label above annotations in the stacking order. Explicitly constrained the image to its 566px container. Changed the vague “Not ready” verdict to “Test failed.”

**Second check:** Source bounds keep the outline out of the headline; the image is positioned independently of intrinsic sizing. The already-visible library and timeline retain their vertical budget. A has the strongest two-second failure story of the three, helped by its plain-language caption.

### B

**Harsh verdict:** The headline stops someone, and the sequence is a good idea, but the supplied render fails the layout requirement. The images grew to roughly their square width and extended below their 350px track, covering the orange timeline and the library heading. The page looked deceptively tidy only because whole sections were hidden behind footage. This was an intrinsic image/grid sizing error, not a reason to remove the missing content.

**Fix:** Gave the film grid and all three figures an explicit 350px height and zero minimum height. Positioned images absolutely within those figures at 350px high. No overflow-hiding workaround is used. Tightened the final annotation around the lifted plate in the corrected crop. The final frame now says “Plate lifted,” and the restored orange timeline concludes “Plate lifted. Test failed.”

**Second check:** The explicit vertical bands still total exactly 900px. Images no longer contribute a square intrinsic minimum height to the film grid. The failure library heading, count, and timeline remain in the HTML and have reserved bands. The revised render must confirm that the source-level fix restores their visibility.

### C

**Harsh verdict:** The blue field stops someone, but the failure explanations were sloppy. All three outlines crossed the captions, and the middle outline surrounded the plate while the caption accused the robot of choosing a wrong bowl. “Rank” and “Model” read like one word. Winner strips extended out of their columns, making separate tests resemble a single continuous table. A wrong-object claim cannot be established from a still without task context or a sample label.

**Fix:** Allocated 232px to each photo and a separate 48px yellow caption strip inside its existing 280px slot. Each test now has its own annotation coordinates. The middle image is positioned to expose the bowl held at the gripper, rather than centring the plate. Shortened captions to “Wrong object,” “Wrong bowl,” and “Plate contact,” at 26px. Increased the rank column from 40px to 60px and removed the winner rows' negative margins. Changed the broad question to “Tested to failure.”

**Second check:** Annotation bottoms stay above the 232px caption boundary. The captions cannot be crossed by outlines because they have their own area and higher stacking order. Model ranks, scores, uncertainty ranges, sample disclosure, and the overall 900px budget remain intact. The middle failure is still an illustrative classification, not verified ground truth; the provided stills lack target-object telemetry.

### Verification status

Rebuilt all three HTML files from `build_round1.py`. Checked every relative image path, alt text, sample disclosure, minimum 16px type, and absence of scripts, visual effects prohibited by the brief, and overflow suppression. Added source checks for B's fixed image containment and C's image/caption split and wider rank columns. No new browser rendering was performed. These changes address defects visible in the supplied PNGs; a fresh render is still needed to verify the revised pixels.

## Round 2 — The proving house

New files: `page-1.html` and `page-2.html`. These replace the poster approach with a familiar white website: Palatino typography, a normal header, restrained rules, generous spacing, and modest simulator images. No Kaggle screenshot was present in `_brief/inspiration/`; the competition structure comes from the supplied brief, without copying a reference layout.

Palette: #FFFFFF (page), #222520 (ink), #234F43 (deep green accent), #A1352C (failure only), #62695F (secondary text), #D8DCD7 (rules). Headings and body use the requested Palatino stack. The leaderboard uses Arial for column clarity, with tabular lining numerals. All declared text is at least 16px.

**Page 1:** An editorial introduction begins “Crash tests made cars safe.” Three open bounties appear in ruled rows with a real thumbnail, invented company, prize, solver count, and days remaining. No rounded cards, shadows, decorative colour fields, or giant scores. Images are 100 × 88px.

**Page 2:** The bowl-placement bounty has its own title, company, 5,000 USDC prize panel, and standard section tabs. The Leaderboard view shows three models, scores with illustrative ranges, entry counts, and last-run times. A separate evidence column connects the selected SmolVLA result to a 309 × 220px real frame and a written failure explanation. Red is confined to that failure's title and annotation.

Review: tightened the second page's header, table rows, and explanatory copy to budget the table and evidence panel within the first 900px. Gave the replay image an explicit positioned container so it cannot repeat the earlier intrinsic image/grid overflow. Checked local image paths, sample disclosure, 16px minimum type, and absence of scripts, gradients, shadows, glass, or overflow hiding. Both files exist and pass these static checks. No browser rendering was performed; exact Palatino metrics and final wrapping need the next PNG review.

Both pages are static design studies. Search, sign-in, join, filters, tabs, and replay controls are visual affordances without application behaviour. Bounty links lead to the single sample detail page. All companies, prizes, numbers, outcomes, and timing are illustrative; each page visibly says “Sample data.” `build_round2.py` is the construction source for these two pages and does not alter the earlier directions.

The direction scales through additional bounty rows, paginated rankings, and evidence drill-downs while preserving the same typography and restrained layout.

## Round 2 PNG review — refinement

**Observed:** Both supplied renders fit without visible clipped or overlapping text. The Palatino hierarchy and white page feel considered, but the home page leaned toward a prospectus: its supporting slogan was generic, filters mixed task category with sort order, and bounty rows did not explicitly say what to do next. Page 2 was readable but gave the prize more clarity than the selected model's failed outcome. Its selected rank was visibly indented relative to the other ranks.

**Page 1 changes:** Replaced the generic right-side statement with a short explanation of joining a bounty and earning a reward. Added a sample-bounty CTA and a dedicated “View bounty” column. Kept task filtering separate from a labeled native “Sort by” select. Kept the Palatino titles, white background, quiet green accents, modest real images, and ruled rows. Only the first bounty links to the implemented detail page; the other row affordances remain static rather than navigating to the wrong task.

**Page 2 changes:** Added the explicit outcome “SmolVLA did not pass” below the ranking. Gave the selected score a modest size increase. Replaced the vague methodology heading with “What unlocks the reward?” and explained that no displayed entry reaches the 90 / 100 threshold. Linked SmolVLA to the selected failure panel and renamed the panel accordingly. Replaced the selected cell's layout-changing border/padding with an independently positioned selection rule; every rank and its column heading now share the same inset. Marked Results as the active main-navigation link.

**Second review:** All local links and image paths resolve, the selected-failure anchor exists, and the generated HTML contains the revised sorting, outcome, and payout copy. Type remains at least 16px. No scripts, banned visual effects, or overflow-hiding fixes were introduced. The small selected-score and outcome-type increases add about 12px to the table column's height; the supplied render had room for that increase. No new render was performed, so exact revised fit remains unverified.

These changes improve discoverability in the static design, not application functionality. The search, sign-in, non-active tabs, filters, sorting, join and replay controls still need implementation. The sample bounty link and in-page failure link work without JavaScript. The expensive feel comes from controlled typography and alignment; the next usability gain is working behaviour, not more ornament.

## Round 3 — A sentence becomes a test

Created `site-1.html` and `site-2.html`, with `build_round3.py` as their construction source. The new composition borrows focus, breathing room and real product evidence from the supplied reference, while deliberately changing the visual structure: Palatino headlines sit on white space, an editable brief sits beside four world previews, and the campaign result uses an evidence workspace. No cinematic hero card, overlaid marketing headline, pill-button pair, logo strip, reference branding, or borrowed wording.

Palette: #FFFFFF, #242823, #2C5043, #A8342A, #626B60, #DCE1DA. Palatino is used for display headings; Arial handles the brief, controls and evidence labels. Deep green is the sole quiet accent, red is reserved for failures, and all declared text is at least 16px. Rounded corners are limited to controls, the brief editor and small image edges. No glass or shadows were needed.

The home page leads with the user's plain-English brief, four sharp world setup images, and visible pass/fail labels, plus links into the campaign result and open bounties. The result repeats the exact brief, shows the four-world subset and a 71 ± 4 score across 300 sample scenes, opens the wrong-object run, and compares it with an illustrative 93 ± 2 result after a target-check fix. It links to the existing bounty/leaderboard page. The failure replay is separate from the world setup imagery. Both pages visibly say “Sample data.”

Honesty: outcomes, scene counts, scores, ranges, timing and the fix are illustrative. The before/after stills are supplied images from different source tasks, not proof of a paired controlled experiment; the comparison is explicitly labeled illustrative on the page. There is no generation or playback backend: editing the brief changes its text only, and build/replay/sign-in controls remain static. Navigation links work. The new pages say “replay the recorded run” and make no seed-reproduction claim.

Checks: inspected all four sharp assets and the supplied reference. Source review tightened the home-page vertical budget and kept image containers explicitly sized to avoid intrinsic-image overflow. Both pages pass local asset/link/anchor checks, minimum type-size checks, and checks for prohibited visual effects and wording. No rendering was attempted. The next PNG review should verify the home footer clearance and the result page's incident/comparison wrapping; exact rendered fit remains unverified.

## Round 3 PNG critique — applied refinements

**What the renders actually showed:** No visible clipping or overlapping text in either supplied PNG. The pages are recognizably different from the reference: white editorial layout, dark Palatino headings, exposed UI, multiple small scenes, no cinematic card or overlaid marketing copy. The result feels professional and calm, but the home page's wide, shallow crops and equal-weight labels made it feel more like a generic scene browser than a premium product demonstration. Robot bodies and relevant object positions were cropped away. The brief editor had conspicuous empty space, and the headline required interpretation before the product promise became clear. The before/after comparison was readable but visually subordinate to almost everything else.

**Home fixes:** Replaced the abstract headline with “Write the test in words. See the worlds it builds.” Shortened the editor from a 208px text area to 176px while retaining room for the displayed brief. A single fine connecting rule joins the brief editor to the output area. Reorganized the four outputs as square 220px scene images with adjacent Palatino titles and plain pass/fail labels, preserving the full source composition. Output copy now says “From this brief: four test worlds.” Tightened the introduction and bounty strip to fund the new image proportions within the screenshot budget. No additional cards, decorative colour fields, or shadows were added.

**Result fixes:** Enlarged the before/after stills from 96px to 112px and comparison scores from 28px to 36px. The heading now makes the numerical difference explicit: “After the fix: 22 points higher.” Before and after labels are explicit. Changed “Same test set” to “Illustrative rerun,” retaining 300 sample scenes and the visible illustrative-comparison disclosure. Clarified that the four thumbnails are world setup images, with outcomes from sample runs. Reduced surrounding spacing to make room without pushing the footer down.

**Second source review:** Checked all image paths, navigation targets and anchors; retained the minimum 16px type size, explicit image heights, sample labels, and before/after range values. Confirmed no prohibited effects, reference wording, seed claims or overflow suppression in the new pages. No browser render was performed. Revised wrapping and footer clearance still require a fresh 1440 × 900 PNG. The reference-distinction judgment is based on the supplied screenshots; the revised design keeps that same structural separation. Build, sign-in and replay remain static mockup controls.

## Round 4 — The simulation workbench

Created `app-1.html`, `app-2.html`, and `app-3.html` from `_brief/PRODUCT.md` and `_brief/BRIEF-round4.md`. `build_round4.py` is the construction source. Each is a static 1440 × 900 Mac-style app window with a 424px conversation pane, a simulation/scenario/result pane, and links between the three screens. White surfaces, near-black ink, deep green (#315749), and failure-only red (#A5352C). Palatino carries headings and the user's words; Arial carries UI text; Menlo/Monaco/Consolas is used only for code. Body text is at least 16px; code and small labels are at least 13px.

**App 1:** The exact requested user message leads to a short setup explanation and first-test action. The right pane has wind, suction and grip readings plus a flat SVG façade, distant city, dirt film and cleaned path. The robot is a flat square on tracks, about one fifth of a pane's width, with one upward tether and no arms. The schematic is explicitly a geometry preview, not a fabricated photo.

**App 2:** The first test passes, then the scenario agent explains its proposed 40 cases: 8 dust, 8 high-floor wind, and 6 each for humidity, friction, mullion geometry and heat. All 40 worlds have individual plain-language reasons in six groups. Each group names the physics mechanism it proposes to change; the UI states that equations or assumptions belong in PARAMETERS.md. Seal wear, water ingress and tether fatigue stay on the not-tested list, with a “Send to a bounty” affordance. Forty is the sample agent's recommendation, not a fixed setting.

**App 3:** All 40 worlds appear in a compact grid, with 31 passes and 9 failures. Six failures involve wind/dust; the other three concern humidity, low friction and a raised edge. S4 is opened with a recorded-run preview and three-event timeline. The chat traces the failure to a 28 kPa cutoff on line 88, while simulated grip is lost at 32 kPa, then offers “Try a fix.” Bounty status is a draft covering three untested gaps, with a reward per new valid failure; nothing is represented as published.

**Review and checks:** Tightened the chat copy and scenario-list spacing so the first-test action, not-tested list, fix control and bounty draft have space above their composers. Explicitly sized the SVG containers. Static checks pass for the exact opening message, required actions, 40 scenario reasons, 40 result tiles, nine failed results, local links and anchors, sample disclosures, and absence of prohibited effects or clipping suppression. No browser rendering was performed; the next PNG review should check the dense 40-world plan and the bottom of each chat pane.

**Honesty:** Every number, result and code excerpt is illustrative. All screens say “Simulated” and “Sample data,” and disclose hand-built physics, simplified weather and lack of hardware validation. The depicted coverage is a proposed model contract, not a claim that this HTML implements physics or changes controller code. No PARAMETERS.md or physics implementation was created. The controls do not run simulations, apply fixes, send messages or publish bounties. Screen navigation works; all other controls are static. Replay wording is “replay the recorded run.”

## Round 4 PNG review — completeness and engineering credibility

The three supplied renders are complete at 1440 × 900: no visible clipped content, all chat actions remain above the composer, and all 40 plan entries and 40 result tiles are present. The white split-pane workspace, Palatino hierarchy, scene-specific controls and code trace distinguish it from a generic chatbot or dark editor clone. It feels restrained, but the repeated thumbnails and decorative under-preview copy weakened its engineering character. The UI alone cannot establish trustworthy physics.

**App 1 fixes:** Replaced the two generic explanatory panels with concrete included-model and excluded-model statements. Defined the first-test pass criterion as finishing one pane without slip or a tether catch. Corrected the grip display: μ is the coefficient's symbol, not a unit following 0.72. Clarified that pressure is suction magnitude. Preserved the square tracked robot, single tether, dirt/clean path, distant city and pane-relative scale.

**App 2 full-brief audit and fixes:** Retained the first-test result, the exact “Test this on 40 worlds” and “See the 40 worlds” text, the all-worlds action, all six required groups, and the not-tested list with “Send to a bounty.” Rewrote every one of the 40 entries as a condition plus a plain risk or reference purpose. Explained the higher allocation to wind/dust through their interaction at the seal, rather than merely repeating the counts. The plan explicitly calls itself targeted, not exhaustive. Group subtitles identify model terms or assumptions; the footer now states the implementation/documentation gate rather than implying the HTML demonstrates implemented physics. Untested effects explicitly say “No pass claimed.” Counts remain 8 + 8 + 6 + 6 + 6 + 6 = 40.

**App 3 fixes:** Changed the duplicate miniatures into visibly varied, explicitly labeled scenario schematics: dust, wind load, moisture, low-grip patches, joint geometry and temperature each have a different schematic cue. These are not claims that appearance validates physics. Zoomed the opened failure to the contact region; the robot now has an earlier-position outline and a slip annotation instead of a nearly invisible red corner in a distant façade view. Qualified the causal explanation as occurring “in this model.” The 31/9 totals, S4 selection, controller cutoff, timeline, fix action and draft bounty remain consistent.

**Verification:** Rebuilt all three HTML files. Static checks verify 40 individual scenario reasons, six groups, the required app-2 actions, modelling gate, 40 results with nine failures, valid local links/anchors, sample and simulated labels, minimum declared text sizes, and absence of prohibited effects or overflow suppression. No fresh rendering was attempted. The revised app-2 rationale/footer wrapping and app-3 close-up annotations need the next PNG check. These remain design mockups with sample physics, code and outcomes; no model validation, simulation execution or publishing occurred.

## Round 5 — Design system (defined before implementation)

**Idea:** An evidence workbench: conversation proposes work; structured views expose runs, code changes and local payout decisions.

### Tokens

| Token | Value | Use |
|---|---|---|
| `--app` | `#0B0C0E` | Application backdrop |
| `--panel` | `#111317` | Chat, inspector, secondary workspace |
| `--raised` | `#16191E` | Inputs, menus, approval surfaces |
| `--hover` | `#1E2228` | Hover and selected-row affordances |
| `--border` | `#292E36` | Low-contrast dividers |
| `--text` | `#E8EBF0` | Primary text |
| `--muted` | `#9CA6B4` | Secondary text |
| `--subtle` | `#788392` | Tertiary labels |
| `--accent` | `#91A7FF` | Focus, selection, primary-action fill |
| `--accent-ink` | `#101729` | Text on primary actions |
| `--red` | `#F18B91` | Failed/rejected/danger |
| `--amber` | `#E6BB72` | Held, flaky, review required |
| `--green` | `#88C9A0` | Passed, accepted, completed |

Typography: system sans (`-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`); 11, 12, 13, 14, 16, 20px only; 13px body; tabular numbers. Code: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`. No serif. Spacing: 4, 8, 12, 16, 20, 24, 32px. Radius: 4px small controls, 6px inputs/cards, 8px floating surfaces. Icon set: inline Lucide SVG geometry, 24-unit viewBox, 1.75 stroke width, round caps and joins. No gradients, shadows, glows or glass.

Layout: 40px native title bar; 40px activity rail; 336px AI conversation; right workspace with a 40px tab strip; 24px status bar. All screens are 1440 × 900. Shared dividers provide hierarchy without outlining every section. Viewport, inspector, table, chart and code regions have distinct responsibilities.

Components: primary, secondary and ghost buttons; native inputs/selects; segmented control; semantic badge with text; tooltip; sorted table header; selectable tree/list row; pipeline progress; scrubber and transport; contextual empty state; non-modal toast; command shortcut hint; syntax-highlighted, line-numbered code; inline diff; ledger stepper. Enabled controls receive hover/pressed and `:focus-visible` treatments. Disabled controls use native `disabled` state. Active tabs/rows/segments use explicit styling and accessible state. Static interaction states will be represented without JavaScript; local screen links work, operational buttons are mockups.

Content contract: preserve the supplied 52-world totals (31 failed, 13 held, 5 flaky, 3 passed), 10/10 controls, fix improvement from 11 to 17 passes on 104 fresh worlds with 0 worse, removal of a guard, not-applied status, and gate threshold 7/8. Other values are sample. Keep “Simulated,” “Replay of recorded run,” and “Local ledger. Not on chain.” visible where relevant. No operation in this task applies code, funds a bounty, sends a message or publishes anything.
