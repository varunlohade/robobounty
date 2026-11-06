# CrashLab website, design brief

Owner's words: "make the website much more interactive, where we can have a login with world ID, and then you enter, then there is a crash lab section where you can, if you click on it, it opens up the thing we have just built where we can simulate things ... have a bounty page where you can see the bounties, have data, have providers, like have a normal fucking page". He delegated all design choices.

## What CrashLab is
A person imports a robot, says its job, an AI builds the world, the person changes it by typing, an AI lists the test scenarios, and a grid of simulations runs. Failures go red, with reasons. The AI tries a fix. What it cannot fix becomes a bounty: engineers submit fixes, code checks them on hidden worlds, and a contract pays only on a pass. For robotics companies. It must feel serious and useful, never gimmicky.

## Screens, 1440x900 each, with real interaction states shown
1. `login`: sign in with World ID. Calm, confident, one primary action, with what World ID proves in one line, and a clear state while verifying.
2. `home`: after login. A normal product home with clear nav: CrashLab, Bounties, Data, Providers. Shows your recent runs and open work. CrashLab is the obvious way in.
3. `crashlab`: the entry into the simulator: choose a robot (window cleaning, plant inspection), recent worlds, an "Open CrashLab" action which opens the real tool at lab.html. Show the tool's real frames.
4. `bounties`: list of bounties, filters, status, pay, a bounty detail with public failing worlds, replays, submission state, and hidden worlds stated as hidden. Label "Local ledger. Not on chain." unless it changes.
5. `data`: campaign results as real tables and charts: worlds run, passed, failed, safe holds, failure types, boundary values. A failure library you can search.
6. `providers`: who provides what: simulation engines (MuJoCo, Newton), robots and controllers, AI models, testers and fix authors. Real entries only. Empty states where none exist.

## Must have
- Interactive feel: hover, focus, press, filtering, sort and transitions are designed, with motion rules from ~/.claude/roles/art_design.md.
- Real frames only: design/shell/lab-3.png, build-part-ac_unit.png, inspection-plant-t17.png, grid-*.png, weather-*.png, in `design/site2/assets/`, copied there. Better inspection renders are coming; leave room for them.
- Real numbers only, marked "Sample" where not. Window: 33 run, 2 passed, 27 failed, 4 safe holds. Inspection: 34 run, 16 passed, 18 failed. All simulated. "Simulated. Hand-built physics." stays visible and calm.
- The simulator tool itself stays as is; this site must feel like the same product: dark tool, Inter, JetBrains Mono for code. Tokens in design/claude/NOTES.md, round 5. You may push the marketing-free pages further, but no serif in the app.
- Say "replay the recorded run". Never say first, scientifically accurate, real failures, AI robot, reproducible from a seed.

## Banned
Gradients as decoration, glows, glass, tracked all-caps eyebrows, identical rounded cards, outlined boxes around everything, an arrow on every button, emoji, fake logos of real companies, fake testimonials, invented customers, sample rows pretending to be real.

## Output
`<screen>.html` plus `<screen>.png` at 1440x900, one shared stylesheet, inline SVG icons (Lucide), and NOTES.md with your tokens and one-line idea. Self-critique twice on the rendered PNGs and fix what you see.
