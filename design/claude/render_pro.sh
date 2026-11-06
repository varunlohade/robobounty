#!/bin/bash
# Renders pro screens at 1x and 2x, and lists clipped or off-scale text.
D=/Users/varun/robobounty/design/claude; cd "$D"
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PR=$(mktemp -d /tmp/pro-chrome.XXXX); OUT=/tmp/pro-2x; mkdir -p $OUT
for f in "$@"; do
  "$CH" --headless --no-first-run --user-data-dir=$PR --screenshot=$D/$f.png --window-size=1440,900 --hide-scrollbars --virtual-time-budget=1500 file://$D/$f.html 2>/dev/null
  "$CH" --headless --no-first-run --user-data-dir=$PR --screenshot=$OUT/$f.png --window-size=1440,900 --force-device-scale-factor=2 --hide-scrollbars --virtual-time-budget=1500 file://$D/$f.html 2>/dev/null
  sed 's|</body>|<script src="pro-check.js"></script></body>|' $f.html > .chk-$f.html
  echo "== $f"; "$CH" --headless --no-first-run --user-data-dir=$PR --virtual-time-budget=1500 --window-size=1440,900 --dump-dom file://$D/.chk-$f.html 2>/dev/null | sed -n '/<pre id="res">/,/<\/pre>/p' | sed 's/<[^>]*>//g'
  rm -f .chk-$f.html
done
