#!/bin/zsh
# Renders the three app screens to PNG and prints any clipped or undersized text.
cd "${0:A:h}" || exit 1
PYTHONHASHSEED=0 python3 build_app_dark.py
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for n in 1 2 3; do
  "$CH" --headless --screenshot="$PWD/app-$n-dark.png" --window-size=1440,900 --hide-scrollbars --force-device-scale-factor=1 "file://$PWD/app-$n-dark.html" >/dev/null 2>&1
  python3 -c "import sys;h=open(sys.argv[1]).read();c=open('check_app.js').read();open(sys.argv[2],'w').write(h.replace('</body>','<script>'+c+'</script></body>'))" "app-$n-dark.html" ".chk-$n.html"
  echo "--- app-$n"
  "$CH" --headless --dump-dom --window-size=1440,900 "file://$PWD/.chk-$n.html" 2>/dev/null | sed -n '/<pre id="res">/,/<\/pre>/p' | sed 's/<[^>]*>//g'
  rm -f ".chk-$n.html"
done
