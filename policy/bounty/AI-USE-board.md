# AI use: bounty board

Claude (Opus 5.5), as the junior-dev agent, wrote each file below. Varun Lohade has not reviewed them yet.

Backend:
- policy/bounty/board_spec.py
- policy/bounty/board_store.py
- policy/bounty/board_gate.py
- policy/bounty/board_server.py
- policy/bounty/check_board.py
- policy/bounty/AI-USE-board.md

Sketches:
- design/board/board-1.html and design/board/board-1.png
- design/board/board-2.html and design/board/board-2.png
- design/board/render.sh

Not AI-written here: design/board/assets holds copies of the Inter and JetBrains Mono font files from design/claude/pro-assets. The icons in the sketches come from Lucide 0.400.

The board calls gate.py, ledger.py and the sim without changes. Results are simulated with hand-built physics. The ledger is local and not on chain.

Fix bounties, also written by Claude (Opus 5.5) as the junior-dev agent and not yet reviewed by Varun Lohade:
- policy/bounty/board_fix.py, board_fix_run.py, board_fix_gate.py, board_fix_routes.py
- policy/bounty/budget.py, agent_post.py, anvil_mirror.py, check_board_fix.py
- policy/bounty/fixtures/fix5/good_match_fan.py, a controller change used as a test source
- bounties.html and src/board/*, except src/board/fonts, which holds copies of the Inter and JetBrains Mono files from src/lab/fonts. The icons come from Lucide 0.400.
- design/board/board-real.png, board-empty.png and board-post.png, screenshots of the real page

board_server.py gained the route mount and origin 5199. The fix bounty calls fix.py, ledger.py, gate.py and the sim without changes, and imports src/site/shell.ts. No LLM runs on the board's path. Results are simulated with hand-built physics, and a passed fix says nothing about a real robot. The ledger is local and not on chain. The anvil mirror uses a local test chain only, with anvil's public dev accounts and a test token.
