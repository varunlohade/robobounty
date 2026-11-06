# CrashLab design brief, round 1: bolder

The product owner saw all six round 0 pictures and said, in his words: "too bland".
He also said: "do similar to scale ai". We could not capture Scale's visuals, so use its ideas below and do not guess its look.

## What was wrong in round 0
- Everything looked like a tidy report or a wireframe. Nothing grabs you from 3 metres.
- Drawn grey robot arms all look alike and look fake.
- Critics on the weaker pages: flat type weight, thin rules, small failure moment.
- Critics on the stronger pages: repeated green chips compete with failures, and a donut chart looked like decoration.

## What to change
1. REAL FOOTAGE IS THE HERO. Use the real simulator frames in `real-frames/`. Make them large, cropped hard and full-bleed. Stacks of frames, film strips and tight crops of the gripper are all welcome. Drop the drawn arms. These frames are only 360x360, so use `image-rendering: auto` and accept some softness; do not fake extra detail.
2. A STRONG POINT OF VIEW. Each page needs one image or idea you remember the next day. Scale up hard: display type can reach 200-400px. Use solid colour fields and strong contrast. A timid page loses.
3. THE FAILURE MUST HIT. A viewer sees the robot miss in under 2 seconds with no reading.
4. Copy can be short and declarative, like a statement. For example: "Crash tests made cars safe."

## Ideas from Scale AI to use (structure only)
- A public leaderboard: a card per test, with the top 3 models and scores with a ± range.
- Large imagery, a text-led hero with big display headings, short declarative copy.
- Humans design the tests and AI scales them.
Do not use Scale's name, logo, wording or page layout.

## Make three pages (1440x900 each, no scrolling)
- direction-a.html: the crash test report with a huge real failure moment.
- direction-b.html: a different and equally bold take on the report.
- direction-c.html: a robot AI leaderboard as the first screen. Each test shows top models with score ± range, and real frames of how they fail.

Sample data: every number and rival model name is a placeholder. Mark each page "Sample data" in small text. Use "Model A", "Model B" for rivals, not real model names. SmolVLA may appear by name.

## Rules that still hold
- No gradients, glows, vignettes or glass. No top task bar, no bottom tab bar. No status dots.
- Banned: cream + serif + terracotta; near-black + one acid-green accent; identical rounded cards with soft shadow; tracked ALL-CAPS eyebrow labels; "A · B · C" meta strings; an arrow on every button; mono labels everywhere; one accented word in a headline.
- No real organisation's name, logo or rating mark except where this brief allows it.
- No body text under 16px. Nothing clipped by accident.

## Rule that changes
"Pure white or black page" no longer limits you. Solid full colour fields are allowed this round.

## Output
Overwrite direction-a.html, direction-b.html, direction-c.html in your folder. Inline CSS, Google Fonts is fine, no JavaScript. Update NOTES.md.
