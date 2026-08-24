#!/usr/bin/env bash
# Frontend half of the bnkscope verification loop: TypeScript must still compile.
#
# node_modules lives in a named docker volume so repeated runs skip `npm ci`.
# Pass --install to (re)install after a package.json change.
#
#   ./scripts/bnkscope-verify-frontend.sh            # tsc --noEmit
#   ./scripts/bnkscope-verify-frontend.sh --install  # npm ci first
#   ./scripts/bnkscope-verify-frontend.sh --test     # tsc + vitest
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

VOLUME=bnkscope-node
docker volume create "$VOLUME" >/dev/null

run() {
  docker run --rm -v "$PWD/frontend-v2:/app" -v "$VOLUME:/app/node_modules" \
    -w /app node:20-alpine sh -c "$1"
}

case "${1:-}" in
  --install) run "npm ci --no-audit --no-fund" >/dev/null || exit 1 ;;
esac

echo "tsc --noEmit ..."
if out=$(run "npx tsc --noEmit" 2>&1); then
  echo "TSC OK"
else
  echo "$out" | head -40
  echo "TSC FAILED ($(echo "$out" | grep -c 'error TS') errors)" >&2
  exit 1
fi

if [ "${1:-}" = "--test" ]; then
  run "npx vitest run --reporter=dot" 2>&1 | tail -25
fi
