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
