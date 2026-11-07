#!/usr/bin/env bash
# Builds the pages and deploys them to the crashlab Vercel project, without moving the live domain. Promote later with: vercel promote URL
#   deploy/vercel.sh https://BACKEND.up.railway.app
set -eu
BACKEND="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mktemp -d /tmp/crashlab-vercel-XXXXXX)"
cd "$ROOT"
VITE_HOSTED=1 nice -n 19 node_modules/.bin/vite build --config deploy/vite.hosted.ts --outDir "$OUT" --emptyOutDir
rm -rf "$OUT/generated" "$OUT/trials"
for page in lab app crashlab toy; do cp "$OUT/simulation.html" "$OUT/$page.html"; done
cp site-public/index.html "$OUT/index.html"
cp -R site-public/fonts site-public/img "$OUT/"
mkdir "$OUT/.vercel"
cp site-public/.vercel/project.json "$OUT/.vercel/"
cat > "$OUT/vercel.json" <<JSON
{"rewrites":[{"source":"/site-api/:path*","destination":"$BACKEND/site-api/:path*"},{"source":"/board/:path*","destination":"$BACKEND/board/:path*"}]}
JSON
du -sh "$OUT"
(cd "$OUT" && vercel deploy --prod --skip-domain --yes)
