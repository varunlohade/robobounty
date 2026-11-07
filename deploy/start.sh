#!/usr/bin/env bash
# Starts the hosted backend. Both Python servers bind to 127.0.0.1. Caddy alone faces the network.
set -eu
: "${CRASHLAB_PUBLIC_ORIGIN:?Set CRASHLAB_PUBLIC_ORIGIN to the site, https://...}"
export CRASHLAB_BACKEND_HOST="${CRASHLAB_BACKEND_HOST:-${RAILWAY_PUBLIC_DOMAIN:?No public domain yet}}"
DATA="${CRASHLAB_DATA:-/data}"
if [ "$(id -u)" = 0 ]; then
  mkdir -p "$DATA"
  chown -R app "$DATA"
  exec setpriv --reuid=1000 --regid=1000 --init-groups env HOME=/home/app "$0" "$@"
fi
cd /app
mkdir -p "$DATA/board" "$DATA/server"
ln -sfn "$DATA/board" policy/runs/board
ln -sfn "$DATA/server" policy/runs/server
export CRASHLAB_AUTH_DB="$DATA/auth.sqlite" CRASHLAB_HTTPS=1 CRASHLAB_TRUST_PROXY=1 CRASHLAB_HOSTED=1
export CRASHLAB_DEMO=1 CRASHLAB_DEMO_ACCOUNTS=1 CRASHLAB_ARC_DEMO=1 # Recorded mode: seeded demo accounts, labelled on screen, and the recorded proof, tagged so.
unset CRASHLAB_ARC
PY=policy/.venv/bin/python
"$PY" policy/bounty/arc_wallet.py seed-campaign
"$PY" policy/server/site_data.py --port 5297 &
"$PY" policy/bounty/board_server.py --port 5298 &
caddy run --config deploy-files/Caddyfile --adapter caddyfile &
wait -n
echo "A server stopped, so the container stops and Railway starts it again."
exit 1
