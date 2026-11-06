# RoboBounty (working name)

Companies post a robotics problem, their robot (MJCF/URDF) and a bounty.
Solvers submit a controller. The platform runs it in MuJoCo in the browser,
scores it over many randomized runs, ranks it, and pays the winner.

Built from scratch at ETHGlobal Mumbai (Nov 5–7 2026).

## AI use
Built with Claude Code (Claude Opus 5.5). See AI-USE.md for which parts.

## CrashLab run server (demo shortcut)
`policy/server/server.py` runs the chat flow for `app.html`. It is a demo shortcut that an embedded runtime can replace, not a hosted service.
It binds to 127.0.0.1 only and refuses any other origin. Chat text goes only to the LLM layer, and no shell string is built from it. It runs at most 4 sim or LLM processes at once.

    npx vite --port 5199
    policy/.venv/bin/python policy/server/server.py

Open `http://localhost:5199/app.html`. `app.html?trial=<id>` still shows a recorded run with the stub chat.
`app.html?recorded=1` is the demo fallback, labelled "Recorded run". It needs only vite and loads the finished Dubai campaign from `public/trials/worlds.json`. No run server, AI or simulation runs.
Check: `node src/app/tools/check_live.mjs <out dir>`. It makes real LLM calls. Add `--recorded` to use the stored replies in `policy/server/fixtures/`. Add `--live-fix` to run `fix.py` in place of the stored report.
LLM calls have a limit of 10 a session and 40 an hour across sessions. The bounty uses `policy/server/ledger.py`, a local ledger with the contract's states. It is not on chain and needs no wallet or key.

## Checking the numbers
Every headline number comes from one campaign, `campaign_dubai_final`. `policy/runs` is not in git, so `docs/evidence/` holds its JSON summaries. `python3 policy/crashlab/check_numbers.py --evidence` recomputes the numbers and checks the app data and the site.
