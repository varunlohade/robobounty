#!/usr/bin/env bash
# Uploads a clean copy of committed files to Railway. The list holds only git-tracked files from an allow list, so .env and keystores cannot enter it.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d /tmp/crashlab-railway-XXXXXX)"
cd "$ROOT"
git archive HEAD Dockerfile .dockerignore package.json deploy docs/evidence policy/bounty policy/server policy/crashlab policy/highrise policy/highrise5 policy/packs/__init__.py policy/packs/window policy/packs/inspection policy/runs/demo | tar -x -C "$STAGE"
cd "$STAGE"
find . -type f | sort > /tmp/crashlab-railway-files.txt
echo "Upload: $(wc -l < /tmp/crashlab-railway-files.txt) files, $(du -sh . | cut -f1). List: /tmp/crashlab-railway-files.txt"
if grep -E '(^|/)(\.env[^/]*|.*keystore.*|.*\.key|design/.*)$' /tmp/crashlab-railway-files.txt | grep -v '\.env\.example'; then echo "Refused: a secret-like path is in the list."; exit 1; fi
if grep -rlIE 'PRIVATE KEY|ZG_API_KEY=.+|WORLD_RP_SIGNING_KEY=.+' . --include='*' | grep -vE 'check_|\.md$'; then echo "Look at those files before upload."; [ "${FORCE_LOOKED:-}" = 1 ] || exit 1; fi
railway up . --path-as-root --detach --service crashlab --message "${1:-deploy}"
