# CrashLab design brief, round 3: our own site, informed by a reference

The product owner's words: "use them as a reference for UI, but it should not be a direct copy, it should be an adaptation from them, but it should look significantly different in terms of looks of people don't think we copy, they didn't, we had an idea, similar idea, that's very common idea."

Reference: `inspiration/zynoptes.png` (their home page). Steal the qualities, not the page: one confident idea on the first screen, real product footage, lots of air, few words, a calm premium feel.

## A viewer must not think we copied. So do NOT use
- A full-bleed rounded card holding cinematic footage with a headline on top of it.
- A big white sans headline at bottom left with two pill buttons at bottom right.
- A lowercase wordmark ending in a full stop. "Book a demo". "Backed by" logos.
- Orange-to-teal colour. Their wording, section order or numbered steps.

## Our own idea for the first screen
The owner's favourite feature: you write in plain English and it builds the test worlds.
So the hero IS the product: a large plain-English brief, and the worlds it built, right there on the home page.
For example: a person's sentence ("A messy counter in dim light, with the bowl pushed near the edge") leads to a set of real world frames, some passing and some marked as failed. This is the memorable thing. Find your own way to show it.

Keep our line in mind: "Crash tests made cars safe."

## Look
- White page. Near-black ink. One quiet deep accent of your choice, and a failure colour for failures only.
- Palatino for large headlines: `font-family: Palatino, "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif;`. This separates us from the sans-serif look of the reference, and the owner asked for Palatino earlier.
- A clean sans is allowed for interface text, tables and the brief box.
- Rich, calm and expensive. A normal website that anyone can use at once.
- Soft rounded corners are allowed where they help. One subtle glass element is allowed if it earns its place.

## Make two pages (1440x900 screenshot of each)
- `site-1.html`: the home page, with a normal header, the brief-to-worlds hero and a way into open bounties.
- `site-2.html`: a campaign result. Top: the brief as written. Then: the grid of worlds built from it with pass or fail, a score with a ± range, one failure opened large with what went wrong, and a before-and-after comparison once a fix is tried. Link to the bounty and leaderboard, whose Kaggle-like structure stays as inner pages.

## Images
Use only real frames from `real-frames-hd/` (sharp) and `real-frames/` (soft 360x360). No drawn arms, no invented images.

## Honesty
All numbers, companies and rival models are placeholders, with "Sample data" in small text on each page. SmolVLA may appear by name. Use invented company names. Do not name or mention the reference company. Do not say "reproducible from a seed"; say "replay the recorded run". Do not claim "first".

## Rules that still hold
No gradients, glows or vignettes. No status dots. No identical rounded cards with soft shadows. No tracked ALL-CAPS eyebrow labels. No "A · B · C" meta strings. No arrows on every button. No mono labels everywhere. No one accented word in a headline. No body text under 16px.

## Output
`site-1.html`, `site-2.html` in your folder, inline CSS, no JavaScript, plus a short update to NOTES.md.
