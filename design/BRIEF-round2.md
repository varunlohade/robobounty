# CrashLab design brief, round 2: a normal, very rich website

The product owner's words: "make it like a normal website with white and palantier font and stuff make it feel supa fking rich and copy those kaggle for the style but not entierly".

This replaces the poster look of round 1. Do not reuse the huge "Missed" type, solid colour fields or yellow and cobalt walls.

## The feel
A normal website that a person knows how to use at once. White page. Palatino type. It should feel expensive: a private bank, an auction house or a fine press, applied to robot testing. Calm, confident and spacious. Riches come from type, spacing and restraint, not from decoration.

## Type
Use Palatino for headings, and for body text too unless a small sans clearly helps a data table:
`font-family: Palatino, "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif;`
Use real typographic care: old-style or lining numerals where they fit, tabular numbers in tables, fine contrast between sizes, generous line height. No body text under 16px.

## Colour
Pure white page. Near-black ink. At most one quiet, deep accent of your choice, used rarely, plus a failure colour used only for failures. No cream, no gold-on-black, no terracotta.

## Structure: borrow from Kaggle, but not entirely
Use the structure of a Kaggle competition site, because people already understand it. Do not copy its logo, name, colours, wording or exact layout. See `inspiration/kaggle*.png` if present.
- A normal site header with a logo word "CrashLab", a few links, search and a sign-in button. The earlier "no top bar" rule is lifted for this round.
- Bounties are like competitions: a list or grid with a thumbnail, title, company, prize, solver count and days left.
- A bounty page has tabs such as Overview, Robot, Leaderboard, Failures, Rules.
- The leaderboard is a clean ranked table with score ± range, entries and last run.

## Make two pages (1440x900 screenshot of the top of each page)
- `page-1.html`: the home page, listing open bounties, with a headline that uses "Crash tests made cars safe."
- `page-2.html`: one bounty, "Put the bowl on the plate", 5,000 USDC, showing the Leaderboard tab with a real failure frame.

Use real frames from `real-frames/` as images. Show them at a modest size, since they are 360x360 and go soft when large. Use neat crops.

## Content honesty
All scores, companies, rival models and prizes are placeholders. Show "Sample data" in small text on each page. Use "Model A", "Model B" for rivals and invented company names like "Acme Robotics". SmolVLA may appear by name. Do not use a real organisation's name or logo.

## Rules that still hold
No gradients, glows, vignettes or glass. No status dots. No identical rounded cards with soft shadows. No tracked ALL-CAPS eyebrow labels. No "A · B · C" meta strings. No arrows on every button. No mono labels everywhere. No one accented word in a headline.

## Output
`page-1.html`, `page-2.html` in your folder, inline CSS, no JavaScript, plus a short update to NOTES.md.
