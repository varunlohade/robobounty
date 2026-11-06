# CrashLab design brief, round 4: the app

Read ../docs/PRODUCT.md first (from your folder it may be at _brief/PRODUCT.md). This is the main product: a Mac app with a chat on the left and a live simulation on the right. It is like an AI code editor's chat panel, but better, and made for simulation.

## Make three screens (static HTML, 1440x900 each, no JavaScript, inline CSS)
- `app-1.html`: chat building the world. The user wrote "I'm building a window-cleaning robot for towers in Dubai." The AI replied with a short summary of what it set up. Right: the glass tower section with the robot on it, with small live readings for wind, suction and grip.
- `app-2.html`: the moment after the first test. In the chat, a card says "Test this on 40 worlds", with "See the 40 worlds". The panel lists worlds with a plain reason per world, grouped: sandstorm, high-floor wind, humidity, low friction, odd mullion edges, heat. Show the agent's reason for why it chose 40. Include a "Not tested" list with a "Send to a bounty" action.
- `app-3.html`: results. Right: a grid of 40 small worlds, some failed. One failure is open with a replay and a timeline of what went wrong. Left: chat explains the pattern in plain words with counts, shows the line of code, and offers "Try a fix". Show bounty status as well.

## The look
White, calm and expensive. Near-black ink. One quiet deep accent, and red only for failures. Palatino for headings and for the user's own words: `font-family: Palatino, "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif;`. A clean sans for interface text and a real code font for code. Normal Mac app window feel. It must not look like a dark VS Code clone, and it must not look like a generic chatbot.

## The simulation pane
No real high-rise render exists yet. Draw it simply with CSS or SVG shapes as flat clean geometry: glass panes, mullions, a city far below, a flat square robot about one pane's fifth wide, a thin tether going up, and a clean path behind it in a dirt film. Do not invent a photo. A later render replaces this.

## Robot
A flat square suction window robot on tracks with one tether, like a home window robot scaled up. No arms.

## Honesty
All numbers are placeholders. Show "Sample data" in small text. Label results "Simulated". No real organisation's name or logo. Say "replay the recorded run", never "reproducible from a seed".

## Rules
No gradients, glows, vignettes. No status dots. No identical rounded cards with soft shadows. No tracked ALL-CAPS eyebrow labels. No "A · B · C" meta strings. No arrows on every button. No mono labels outside code. No one accented word in a headline. No body text under 16px except code and small labels at 13px or more.

## Output
`app-1.html`, `app-2.html`, `app-3.html` in your folder, plus a short update to NOTES.md.
