#!/bin/bash
#
# bnkscope upgrade — pull, rebuild, restart, verify.
#
# Non-destructive: the volumes stay. The database, the encryption key and the
# telemetry history all survive. `bnkscope down --purge` is the destructive one.
#
# Usage:
#   ./upgrade.sh                      - pull + rebuild + restart
#   ./upgrade.sh --local              - rebuild + restart (no git pull)
#   ./upgrade.sh --allow-dirty        - allow a dirty working tree
#   ./upgrade.sh --allow-non-main     - allow a branch other than main
#   ./upgrade.sh --allow-diverged     - allow HEAD to differ from origin/main
#   ./upgrade.sh --allow-same-version - allow a commit upgrade with no VERSION bump
#   ./upgrade.sh --skip-disk-check    - skip the disk threshold guard
#
# There is no --no-cache here: this always builds through the layer cache.
# For a cold rebuild, `make build-clean`.
#
# The build and restart run through `./bnkscope up`, not through compose
# directly, and that is the whole point of this script's middle. The negotiated
# ports, the remembered `--listen` bind, the telemetry and MCP profiles, and
# Grafana's generated password live in the CLI and in the discovery file at
# ~/.config/bnkscope/endpoints.json. A bare `docker compose up -d` recreates
# the backend from compose's own defaults instead — moving the API back to
# :8000, closing a deliberately-opened bind back to loopback, and starting or
# stopping telemetry against the operator's choice.
#
# Phase markers (##PHASE:xxx) are parsed by the backend to report structured
# progress to the frontend UI (services/system_service.py::_phase_labels). Do
# not remove or rename them without updating that map and the phase list in
# frontend-v2/src/components/settings/SystemUpgrade.tsx.
#
# Exit codes:
#   0 — upgrade succeeded, all services healthy
#   1 — prerequisites missing (docker compose, or not a bnkscope checkout)
#   2 — build or start failed
#   5 — health check failed (services not healthy after timeout)
#   6 — preflight policy check failed
#
# 3 (start failed) and 4 (database migration failed) are retired: build and
# start are now one command, and Alembic went with Phase 4 — bnkscope creates
# its schema from the ORM models at startup (backend/database.py).
#

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
LOCAL_ONLY=false
ALLOW_DIRTY=false
ALLOW_DIVERGED=false
SKIP_DISK_CHECK=false
ALLOW_NON_MAIN=false
ALLOW_SAME_VERSION=false

for arg in "$@"; do
    case $arg in
        --local|-l) LOCAL_ONLY=true ;;
        --allow-dirty) ALLOW_DIRTY=true ;;
        --allow-diverged) ALLOW_DIVERGED=true ;;
        --skip-disk-check) SKIP_DISK_CHECK=true ;;
        --allow-non-main) ALLOW_NON_MAIN=true ;;
        --allow-same-version) ALLOW_SAME_VERSION=true ;;
    esac
done

echo "##PHASE:start"
echo "bnkscope upgrade"
echo "=================================="
echo ""

# Containers, not compose services: `docker ps` needs no compose file, no
# profiles, and no BNKSCOPE_GRAFANA_PASSWORD to interpolate.
ps_table() {
    docker ps -a --filter 'name=bnkscope-' --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true
}

container_exists() { docker inspect "$1" >/dev/null 2>&1; }

# Record current version for comparison
OLD_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Current version: ${OLD_VERSION} (commit: ${OLD_COMMIT})"

# ---------------------------------------------------------------------------
# Phase 0: Preflight policy checks
# ---------------------------------------------------------------------------
echo ""
echo "##PHASE:preflight"
echo "Running preflight checks..."

# Check working tree cleanliness
if [ "$ALLOW_DIRTY" = false ]; then
    if [ -n "$(git status --porcelain 2>/dev/null || true)" ]; then
        echo ""
        echo "##PHASE:failed"
        echo "ERROR: Working tree is not clean."
        echo "  Commit/stash changes before upgrade, or rerun with --allow-dirty"
        echo "  Command: git status --short"
        exit 6
    fi
    echo "  ✓ Git working tree clean"
else
    echo "  ⚠ Skipping dirty-tree check (--allow-dirty)"
fi

# Check branch policy (upgrades should run from main unless explicitly overridden)
if [ "$ALLOW_NON_MAIN" = false ]; then
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    if [ "$CURRENT_BRANCH" != "main" ]; then
        echo ""
        echo "##PHASE:failed"
        echo "ERROR: Upgrade must run from main branch (current: ${CURRENT_BRANCH})."
        echo "  Switch to main and sync first: git checkout main && git pull --ff-only"
        echo "  Or rerun with --allow-non-main (not recommended)"
        exit 6
    fi
    echo "  ✓ Branch policy check passed (main)"
else
    echo "  ⚠ Skipping main-branch check (--allow-non-main)"
fi

# Check disk policy (critical threshold should fail)
if [ "$SKIP_DISK_CHECK" = false ] && [ -x "./scripts/check-disk-space.sh" ]; then
    set +e
    ./scripts/check-disk-space.sh
    DISK_RC=$?
    set -e
    if [ $DISK_RC -eq 2 ]; then
        echo ""
        echo "##PHASE:failed"
        echo "ERROR: Disk usage above critical threshold (>=85%)."
        echo "  Run: ./scripts/docker-cleanup.sh"
        echo "  Or rerun with --skip-disk-check (not recommended)"
        exit 6
    elif [ $DISK_RC -eq 1 ]; then
        echo "  ⚠ Disk usage warning (>=70%). Proceeding."
    else
        echo "  ✓ Disk usage check passed"
    fi
elif [ "$SKIP_DISK_CHECK" = true ]; then
    echo "  ⚠ Skipping disk check (--skip-disk-check)"
else
    echo "  ⚠ Disk check script not found or not executable: ./scripts/check-disk-space.sh"
fi

# ---------------------------------------------------------------------------
# Phase 1: Pull latest code
# ---------------------------------------------------------------------------
echo ""
echo "##PHASE:pull"

if [ "$LOCAL_ONLY" = false ]; then
    echo "Pulling latest code..."
    # gh auth is optional — don't fail if not available
    gh auth setup-git 2>/dev/null || true

    if git pull --ff-only; then
        NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        if [ "$OLD_COMMIT" != "$NEW_COMMIT" ]; then
            echo "  Updated: ${OLD_COMMIT} -> ${NEW_COMMIT}"
            git diff --stat "${OLD_COMMIT}..${NEW_COMMIT}" 2>/dev/null | head -10
        else
            echo "  Already up to date."
        fi
    else
        echo ""
        echo "##PHASE:failed"
        echo "ERROR: git pull --ff-only failed."
        echo "  Resolve branch divergence first, then retry: git pull --ff-only"
        exit 6
    fi
else
    echo "Local mode: skipping git pull"
fi

# Sync policy check: in --local mode, HEAD must match origin/main unless overridden.
# In pull mode, enforce this after pull to ensure target commit was actually reached.
if [ "$ALLOW_DIVERGED" = false ]; then
    git fetch origin main >/dev/null 2>&1 || true
    HEAD_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    ORIGIN_MAIN_COMMIT=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
    if [ "$HEAD_COMMIT" != "$ORIGIN_MAIN_COMMIT" ]; then
        echo ""
        echo "##PHASE:failed"
        echo "ERROR: Local HEAD does not match origin/main."
        echo "  HEAD:        ${HEAD_COMMIT}"
        echo "  origin/main: ${ORIGIN_MAIN_COMMIT}"
        if [ "$LOCAL_ONLY" = true ]; then
            echo "  Local mode requires repo to already be synced."
            echo "  Run: git pull --ff-only"
        else
            echo "  Pull did not converge to origin/main. Resolve and retry."
        fi
        echo "  Or rerun with --allow-diverged (not recommended)"
        exit 6
    fi
    echo "  ✓ Git HEAD aligned with origin/main"
else
    echo "  ⚠ Skipping origin/main sync check (--allow-diverged)"
fi

NEW_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
echo "  Target version: ${NEW_VERSION}"

# Version policy check (D17): if commit changed during this upgrade, VERSION should also change.
CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
if [ "$ALLOW_SAME_VERSION" = false ] && [ "$OLD_COMMIT" != "$CURRENT_COMMIT" ] && [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
    echo ""
    echo "##PHASE:failed"
    echo "ERROR: Commit changed but VERSION was not bumped (policy D17)."
    echo "  Old commit: ${OLD_COMMIT}"
    echo "  New commit: ${CURRENT_COMMIT}"
    echo "  Version:    ${OLD_VERSION}"
    echo "  Bump VERSION (and frontend-v2/package.json if required), commit, and retry."
    echo "  Or rerun with --allow-same-version (not recommended)"
    exit 6
fi
if [ "$OLD_COMMIT" != "$CURRENT_COMMIT" ] && [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
    echo "  ⚠ Version unchanged while commit changed (--allow-same-version)"
elif [ "$OLD_COMMIT" != "$CURRENT_COMMIT" ]; then
    echo "  ✓ Version policy check passed (${OLD_VERSION} -> ${NEW_VERSION})"
fi

# ---------------------------------------------------------------------------
# Phase 2: Build and restart
#
# One command, because `bnkscope up` is the only thing that knows the whole
# shape of a running install — see the note at the top of this file. It builds
# through the layer cache, so services whose inputs did not change cost
# seconds; there is no service-level change detection to keep in step with
# docker-compose.yml any more.
# ---------------------------------------------------------------------------
echo ""
echo "##PHASE:build"

# Prerequisites are checked here rather than at the top on purpose: everything
# above this line is git policy, which is worth enforcing — and worth being
# able to test — on a checkout that has no Docker at all.
if ! docker compose version >/dev/null 2>&1; then
    echo "##PHASE:failed"
    echo "ERROR: 'docker compose' not found."
    exit 1
fi
if [ ! -x ./bnkscope ]; then
    echo "##PHASE:failed"
    echo "ERROR: ./bnkscope not found or not executable — this is not a bnkscope checkout."
    exit 1
fi

echo "Building images and restarting services..."
BUILD_START=$(date +%s)

if ! ./bnkscope up; then
    echo ""
    echo "##PHASE:failed"
    echo "ERROR: Build or start failed."
    echo "  The running system may still be on version ${OLD_VERSION}."
    echo "  Check the output above, then: ./bnkscope logs"
    echo ""
    ps_table
    exit 2
fi

BUILD_END=$(date +%s)
echo "  ✓ Build and restart complete in $((BUILD_END - BUILD_START))s"

# ---------------------------------------------------------------------------
# Phase 3: Health verification
#
# `bnkscope up` already waits for the API. These gates are the stricter pass:
# container health, a backend log free of fatal startup patterns, and the
# health endpoint reporting healthy rather than merely answering.
# ---------------------------------------------------------------------------
echo ""
echo "##PHASE:verify"
echo "Verifying services..."

# The API port is negotiated, so read it back rather than assuming 8000. The
# backend runs with host networking, so the port it listens on inside the
# container is the same one it publishes.
API_PORT=$(./bnkscope endpoint 2>/dev/null \
    | sed -n '/"api"/,/}/s/.*"port": *\([0-9]*\).*/\1/p' | head -1)
API_PORT="${API_PORT:-8000}"
echo "  API port: ${API_PORT}"

health_response() {
    docker exec bnkscope-backend \
        curl -sf "http://127.0.0.1:${API_PORT}/api/system/health" 2>/dev/null || true
}

HEALTH_OK=false
MAX_WAIT=60
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH_RESPONSE=$(health_response)
    if [ -n "$HEALTH_RESPONSE" ] && echo "$HEALTH_RESPONSE" | grep -q '"status":"healthy"'; then
        HEALTH_OK=true
        break
    fi
    WAITED=$((WAITED + 2))
    echo "  Waiting... (${WAITED}s / ${MAX_WAIT}s)"
    sleep 2
done

if [ "$HEALTH_OK" = false ]; then
    echo ""
    echo "##PHASE:failed"
    echo "ERROR: Services did not become healthy within ${MAX_WAIT} seconds."
    echo ""
    echo "  Service status:"
    ps_table
    echo ""
    echo "  Last health response: ${HEALTH_RESPONSE:-none}"
    echo ""
    echo "  Troubleshooting:"
    echo "    ./bnkscope logs backend"
    echo "    ./bnkscope logs frontend"
    exit 5
fi

# Gate 1: critical containers must be running and healthy.
#
# Built from what is actually deployed, not from a fixed list: MCP and the
# telemetry stack are optional profiles (`bnkscope up --no-mcp`,
# `--no-telemetry`), and a container the operator opted out of is not a fault.
echo "  Verifying container health gate..."
CRITICAL_SERVICES=(bnkscope-backend bnkscope-frontend)
for optional in bnkscope-mcp bnkscope-prometheus bnkscope-grafana bnkscope-loki bnkscope-alloy; do
    if container_exists "$optional"; then
        CRITICAL_SERVICES+=("$optional")
    fi
done

# `starting` is not a verdict. Docker reports it for the whole of a
# healthcheck's start_period, and the frontend is reliably still inside that
# window here — `bnkscope up` returns once the *API* answers, which says
# nothing about nginx. Treating it as a fault failed the gate on a stack that
# was coming up perfectly well, so wait for each container to settle and fail
# only on a genuine unhealthy, a stopped one, or a start period that overruns.
GATE_WAIT=90

for svc in "${CRITICAL_SERVICES[@]}"; do
    gate_waited=0
    while :; do
        if ! container_exists "$svc"; then
            echo ""
            echo "##PHASE:failed"
            echo "ERROR: Required container not found: $svc"
            printf '  Troubleshoot: docker ps -a --format "table {{.Names}}\t{{.Status}}"\n'
            exit 5
        fi

        STATUS=$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo "unknown")
        HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$svc" 2>/dev/null || echo "unknown")

        if [ "$STATUS" != "running" ]; then
            echo ""
            echo "##PHASE:failed"
            echo "ERROR: Container is not running: $svc (status=$STATUS)"
            echo "  Troubleshoot: docker logs $svc --tail 50"
            exit 5
        fi

        # No healthcheck defined, or it has passed.
        if [ "$HEALTH" = "none" ] || [ "$HEALTH" = "healthy" ]; then
            break
        fi

        if [ "$HEALTH" = "starting" ] && [ "$gate_waited" -lt "$GATE_WAIT" ]; then
            if [ "$gate_waited" = 0 ]; then
                echo "    $svc: waiting out its healthcheck start period..."
            fi
            gate_waited=$((gate_waited + 3))
            sleep 3
            continue
        fi

        echo ""
        echo "##PHASE:failed"
        if [ "$HEALTH" = "starting" ]; then
            echo "ERROR: Container did not finish its healthcheck start period within ${GATE_WAIT}s: $svc"
        else
            echo "ERROR: Container health not healthy: $svc (health=$HEALTH)"
        fi
        echo "  Troubleshoot: docker logs $svc --tail 50"
        exit 5
    done
done
echo "  ✓ Container health gate passed (${#CRITICAL_SERVICES[@]} containers)"

# Gate 2: backend logs sanity check
echo "  Verifying backend log sanity gate..."
BACKEND_LOG_TAIL=$(docker logs bnkscope-backend --tail 50 2>&1 || true)
if echo "$BACKEND_LOG_TAIL" | grep -E 'Traceback \(most recent call last\)|ModuleNotFoundError|ImportError|SyntaxError|ERROR: +Exception in ASGI application' >/dev/null 2>&1; then
    echo ""
    echo "##PHASE:failed"
    echo "ERROR: Backend logs contain fatal startup patterns."
    echo "  Check: docker logs bnkscope-backend --tail 200"
    exit 5
fi
echo "  ✓ Backend log sanity gate passed"

# Gate 3: health endpoint gate
echo "  Verifying health endpoint gate..."
HEALTH_RESPONSE=$(health_response)
if [ -z "$HEALTH_RESPONSE" ] || ! echo "$HEALTH_RESPONSE" | grep -q '"status":"healthy"'; then
    echo ""
    echo "##PHASE:failed"
    echo "ERROR: Health endpoint check failed after restart."
    echo "  Check: docker exec bnkscope-backend curl -s http://127.0.0.1:${API_PORT}/api/system/health"
    exit 5
fi
echo "  ✓ Health endpoint gate passed"

# ---------------------------------------------------------------------------
# Phase 4: Complete
# ---------------------------------------------------------------------------
echo ""
echo "##PHASE:complete"
echo "=================================="
echo "Upgrade complete!"
echo ""
NEW_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "  Version: ${OLD_VERSION} -> ${NEW_VERSION}"
echo "  Commit:  ${OLD_COMMIT} -> ${NEW_COMMIT}"
echo ""
ps_table
echo ""
echo "  All services healthy."
