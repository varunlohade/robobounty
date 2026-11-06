#!/usr/bin/env bash
# One command for the whole demo: vite, the run server, the site server and the board server.
#   npm run demo                live: real AI calls and real physics
#   npm run demo -- --recorded  stored results: no AI and no sim in the lab. A fix sent to the board still runs real sims.
#   npm run demo -- --stored    stored AI replies, real physics. No AI call.
# It checks each port first, refuses a port in use and kills nothing it did not start. Ctrl+C stops all four.
# --ports WEB,RUN,SITE,BOARD picks other ports. --board-root DIR keeps the board's ledger elsewhere.
set -u
trap "" PIPE # A closed log pipe must not stop the shutdown below.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE=live
WEB=5199; RUN=5198; SITE=5297; BOARD=5298
BOARD_ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --recorded) MODE=recorded ;;
    --stored) MODE=stored ;;
    --ports) IFS=, read -r WEB RUN SITE BOARD <<<"$2"; shift ;;
    --board-root) BOARD_ROOT="$2"; shift ;;
    *) echo "Unknown option: $1"; sed -n 2,7p "$0"; exit 2 ;;
  esac
  shift
done

PY=policy/.venv/bin/python
[ -x "$PY" ] || { echo "Python is not set up: $PY is missing. See README.md, Run it."; exit 1; }
[ -x node_modules/.bin/vite ] || { echo "Node packages are missing. Run: npm ci"; exit 1; }

busy=0
for port in "$WEB" "$RUN" "$SITE" "$BOARD"; do
  who="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" pid "$2}')"
  if [ -n "$who" ]; then echo "Port $port is in use by $who. I will not touch it."; busy=1; fi
done
if [ "$busy" = 1 ]; then echo "Stop those servers, or pick free ports: npm run demo -- --ports 6199,6198,6297,6298"; exit 1; fi

PIDS=()
LOGS="$(mktemp -d /tmp/crashlab-demo-XXXXXX)"
stop() {
  trap - INT TERM EXIT
  echo; echo "Stopping the four servers."
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null; done
  wait 2>/dev/null
  echo "Stopped. Logs: $LOGS"
  exit "${1:-0}"
}
trap 'stop 0' INT TERM
trap 'stop 1' EXIT

unset CRASHLAB_DEMO_ACCOUNTS
export CRASHLAB_DEMO=1 CRASHLAB_WEB_PORT="$WEB" CRASHLAB_SITE_PORT="$SITE" VITE_RUN_PORT="$RUN" VITE_BOARD_PORT="$BOARD"
case "$MODE" in
  recorded) RECORDED=(--recorded policy/runs/demo); export CRASHLAB_DEMO_ACCOUNTS=1 CRASHLAB_AUTH_DB="$LOGS/auth.sqlite" ;; # Seeded demo accounts, labelled on screen, in a store that ends with this run.
  stored) RECORDED=(--recorded policy/server/fixtures) ;;
  *) RECORDED=() ;;
esac

"$PY" policy/server/supervise.py --port "$RUN" ${RECORDED[@]+"${RECORDED[@]}"} >"$LOGS/run.log" 2>&1 & PIDS+=($!)
"$PY" policy/server/site_data.py --port "$SITE" >"$LOGS/site.log" 2>&1 & PIDS+=($!)
"$PY" policy/bounty/board_server.py --port "$BOARD" ${BOARD_ROOT:+--root "$BOARD_ROOT"} >"$LOGS/board.log" 2>&1 & PIDS+=($!)
node_modules/.bin/vite --port "$WEB" --strictPort >"$LOGS/vite.log" 2>&1 & PIDS+=($!)

ORIGIN="http://localhost:$WEB"
up() {
  local name="$1" url="$2"
  printf '%s ... ' "$name"
  for _ in $(seq 1 150); do
    if curl -fs -o /dev/null -H "Origin: $ORIGIN" "$url"; then echo ok; return 0; fi
    for pid in "${PIDS[@]}"; do kill -0 "$pid" 2>/dev/null || { echo "a server stopped. Logs: $LOGS"; return 1; }; done
    sleep 0.2
  done
  echo "no answer after 30 s. Logs: $LOGS"; return 1
}
up "Run server, port $RUN" "http://127.0.0.1:$RUN/api/health" || exit 1
up "Site server, port $SITE" "http://127.0.0.1:$SITE/site-api/health" || exit 1
up "Board server, port $BOARD" "http://127.0.0.1:$BOARD/api/health" || exit 1
up "Web server, port $WEB" "$ORIGIN/login.html" || exit 1

# The first request to each page makes vite prepare its code. Doing it here saves the judge that wait.
printf 'Warming up the pages ... '
for path in login.html home.html simulation.html lab.html bounties.html data.html src/lab/main.ts src/board/main.ts src/site/data.ts src/site/home.ts src/app/view.ts; do
  curl -fs -o /dev/null "$ORIGIN/$path"
done
echo ok

echo
case "$MODE" in
  recorded) echo "Recorded run: stored results, no AI and no sim in the lab. A fix sent to the board runs real sims." ;;
  stored) echo "Stored AI replies, real physics." ;;
  *) echo "Live: real AI calls and real physics." ;;
esac
echo "Open $ORIGIN/"
echo "Press Ctrl+C to stop."
while :; do
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || { echo "A server stopped by itself. Logs: $LOGS"; stop 1; }
  done
  sleep 1 & wait $! 2>/dev/null
done
