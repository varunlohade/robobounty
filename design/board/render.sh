#!/bin/bash
# Renders the two board sketches at 1440x900, with their own Chrome profile.
D="$(cd "$(dirname "$0")" && pwd)"
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PR=$(mktemp -d /tmp/board-chrome.XXXX)
for f in board-1 board-2; do
  "$CH" --headless --no-first-run --user-data-dir="$PR" --screenshot="$D/$f.png" --window-size=1440,900 --hide-scrollbars --virtual-time-budget=1500 "file://$D/$f.html" 2>/dev/null
done
rm -rf "$PR"
