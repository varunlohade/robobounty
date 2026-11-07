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
export CRASHLAB_DEMO_ACCOUNTS="${CRASHLAB_DEMO_ACCOUNTS:-0}" # Off unless the owner asks. Sign-in is guest and real accounts.
export CRASHLAB_DEMO=1 CRASHLAB_ARC_DEMO=1 CRASHLAB_POST_CAP="${CRASHLAB_POST_CAP:-5}" # The recorded proof, tagged so, and a cap on one account's bounties.
unset CRASHLAB_ARC
if [ -n "${ARC_KEYSTORE_RESOLVER:-}" ] && [ -n "${ARC_KEYSTORE_ARBITER:-}" ] && [ -n "${ARC_KEYSTORE_PASSWORD:-}" ]; then
  # The agent's two wallets become files outside the repo, readable by this user only, and leave the environment. The company and tester wallets are never here.
  WALLETS="$HOME/.crashlab-arc"
  (umask 077; mkdir -p "$WALLETS"; printf '%s' "$ARC_KEYSTORE_RESOLVER" > "$WALLETS/resolver"; printf '%s' "$ARC_KEYSTORE_ARBITER" > "$WALLETS/arbiter"; printf '%s' "$ARC_KEYSTORE_PASSWORD" > "$WALLETS/password")
  export ARC_WALLET_DIR="$WALLETS" CRASHLAB_ARC=1
  cp deploy-files/arc.json "$DATA/board/arc.json"
fi
unset ARC_KEYSTORE_RESOLVER ARC_KEYSTORE_ARBITER ARC_KEYSTORE_PASSWORD
PY=policy/.venv/bin/python
"$PY" policy/bounty/arc_wallet.py seed-campaign
"$PY" policy/server/site_data.py --port 5297 &
env -u WORLD_RP_SIGNING_KEY "$PY" policy/bounty/board_server.py --port 5298 &
if [ "${CRASHLAB_ARC:-}" = 1 ]; then
  # A chain or gas problem must not stop the site, so the agent retries on its own and never ends this script.
  (while :; do env -u WORLD_RP_SIGNING_KEY "$PY" policy/bounty/arc_wallet.py serve || true; sleep 30; done) &
fi
caddy run --config deploy-files/Caddyfile --adapter caddyfile &
wait -n
echo "A server stopped, so the container stops and Railway starts it again."
exit 1
