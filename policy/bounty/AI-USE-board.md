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
