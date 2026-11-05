# CrashLab product spec

Written from the owner's description on 2026-11-06. His words on the main flow:

"the left side should be like a chat window, like a chatbot window, similar to how cursor has the extension for VS Code ... but better for simulation. So let's say if I type I want this, this, this, it will simulate in real time ... on the right side."

"it will say run 40 different worlds and test cases. Basically the 40 number would come by another AI agent ... It will figure out the edge cases ... we can have the cleaning robot in Dubai to clean the buildings, but Dubai has sandstorms ... Some buildings are on a very high floor, so it will have very, very strong winds. Some have high moisture, high humidity, low friction, high friction. Some have weird edges"

"on the left hand side we see let's say tabs or pop-up saying test this on 40 worlds, see the 40 worlds ... the same robot can be tested on all those worlds in all those scenarios: temperatures, this, that, humidity, speed, wind, weather ... And whatever is not tested, the user can then send it to a bounty."

## The app
Left: chat, like an AI code editor's side panel. It changes the code and the world. Right: the live simulation, which updates as the chat changes the world.

## Flow
1. Chat: the user says what the robot is and where it will work. "Window robot for towers in Dubai."
2. The right side builds and shows the world, live.
3. The user tests the robot once and watches it.
4. A scenario agent reads the conversation and works out what could go wrong for this robot in this place. The number of worlds comes from this agent, not from a fixed setting. Each world has a plain reason, such as "Dubai sandstorm: dust on the seal, 18 m/s wind".
5. A card appears in the chat: "Test this on 40 worlds", with "See the 40 worlds".
6. The same robot runs in all of them. The results come back in the chat and on the right.
7. Failures can be opened, replayed and traced to code. AI tries a fix.
8. The agent lists what it did NOT test or cannot model. The user can send those gaps to a bounty. Testers submit worlds that break the robot, and the contract pays per new valid failure.

## Rule for scenario factors
A factor counts only if it changes the physics in code, with the equation or the assumption in PARAMETERS.md. Examples: temperature changes air density and battery output; humidity and condensation change friction; sand and dust add seal leak, friction change and sensor noise, plus wind. A factor we cannot model goes on the not-tested list. It never gets a fake pass.

## Demo limits for Saturday
One robot. Hand-built physics, not validated against real hardware. Weather effects are simplified models. Results are simulated and must say so.

## Product steps added after studying a reference product film (2026-11-06)
Owner's words: "Go on their website and watch that video. It's so helpful." Ideas and flow only, in our own words and form.
1. Ask only what the AI cannot infer: one or two quick questions with options, before building.
2. The AI looks at what it built before running anything, and shows it.
3. It writes numbered pass/fail requirements first, and every world is judged the same way.
4. One normal run first. Then the human check: "Does the scene look right?"
5. A campaign review before spending: objective, requirements, allowed variations, world count, worlds held back, expected compute cost. The human approves.
6. A visible pipeline: queued, running, reproducing, diagnosing, fixing, validating, report. Worlds fill in, then collapse into a map coloured by failure type.
7. Failures are grouped into a few failure types, each with severity, count, worst world and code line. Flaky results that do not reproduce are excluded and shown as excluded.
8. Each fix is validated on held-back worlds, with no regressions, and the whole set is re-run. Before and after side by side.
9. What the code cannot fix is handed on. Ours: it goes to a bounty or to the right owner.
10. A short final report with a few big numbers.
