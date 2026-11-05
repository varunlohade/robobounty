# CrashLab design brief, round 0: three picture directions

## Product
CrashLab is crash testing for robot AI. "Crash tests made cars safe. We're doing it for robots."
A company posts a robot and a problem with a USDC bounty held in a contract. Solvers connect their robot AI by a
link. Each fix goes through a crash test: hundreds of scene variations, an AI tester that invents tricky scenes,
and verified humans who earn money for each new failure that the machines missed. Each result replays from a scene
file and a seed. The contract pays out on a passing result.

## Who looks at it
ETHGlobal judges in a 4-minute demo, on a projector, from 3 metres. Then robotics engineers. In 5 seconds they must
understand: this robot AI got a score, here is how it failed, and I can watch each failure.

## What to make
THREE different visual directions for ONE screen: the crash test report. Each is one static 1440x900 page.
These are cheap pictures for choosing a direction. They are not a product build.

The screen shows:
- The headline result: the AI name (SmolVLA), the task ("put the bowl on the plate"), a score such as 71/100.
- The failure library: 5-8 failures, each with a video frame, the failure type (dropped object, wrong object,
  collision, timed out), the scene change that caused it (dim light, moved 4 cm, clutter added), and who found it
  (variation bot, AI tester, human).
- One failure opened as a large replay, with a timeline of what happened.
- The bounty: 5,000 USDC, and whether this fix passes.

Use grey placeholder blocks or simple drawn robot-arm frames for video. All numbers are sample data for now.

## Subject materials to draw from
Real crash test culture: star ratings, Good/Marginal/Poor grids, yellow-and-black calibration targets on test cars,
high-speed film frames, lab reports. Read INSPIRATION.md. Steal ideas, do not copy any page. Do not use Euro NCAP,
IIHS or any other real organisation's name, logo or rating mark.

## Hard rules
- Pure white or pure black page background. No gradients, glows, vignettes, tinted panels or glass.
- No top task bar and no bottom tab bar. No status dot or pulsing dot in front of a label.
- Banned: cream + serif + terracotta. Near-black + one acid-green accent. Identical rounded cards with a soft shadow.
  Tracked ALL-CAPS eyebrow labels. "A · B · C" meta strings. Arrows on every button. Mono data labels everywhere.
  One accented word in a headline. 01/02/03 on things that are not a sequence.
- Use tabular numbers. Spend boldness in ONE place. Sentence case in copy.
- Readable on a projector: no body text under 16px at 1440 wide.
- The three directions must differ in layout and idea, not just in colour.

## Output
Three self-contained files: direction-a.html, direction-b.html, direction-c.html. Inline CSS. Google Fonts is fine.
No JavaScript needed. Each must fit in 1440x900 with no scrolling and no clipped text.
Also write NOTES.md: for each direction, a name, 4-6 hex colours, type families and one line on the idea.
