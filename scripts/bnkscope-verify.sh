#!/usr/bin/env bash
# bnkscope verification loop: does the backend still import, and what is the
# API surface now?  Runs against the working tree inside the already-built
# bnkscope-api image, so no local Python toolchain is needed.
#
#   ./scripts/bnkscope-verify.sh              # import + route/path count
#   ./scripts/bnkscope-verify.sh <pytest...>  # also run a pytest selection
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${BNKSCOPE_VERIFY_IMAGE:-bnkscope-api:latest}"
RUN=(docker run --rm --entrypoint python
     -v "$PWD/backend:/app" -w /app
     -e DATABASE_URL="sqlite:////tmp/verify.db"
     "$IMAGE")

"${RUN[@]}" -c "
import main
paths = main.app.openapi()['paths']
print(f'IMPORT OK  routes={len(main.app.routes)}  openapi_paths={len(paths)}')
" 2>&1 | grep -Ev '^[0-9]{4}-[0-9]{2}-[0-9]{2} ' || {
  echo "IMPORT FAILED" >&2
  exit 1
}

# Importing main.py only proves the import graph is intact — a deleted name still
# referenced inside a function body fails at request time, not import time. F821
# catches exactly that; it is the check that makes large deletions safe.
if ! docker image inspect bnkscope-ruff >/dev/null 2>&1; then
  docker build -q -t bnkscope-ruff - >/dev/null <<'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir ruff==0.15.2
DOCKERFILE
fi
docker run --rm -v "$PWD/backend:/app" -w /app bnkscope-ruff \
  ruff check --select F821,F811 --no-cache --output-format concise . \
  || { echo "RUFF F821/F811 FAILED — dangling references to deleted code" >&2; exit 1; }

if [ $# -gt 0 ]; then
  docker run --rm --entrypoint python \
    -v "$PWD/backend:/app" -w /app \
    -e DATABASE_URL="sqlite:////tmp/verify.db" \ \
    "$IMAGE" -m pytest "$@"
fi
