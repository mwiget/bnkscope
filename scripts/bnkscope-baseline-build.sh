#!/usr/bin/env bash
# Phase-0 baseline: cold (--no-cache) single-arch build of every image a
# developer builds locally, timed per service, plus a warm rebuild of the
# backend + frontend to capture the daily edit→rebuild loop.
#
# Writes TSV to the path given as $1 (default: /tmp/bnkscope-build.tsv).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

OUT="${1:-/tmp/bnkscope-build.tsv}"
: > "$OUT"

# Compose interpolates the whole file on every command, `build` included, and
# Grafana's password is a required variable there. Nothing here starts Grafana,
# so a placeholder is enough — it just has to be set.
export BNKSCOPE_GRAFANA_PASSWORD="${BNKSCOPE_GRAFANA_PASSWORD:-baseline}"
# The MCP service sits behind a profile; without this it is not buildable.
export COMPOSE_PROFILES=mcp

SERVICES="backend frontend mcp"

echo "=== COLD BUILD (--no-cache) ===" >&2
for svc in $SERVICES; do
  start=$(date +%s)
  docker compose build --no-cache "$svc" >/dev/null 2>&1
  rc=$?
  end=$(date +%s)
  printf 'cold\t%s\t%s\t%s\n' "$svc" "$((end - start))" "$rc" | tee -a "$OUT" >&2
done

echo "=== WARM REBUILD (real source change, layer cache warm) ===" >&2
# BuildKit hashes file CONTENT, not mtime — `touch` alone is a no-op rebuild.
# Append a marker line, rebuild, then restore the file exactly. The comment
# marker must be valid in the target language or the build fails on lint/tsc.
warm_build() {
  local svc="$1" file="$2" prefix="#"
  case "$file" in *.ts|*.tsx|*.js|*.jsx) prefix="//" ;; esac
  echo "$prefix bnkscope-baseline-warm-rebuild-marker" >> "$file"
  local start end rc
  start=$(date +%s)
  docker compose build "$svc" >/dev/null 2>&1
  rc=$?
  end=$(date +%s)
  git checkout -- "$file"
  printf 'warm\t%s\t%s\t%s\n' "$svc" "$((end - start))" "$rc" | tee -a "$OUT" >&2
}
warm_build backend  backend/main.py
warm_build frontend frontend-v2/src/main.tsx

echo "=== IMAGE SIZES ===" >&2
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' \
  | grep -E '^bnkscope-' | sort | tee -a "$OUT" >&2

echo "DONE" >&2
