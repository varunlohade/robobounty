#!/bin/sh
# One command for the mechanical part of the loop on the current sim. Run from anywhere. Writes only under policy/runs.
#   loop.sh <tag> [--live-chat] [--word] [--fix]
# Default reuses the stored Dubai plan, with no LLM call. --live-chat asks the scenario agent again (1 call). --word words the diagnosis (1 call).
# Other workers edit policy/highrise in this tree, so to pin the sim run this from a clean checkout:
#   git worktree add /tmp/frozen <commit> && ln -s "$PWD/policy/.venv" /tmp/frozen/policy/.venv && ln -s "$PWD/policy/runs" /tmp/frozen/policy/runs
#   /tmp/frozen/policy/crashlab/loop.sh <tag> --fix
# --fix runs fix.py (up to 3 calls). Stops at the first failed step. Nothing here changes controller.py.
set -e
POLICY="$(cd "$(dirname "$0")/.." && pwd)"
PY="$POLICY/.venv/bin/python"
TAG="$1"; shift
[ -n "$TAG" ] || { echo "usage: loop.sh <tag> [--live-chat] [--word] [--fix]"; exit 2; }
LIVE=; WORD=; FIX=
for a in "$@"; do case "$a" in --live-chat) LIVE=1;; --word) WORD=--word;; --fix) FIX=1;; *) echo "unknown $a"; exit 2;; esac; done
CHAT="I have a window cleaning robot for glass towers in Dubai. Dubai has sandstorms. Some buildings are very high up, so they get very strong winds. Some have high moisture and high humidity, some have low friction and some high friction, and some have weird edges. It also gets very hot."
SC="$POLICY/runs/scenarios/dubai_$TAG"
CAMP="$POLICY/runs/highrise/campaign_dubai_$TAG"
cd "$POLICY/crashlab"
"$PY" check_brief.py
"$PY" check_scenarios.py
"$PY" check_diagnose.py
"$PY" check_fix.py
if [ -n "$LIVE" ]; then
  "$PY" scenarios.py "$CHAT" --out "$SC" --seed 1
else
  "$PY" scenarios.py "$CHAT" --out "$SC" --seed 1 --reply "$POLICY/runs/scenarios/dubai_v3/scenarios.json"
fi
"$PY" check_scenarios.py --scan "$SC"
"$PY" requirements.py "$CAMP"
nice -n 10 "$PY" ../highrise/campaign.py --scenarios "$SC" --seed 31 --controls 10 --out "$CAMP" --procs 4
nice -n 10 "$PY" ../highrise/linetrace.py "$CAMP" --procs 4
nice -n 10 "$PY" diagnose.py "$CAMP" --reproduce --retest --oracle $WORD
if [ -n "$FIX" ]; then nice -n 10 "$PY" fix.py run "$CAMP"; fi
echo "LOOP DONE $CAMP"
