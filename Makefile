# === bnkscope — Commands ===
# Usage: make deploy       — build + deploy (auto-detects Linux vs macOS networking)
#        make install      — first-time server setup (builds from scratch)
#        make update       — pull latest + rebuild + restart (keeps all data)
#        make test         — run all tests locally
#        make help         — see all commands
#
# Requires:
#   - Docker with BuildKit (default since Docker 23+)
#   - backend/.venv with dependencies installed (for local tests)
#   - frontend-v2/node_modules installed (for local tests)

SHELL := /bin/bash

# OPT-001: Ensure BuildKit is enabled for cache mount support
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# ─── Platform-aware compose command ──────────────────────────────────────────
# Auto-detects Linux vs macOS and picks the right networking:
#   Linux  → network_mode: host (services bind directly to host ports)
#   macOS  → bridge networking with port mappings (docker-compose.local.yml overlay)
#
# Grafana's admin password is a required variable in docker-compose.yml — it
# fails closed rather than shipping a default that is also in git. `bnkscope up`
# generates and persists one; a bare `make` target reads that, and falls back to
# a fresh random value so a direct compose call cannot resurrect a known
# password by accident.
export BNKSCOPE_GRAFANA_PASSWORD ?= $(shell cat $(HOME)/.config/bnkscope/grafana-admin-password 2>/dev/null || python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
#
# SAFETY: Running bridge networking on Linux creates iptables rules that can
# kill SSH connections permanently when net.bridge.bridge-nf-call-iptables = 1
# (the default on most distros). Requires BMC/IPMI reset to recover.
UNAME_S := $(shell uname -s)
# WSL2 reports "Linux" but runs Docker Desktop, which behaves like macOS for
# networking — host-mode containers bind inside the docker-desktop WSL2 distro,
# not the user's distro, so the local overlay (bridge + published ports) is
# what makes a Vite dev server reach the backend.
IS_WSL := $(shell grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null && echo 1)
ifeq ($(UNAME_S),Darwin)
  COMPOSE := docker compose -f docker-compose.yml -f docker-compose.local.yml
else ifeq ($(IS_WSL),1)
  COMPOSE := docker compose -f docker-compose.yml -f docker-compose.local.yml
else
  COMPOSE := docker compose
endif

# ─── CI / Local differentiation ─────────────────────────────────────────────
# GitHub Actions sets CI=true automatically. These variables control output
# format differences. The actual commands are identical in both contexts.

# Frontend commands run one of two ways. `FRONTEND_RUN` takes a single quoted
# command in both, so a target is written once:
#
#     $(FRONTEND_RUN) 'npx eslint .'
#
# Which way is decided by where node_modules actually is. `make` installs it
# into the tree; `scripts/bnkscope-verify-frontend.sh` keeps it in the
# `bnkscope-node` docker volume and mounts it over an **empty**
# `frontend-v2/node_modules`. That empty directory satisfies a directory
# prerequisite while providing no binaries, which is how every frontend target
# came to fail with `eslint: not found` while the verify script passed. So the
# test is for an installed binary, not for the directory.
FRONTEND_NODE_IMAGE := node:20-alpine
FRONTEND_NODE_VOLUME := bnkscope-node

# Same idea for shellcheck, decided on the binary rather than the layout:
# GitHub's runners ship it, most workstations do not, and a linter that is
# skipped because it is missing is a linter nobody runs. Read-only, so the
# container may stay root without leaving anything behind.
ifeq ($(shell command -v shellcheck 2>/dev/null),)
  SHELLCHECK := docker run --rm -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:stable
else
  SHELLCHECK := shellcheck
endif

ifdef CI
  # CI: XML artifacts for GitHub Actions upload. SUITE is set per-target below.
  PYTEST_COV_REPORT  = --cov-report=xml:coverage-$(SUITE).xml
  PYTEST_JUNIT       = --junitxml=junit-$(SUITE).xml
  BACKEND_VENV       :=
  BACKEND_VENV_ROOT  :=
  BACKEND_PREREQ     :=
  FRONTEND_PREREQ    :=
  FRONTEND_RUN       := cd frontend-v2 && sh -c
  FRONTEND_BUILD_CMD := npm run build
  FRONTEND_COVER_CMD := npm run test:coverage
else
  # Local: terminal output, venv activation
  PYTEST_COV_REPORT  := --cov-report=term-missing
  PYTEST_JUNIT       :=
  BACKEND_VENV       := source .venv/bin/activate &&
  BACKEND_VENV_ROOT  := source backend/.venv/bin/activate &&
  BACKEND_PREREQ     := | backend/.venv/bin/activate
ifeq ($(wildcard frontend-v2/node_modules/.bin/eslint),)
  # Deps are in the docker volume (or not installed yet). `frontend-deps` puts
  # them there; nothing is installed into the tree.
  FRONTEND_PREREQ    := | frontend-deps
  # NPM_CONFIG_UPDATE_NOTIFIER: npx prints an "update npm" banner on every run,
  # and pre-push shows each suite's last three lines — without this the banner
  # is all three of them and the test summary is what scrolls away.
  FRONTEND_RUN       := docker run --rm -e NPM_CONFIG_UPDATE_NOTIFIER=false \
                          -v "$(CURDIR)/frontend-v2:/app" \
                          -v $(FRONTEND_NODE_VOLUME):/app/node_modules \
                          -w /app $(FRONTEND_NODE_IMAGE) sh -c
  # The container runs as root, so anything it writes into the mounted tree
  # lands root-owned in the operator's checkout. Neither of these needs its
  # output kept, so both write inside the container instead.
  FRONTEND_BUILD_CMD := npx tsc && npx vite build --outDir /tmp/dist --emptyOutDir
  FRONTEND_COVER_CMD := npx vitest run --coverage --coverage.reportsDirectory=/tmp/coverage
else
  FRONTEND_PREREQ    := | frontend-v2/node_modules
  FRONTEND_RUN       := cd frontend-v2 && sh -c
  FRONTEND_BUILD_CMD := npm run build
  FRONTEND_COVER_CMD := npm run test:coverage
endif
endif

PYTEST_BASE = python -m pytest
# --cov enables coverage; --cov-fail-under=0 overrides pyproject.toml's fail_under
# so individual suite runs don't fail on partial coverage. The full suite
# coverage threshold is enforced by `make coverage-backend`.
PYTEST_COV  = --cov --cov-fail-under=0

.PHONY: install update status logs \
        test test-backend test-backend-unit test-backend-component test-backend-legacy test-frontend \
        test-contracts \
        test-integration test-integration-full build-frontend-check smoke-mcp-live mcp-readiness mcp-recreate \
        lint lint-backend lint-frontend shellcheck coverage quick-check pre-push push install-hooks setup-hooks \
        dev-setup security-audit docker-check docker-verify docker-validate frontend-deps \
        openapi openapi-types openapi-check openapi-types-check api-docs api-docs-check \
        openapi openapi-types openapi-check openapi-types-check typecheck-backend typecheck-frontend \
        build build-retry build-backend build-frontend build-all \
        up down restart deploy deploy-backend deploy-frontend upgrade-safe \
        clean clean-docker check-disk setup-cleanup-cron ensure-host-dirs \
        test-upgrade push-images buildx-setup publish-signed help

# ─── Quick Start Commands ────────────────────────────────────────────────────
#
# These are the main entry points for users:
#   make install  — first-time setup (builds everything from scratch)
#   make update   — pull latest + rebuild + restart (keeps all data)
#   make status   — show container health and versions
#

# First-time installation: clean slate, build, configure, start
# This is the only entry point for new installations. No separate scripts.
install: _install-clean _install-override _install-build _install-start _install-info

# --- Install sub-targets (not meant to be called directly) ---

_install-clean:
	@echo ""
	@echo "========================================="
	@echo "  bnkscope — First-Time Installation"
	@echo "========================================="
	@echo ""
	@echo "Stopping and removing existing containers..."
	@docker compose down 2>/dev/null || true
	@echo "Removing existing volumes..."
	@docker volume ls -q | grep bnkscope | xargs docker volume rm 2>/dev/null || echo "  No volumes to remove"
	@echo "Removing existing images..."
	@docker images | grep bnkscope | awk '{print $$1":"$$2}' | xargs docker rmi 2>/dev/null || echo "  No images to remove"

_install-override:
	@echo ""
	@echo "Configuring GUI Upgrade..."
	@printf '%s\n' \
		'# Auto-generated by make install — enables GUI Upgrade feature' \
		'# SEC-004: Docker socket grants full Docker daemon access (root-equivalent).' \
		'# Remove this file if you do not need the GUI "Upgrade Now" button.' \
		'' \
		'services:' \
		'  backend:' \
		'    environment:' \
		'      HOST_REPO_PATH: $(CURDIR)' \
		'    volumes:' \
		'      - /var/run/docker.sock:/var/run/docker.sock' \
		> docker-compose.override.yml
	@echo "  HOST_REPO_PATH=$(CURDIR)"
	@echo "  ✓ Created docker-compose.override.yml"

_install-build:
	@echo ""
	@echo "Building images (first build: ~3 min, cached: ~30s)..."
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose build

# The database is a SQLite file the backend creates on the data volume, and
# the schema comes from the ORM models at startup — there is no server to wait
# for and no migration to run. Both volumes are pre-created here only so the
# container's non-root user owns them: Docker creates a bind-less volume as
# root, and the backend cannot write its key file into a root-owned directory.
_install-start: ensure-host-dirs
	@echo ""
	@echo "Fixing volume permissions..."
	@PROJECT=$$(basename "$(CURDIR)"); \
	for v in bnkscope-data bnkscope-keys; do \
	  docker volume create \
	    --label com.docker.compose.project=$${PROJECT} \
	    --label com.docker.compose.volume=$${v} \
	    "$${PROJECT}_$${v}" >/dev/null; \
	done; \
	docker run --rm \
	  -v "$${PROJECT}_bnkscope-data:/app/data" \
	  -v "$${PROJECT}_bnkscope-keys:/app/keys" \
	  alpine:latest sh -c "chown -R 1000:1000 /app/data /app/keys" \
	  2>/dev/null && echo "  ✓ Volume permissions configured" \
	  || echo "  ⚠  Could not pre-configure permissions"
	@echo ""
	@echo "Starting services..."
	@docker compose up -d
	@echo ""
	$(call wait-healthy,12,5)

_install-info:
	@echo ""
	@docker compose ps
	@echo ""
	@echo "========================================="
	@echo "  ✅ Installation complete!"
	@echo ""
	@echo "  Version: $$(cat VERSION 2>/dev/null || echo 'unknown')"
	@echo ""
	@echo "  Open: http://localhost:8080"
	@echo ""
	@echo "  There is no login — bnkscope is a local tool and binds"
	@echo "  the API to 127.0.0.1 (see docker-compose.yml)."
	@echo ""
	@echo "  Next steps:"
	@echo "    1. Your kube contexts are discovered automatically"
	@echo "    2. Add any cluster not in ~/.kube/config from Clusters → Add"
	@echo "========================================="

# Pull latest code, rebuild, and restart (non-destructive — keeps all data)
update:
	@echo ""
	@echo "========================================="
	@echo "  bnkscope — Update"
	@echo "========================================="
	@echo ""
	@./upgrade.sh

# Show container health, versions, and service status
status:
	@echo ""
	@echo "========================================="
	@echo "  bnkscope — Status"
	@echo "========================================="
	@echo ""
	@echo "Version: $$(cat VERSION 2>/dev/null || echo 'unknown')"
	@echo "Commit:  $$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
	@echo ""
	@$(COMPOSE) ps 2>/dev/null || echo "Docker Compose not running"
	@echo ""
	@echo "Health check:"
	@curl -sf http://localhost:8000/api/system/health 2>/dev/null | python3 -m json.tool 2>/dev/null \
		|| curl -sf https://localhost:8443/api/system/health -k 2>/dev/null | python3 -m json.tool 2>/dev/null \
		|| echo "  Backend not reachable (containers may not be running)"

# ─── Docker Build (OPT-001: cached builds) ──────────────────────────────────
#
# IMPORTANT: Do NOT use --no-cache for normal code changes!
# BuildKit caches pip/npm downloads across builds. Layer caching handles code.
# Only use `make build-clean` when requirements.txt or tool versions change.
#

# Build both app images — backend API and frontend
# OPT-002: Single docker compose build parallelizes independent stages via BuildKit
build:
	@echo ""
	@echo "=== Building all app images (parallel) ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose build backend frontend
	@echo ""
	@echo "========================================="
	@echo "  Build complete (cached)"
	@echo "========================================="

# Same as `build`, but retries on transient download failures. Use this for
# from-scratch builds on DLP-managed workstations: the github.com tool
# downloads use Docker `ADD` (see docs/adr/D-035), which has no built-in retry,
# so a transient CDN/TLS blip aborts the whole build. BuildKit's layer cache
# makes each retry cheap (only the failed layer re-runs). Tune with
# RETRY_ATTEMPTS / RETRY_DELAY, e.g. `make build-retry RETRY_ATTEMPTS=5`.
build-retry:
	@echo ""
	@echo "=== Building all app images (parallel, with retry) ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 ./scripts/retry.sh -- docker compose build backend frontend
	@echo ""
	@echo "========================================="
	@echo "  Build complete (cached)"
	@echo "========================================="

# Build just the API image (backend code changes)
build-backend:
	@echo ""
	@echo "=== Building backend (API) ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 $(COMPOSE) build backend
	@echo "  ✓ Backend image built"

# Build just the frontend image
build-frontend:
	@echo ""
	@echo "=== Building frontend ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 $(COMPOSE) build frontend
	@echo "  ✓ Frontend image built"

# Build MCP server image
build-mcp:
	@echo ""
	@echo "=== Building MCP server ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose build mcp
	@echo "  ✓ MCP server image built"

# Build ALL images (backend API + frontend + the optional MCP profile)
build-all:
	@echo ""
	@echo "=== Building ALL images ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose build
	@echo "  ✓ All images built"

# Force rebuild without cache (only for requirements.txt / tool version changes)
build-clean:
	@echo ""
	@echo "=== Clean rebuild (no cache) — this will take several minutes ==="
	BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker compose build --no-cache
	@echo "  ✓ Clean rebuild complete"

# ─── Docker Deploy (build + restart + verify) ───────────────────────────────
#
# All deploy/runtime targets use $(COMPOSE) which auto-detects:
#   Linux  → host networking (docker compose)
#   macOS  → bridge networking (docker compose -f ... -f docker-compose.local.yml)

# Reusable health-check: polls backend /api/system/health.
# Usage: $(call wait-healthy,ATTEMPTS,SLEEP_SECONDS)
#   e.g. $(call wait-healthy,12,5)  → 12 attempts, 5s apart (60s max)
define wait-healthy
	@echo "=== Waiting for health checks... ==="
	@sleep $(2)
	@for i in $$(seq 1 $(1)); do \
	  if curl -sf http://localhost:8000/api/system/health > /dev/null 2>&1; then \
	    echo "  ✓ Backend healthy"; \
	    break; \
	  fi; \
	  if [ "$$i" = "$(1)" ]; then \
	    echo "  ⚠  Backend did not become healthy within $$(( $(1) * $(2) ))s"; \
	    echo "  Check logs: docker logs bnkscope-backend"; \
	  else \
	    echo "  Waiting... ($$i/$(1))"; \
	  fi; \
	  sleep $(2); \
	done
endef

# Deploy everything: build, restart, verify health
# NOTE: No explicit service list — starts ALL services in the compose file
# (the mcp service is behind a profile, so it only joins when asked for).
deploy: build ensure-host-dirs
	@echo ""
	@echo "=== Restarting containers ==="
	$(COMPOSE) up -d --force-recreate
	@echo ""
	$(call wait-healthy,12,5)
	@echo ""
	@$(COMPOSE) ps
	@echo ""
	date
	@echo ""
	@echo "========================================="
	@echo "  Deploy complete"
	@echo ""
ifeq ($(UNAME_S),Darwin)
	@echo "  Open:  https://localhost"
	@echo "  Login: admin  (initial password: DEFAULT_ADMIN_PASSWORD, default 'changeme'; change on first login)"
endif
	@echo "  Recommended next step: make mcp-readiness"
	@echo "========================================="

# Deploy just the backend — most common for backend code changes
deploy-backend: build-backend ensure-host-dirs
	@echo ""
	@echo "=== Restarting the backend container ==="
	$(COMPOSE) up -d --force-recreate backend
	@echo ""
	date
	@echo ""
	$(call wait-healthy,6,5)

# Deploy just frontend
deploy-frontend: build-frontend
	@echo ""
	@echo "=== Restarting frontend ==="
	$(COMPOSE) up -d --force-recreate frontend

# Run strict safe upgrade flow (preflight + upgrade + verification)
upgrade-safe:
	@echo ""
	@echo "=== Running safe upgrade flow (upgrade.sh --local) ==="
	@echo "  Includes git/disk preflight and strict verification gates."
	@./upgrade.sh --local

# Test upgrade policy guards (runs in isolated temp repo)
test-upgrade:
	@echo ""
	@echo "=== Testing upgrade.sh policy guards ==="
	@./scripts/test-upgrade-policy.sh

# ShellCheck lint for all shell scripts
shellcheck:
	@echo ""
	@echo "=== ShellCheck: linting shell scripts ==="
	@$(SHELLCHECK) --severity=warning bnkscope upgrade.sh scripts/*.sh

# Convenience: start/stop/restart all (platform-aware)
# Docker creates a missing bind-mount source as a root-owned directory in the
# user's home. The backend mounts ~/.kube, ~/.aws and ~/.config/gcloud
# read-only (it reads the operator's own clusters and credentials from them),
# and not everyone has all three -- so create them here, as the user, before
# compose gets the chance to create them as root.
ensure-host-dirs:
	@mkdir -p "$${HOME}/.kube" "$${HOME}/.aws" "$${HOME}/.config/gcloud" "$${HOME}/.config/tmmscope"

# The lifecycle targets defer to ./bnkscope rather than driving compose.
#
# `$(COMPOSE) up -d` looked equivalent and was not: compose interpolates
# `${BNKSCOPE_GRAFANA_PASSWORD:?...}` on every invocation, so it failed before
# starting anything, and it also skipped port negotiation, the UI bind, the
# telemetry profile and the host-directory creation that the CLI does. The CLI
# is the supported entry point; there is no second implementation of it here.
up:
	@./bnkscope up

down:
	@./bnkscope down

restart:
	@./bnkscope down && ./bnkscope up

logs:
	@./bnkscope logs

# ─── Default: run all tests ─────────────────────────────────────────────────

test: lint test-backend test-frontend
	@echo ""
	@echo "========================================="
	@echo "  All tests passed"
	@echo "========================================="

# ─── Individual test suites ──────────────────────────────────────────────────

test-backend: SUITE = backend
test-backend: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Tests ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/ --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

test-frontend: $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Frontend Tests ==="
	@$(FRONTEND_RUN) 'npx vitest run'

test-mcp:
	@echo ""
	@echo "=== MCP Server Tests ==="
	@cd mcp-server && \
	  if [ -d ".venv" ]; then source .venv/bin/activate; fi && \
	  python -m pytest tests/ --tb=short -q

smoke-mcp-live:
	@echo ""
	@echo "=== MCP Live Smoke Validation ==="
	@echo "  NOTE: ping/tools-list reachability != runtime readiness; tool calls require valid MCP backend credentials."
	@echo "  Configure MCP_USERNAME/MCP_PASSWORD if backend admin password was rotated."
	@python3 scripts/mcp_live_smoke.py --mcp-url "$${MCP_SMOKE_URL:-http://localhost:8081/mcp}" $${MCP_SMOKE_INSECURE_TLS:+--insecure-tls}

mcp-readiness:
	@echo ""
	@echo "=== MCP Readiness Check (Liveness + Runtime) ==="
	@echo "  Layer 1: container liveness (protocol ping healthcheck)"
	@state=$$(docker inspect -f '{{.State.Status}}' bnkscope-mcp 2>/dev/null) || (echo "  ERROR: bnkscope-mcp container not found. Start stack first (make deploy)." && exit 1); \
	health=$$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' bnkscope-mcp 2>/dev/null); \
	echo "  bnkscope-mcp: state=$$state health=$$health"; \
	if [ "$$state" != "running" ]; then \
		echo "  ERROR: MCP container is not running."; \
		exit 1; \
	fi; \
	if [ "$$health" != "none" ] && [ "$$health" != "healthy" ]; then \
		echo "  ERROR: MCP protocol liveness healthcheck is not healthy."; \
		exit 1; \
	fi
	@echo "  Layer 2: runtime readiness (governed tool calls via smoke-mcp-live)"
	@$(MAKE) --no-print-directory smoke-mcp-live

mcp-recreate:
	@echo ""
	@echo "=== Recreate MCP service ==="
	@echo "  Use after MCP_USERNAME/MCP_PASSWORD changes so MCP picks up new credentials."
	@$(COMPOSE) up -d --force-recreate --no-deps mcp
	@$(COMPOSE) ps mcp

test-backend-unit: SUITE = unit
test-backend-unit: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Unit Tests ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/unit/ --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

test-backend-component: SUITE = component
test-backend-component: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Component Tests ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/component/ --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

test-contracts: SUITE = contract
test-contracts: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Golden Contract Tests ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/contract/ -v --tb=short $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

# Exact complement of test-integration-full: together they cover every test in
# tests/integration/. The selector is spelled out rather than inherited from
# pyproject's addopts (-m 'not full') on purpose -- that implicit coupling is
# what let the two targets stop being complements without anyone noticing
# (#130). Change one selector, change the other.
test-integration: SUITE = integration
test-integration: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Integration Tests (non-full marker set) ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/integration/ -m 'not full' --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

# SUITE is integration-full, not integration: the artifact filenames are derived
# from it, and CI now runs both targets in one job.
test-integration-full: SUITE = integration-full
test-integration-full: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Full-Mode Integration Tests (requires running Docker stack) ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/integration/ -m full --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

# ─── Linting ─────────────────────────────────────────────────────────────────

lint: lint-backend lint-frontend
	@echo ""
	@echo "=== All linting passed ==="

lint-backend: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Lint (ruff) ==="
	@cd backend && $(BACKEND_VENV) \
	  python -m ruff check . --config pyproject.toml

lint-frontend: $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Frontend Lint (eslint) ==="
	@set -o pipefail && $(FRONTEND_RUN) 'npx eslint .' 2>&1 | tail -30

# ─── Coverage ────────────────────────────────────────────────────────────────

coverage: coverage-backend coverage-frontend
	@echo ""
	@echo "=== Coverage reports complete ==="

coverage-backend: | backend/.venv/bin/activate
	@echo ""
	@echo "=== Backend Coverage ==="
	@cd backend && source .venv/bin/activate && \
	  python -m pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=40 --tb=short -q

coverage-frontend: $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Frontend Coverage ==="
	@$(FRONTEND_RUN) '$(FRONTEND_COVER_CMD)'

# ─── Pre-Push & Push (local checks → push → verify CI) ──────────────────────

typecheck-backend: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Type Check (mypy core/ schemas/) ==="
	@cd backend && $(BACKEND_VENV) \
	  python -m mypy core/ schemas/ --config-file pyproject.toml

typecheck-frontend: $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== TypeScript Type Check (tsc --noEmit) ==="
	@$(FRONTEND_RUN) 'npx tsc --noEmit'

test-backend-legacy: SUITE = legacy
test-backend-legacy: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Backend Legacy Tests (flat test_*.py files) ==="
	@cd backend && $(BACKEND_VENV) \
	  $(PYTEST_BASE) tests/ \
	    --ignore=tests/unit \
	    --ignore=tests/component \
	    --ignore=tests/integration \
	    --ignore=tests/contract \
	    --tb=short -q $(PYTEST_COV) $(PYTEST_COV_REPORT) $(PYTEST_JUNIT)

build-frontend-check: $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Frontend Build Check ==="
	@$(FRONTEND_RUN) '$(FRONTEND_BUILD_CMD)' > /dev/null 2>&1 && echo "  Build succeeded ✓"

# ── Quick check (~15s): lint + types + contracts ────────────────────────────
# Run before every commit. Catches most CI failures instantly.
quick-check: lint typecheck-backend openapi-types-check api-docs-check
	@echo ""
	@echo "========================================="
	@echo "  Quick check passed (~15s)"
	@echo "========================================="

# ── Pre-push (~90s parallel): mirrors ALL CI jobs ───────────────────────────
# Run once before git push. Runs test suites in parallel for speed.
# Prerequisite: quick-check runs first (sequential), then tests fan out.
pre-push: quick-check
	@echo ""
	@echo "=== Running all test suites in parallel... ==="
	@failed=""; \
	( set -o pipefail; make test-backend-unit 2>&1 | tail -3 ) & pid1=$$!; \
	( set -o pipefail; make test-backend-component 2>&1 | tail -3 ) & pid2=$$!; \
	( set -o pipefail; make test-backend-legacy 2>&1 | tail -3 ) & pid3=$$!; \
	( set -o pipefail; make test-frontend 2>&1 | tail -3 ) & pid4=$$!; \
	( set -o pipefail; make typecheck-frontend 2>&1 | tail -3 ) & pid5=$$!; \
	( set -o pipefail; make test-contracts 2>&1 | tail -3 ) & pid6=$$!; \
	wait $$pid1 || failed="$$failed backend-unit"; \
	wait $$pid2 || failed="$$failed backend-component"; \
	wait $$pid3 || failed="$$failed backend-legacy"; \
	wait $$pid4 || failed="$$failed frontend"; \
	wait $$pid5 || failed="$$failed tsc"; \
	wait $$pid6 || failed="$$failed contracts"; \
	if [ -n "$$failed" ]; then \
	  echo ""; \
	  echo "========================================="; \
	  echo "  FAILED:$$failed"; \
	  echo "========================================="; \
	  exit 1; \
	fi
	@echo ""
	@echo "========================================="
	@echo "  Pre-push checks passed — safe to push"
	@echo "========================================="

# How long to wait for GitHub to create a run for the commit just pushed.
# A fixed `sleep 10` was not enough on its own: Actions normally lags a few
# seconds, and can be down entirely for minutes.
CI_WAIT_SECONDS ?= 90

# Watch the run for *this* commit, and say which of the three things happened.
#
# `gh run watch` with no argument needs a TTY to show its picker — under `make`
# it exits with a usage error, which the old `&& ... || ...` read as a failed
# build. So a push during an Actions outage printed "CI RED — check failures",
# naming a build that had never started. Report "did not run" as its own
# outcome: it is not green, and it is not a red build either.
push: pre-push
	@echo ""
	@echo "=== Pushing to origin ==="
	@git push
	@sha=$$(git rev-parse HEAD); \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	echo ""; \
	if ! command -v gh >/dev/null 2>&1; then \
	  echo "  Pushed $$sha. gh is not installed, so CI status is unknown."; \
	  exit 0; \
	fi; \
	if [ "$$branch" = "HEAD" ]; then branch_flag=""; else branch_flag="--branch $$branch"; fi; \
	echo "=== Waiting up to $(CI_WAIT_SECONDS)s for CI to start on $$sha ==="; \
	run=""; waited=0; \
	while [ $$waited -lt $(CI_WAIT_SECONDS) ]; do \
	  run=$$(gh run list $$branch_flag --limit 20 --json databaseId,headSha \
	          --jq "map(select(.headSha==\"$$sha\")) | .[0].databaseId // empty" \
	         2>/dev/null); \
	  [ -n "$$run" ] && break; \
	  sleep 5; waited=$$((waited + 5)); \
	done; \
	if [ -z "$$run" ]; then \
	  echo ""; \
	  echo "========================================="; \
	  echo "  CI DID NOT RUN — nothing to watch"; \
	  echo "========================================="; \
	  echo "  Pushed $$sha, but GitHub created no run for it within"; \
	  echo "  $(CI_WAIT_SECONDS)s. The push landed; the build is UNVERIFIED."; \
	  echo ""; \
	  echo "  Usual causes:"; \
	  echo "    - Actions is degraded — https://www.githubstatus.com"; \
	  echo "    - every changed path is in the workflow's paths-ignore"; \
	  echo "    - Actions is disabled for this repo"; \
	  echo ""; \
	  echo "  Check again later:  gh run list $$branch_flag"; \
	  echo "  Or wait longer:     make push CI_WAIT_SECONDS=300"; \
	  exit 1; \
	fi; \
	echo "=== Watching run $$run (this may take a few minutes)... ==="; \
	if gh run watch "$$run" --exit-status; then \
	  echo ""; \
	  echo "========================================="; \
	  echo "  CI GREEN — all checks passed"; \
	  echo "========================================="; \
	else \
	  echo ""; \
	  echo "========================================="; \
	  echo "  CI RED — inspect with: gh run view $$run --log-failed"; \
	  echo "========================================="; \
	  exit 1; \
	fi

# ─── Containerized Tests (no local venv / Node needed) ──────────────────────
# Run tests and linting inside Docker images — matches CI Python 3.11 / Node 20
# exactly, sidesteps local venv drift (e.g. Python 3.14 on macOS).
#
# Usage:
#   make test-docker              — run all containerized tests
#   make test-backend-docker      — backend pytest in python:3.11 container
#   make test-frontend-docker     — frontend vitest in node:20 container
#   make lint-backend-docker      — ruff in container
#
# Source is bind-mounted so edits take effect immediately (no rebuild).

BACKEND_TEST_IMAGE  := bnkscope-backend-test
FRONTEND_RUN_IMAGE  := node:20-slim
DOCKER_RUN_FLAGS    := --rm -v $(CURDIR):/repo -w /repo

.PHONY: test-docker test-backend-docker test-frontend-docker \
        lint-backend-docker build-test-images

test-docker: lint-backend-docker test-backend-docker test-frontend-docker
	@echo ""
	@echo "========================================="
	@echo "  All containerized tests passed"
	@echo "========================================="

build-test-images: .stamp/backend-test-image

# VERSION is a prerequisite because the image now COPYs it — without this a
# version bump leaves a stale test image reporting the old number.
.stamp/backend-test-image: backend/Dockerfile backend/requirements.txt backend/requirements-dev.txt VERSION
	@mkdir -p .stamp
	@echo ""
	@echo "=== Building backend test image ($(BACKEND_TEST_IMAGE)) ==="
	docker build --target test -f backend/Dockerfile -t $(BACKEND_TEST_IMAGE) .
	@touch $@

test-backend-docker: .stamp/backend-test-image
	@echo ""
	@echo "=== Backend Tests (docker) ==="
	docker run $(DOCKER_RUN_FLAGS) -w /repo/backend $(BACKEND_TEST_IMAGE) \
	  python -m pytest tests/ --tb=short -q

lint-backend-docker: .stamp/backend-test-image
	@echo ""
	@echo "=== Backend Lint (ruff, docker) ==="
	docker run $(DOCKER_RUN_FLAGS) -w /repo/backend $(BACKEND_TEST_IMAGE) \
	  python -m ruff check . --config pyproject.toml

# Frontend: use stock node image + named volume for node_modules cache.
# First run does npm ci (~30s), subsequent runs reuse the volume (~0s).
test-frontend-docker:
	@echo ""
	@echo "=== Frontend Tests (docker) ==="
	docker run $(DOCKER_RUN_FLAGS) \
	  -v bnkscope-fe-node_modules:/repo/frontend-v2/node_modules \
	  -w /repo/frontend-v2 $(FRONTEND_RUN_IMAGE) \
	  sh -c '[ -f node_modules/.package-lock.json ] || npm ci; npm test -- --run'

# ─── Dev Environment Setup ───────────────────────────────────────────────────
# Creates local Python virtualenvs and installs frontend deps needed by the
# lint/test targets. File targets are idempotent — re-running is a no-op once
# the stamps exist. Delete the target path to force a rebuild.

dev-setup: backend/.venv/bin/activate frontend-v2/node_modules
	@echo ""
	@echo "=== Dev environment ready ==="
	@echo "  backend/.venv        ✓"
	@echo "  frontend-v2/node_modules ✓"

backend/.venv/bin/activate: backend/requirements.txt backend/requirements-dev.txt
	@echo ""
	@echo "=== Creating backend/.venv ==="
	@cd backend && (python3.11 -m venv .venv || python3 -m venv .venv) && \
	  .venv/bin/pip install --upgrade pip && \
	  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
	@touch $@

frontend-v2/node_modules: frontend-v2/package.json frontend-v2/package-lock.json
	@echo ""
	@echo "=== Installing frontend-v2 dependencies ==="
	@cd frontend-v2 && npm ci
	@touch $@

# Same dependencies, in the docker volume the verify scripts share. Cheap to
# re-check (one container start) and it is the only thing that makes the
# volume self-installing, so a fresh clone needs no separate bootstrap step.
frontend-deps:
	@docker volume create $(FRONTEND_NODE_VOLUME) >/dev/null
	@docker run --rm -v "$(CURDIR)/frontend-v2:/app" \
	  -v $(FRONTEND_NODE_VOLUME):/app/node_modules -w /app $(FRONTEND_NODE_IMAGE) \
	  sh -c '[ -x node_modules/.bin/eslint ] || { \
	    echo "=== Installing frontend-v2 dependencies (docker volume) ==="; \
	    npm ci --no-audit --no-fund; }'

# ─── Git Hooks ───────────────────────────────────────────────────────────────

install-hooks:
	@echo "Installing git hooks..."
	@mkdir -p .git/hooks
	@cp .githooks/pre-commit .git/hooks/pre-commit
	@cp .githooks/pre-push .git/hooks/pre-push
	@chmod +x .git/hooks/pre-commit .git/hooks/pre-push
	@echo "Git hooks installed:"
	@echo "  pre-commit: lint on every commit (~5-10s)"
	@echo "  pre-push:   lint + unit + component + frontend tests (~2-3m)"

setup-hooks: ## Configure git to use project hooks (.githooks/)
	git config core.hooksPath .githooks
	@echo "Git hooks installed — pre-commit and pre-push checks active"

# ─── OpenAPI & Type Generation ───────────────────────────────────────────────

openapi: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Generating OpenAPI spec ==="
	@$(BACKEND_VENV_ROOT) python scripts/generate-openapi.py

openapi-types: openapi $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Generating TypeScript types from OpenAPI spec ==="
	@cd frontend-v2 && npx openapi-typescript ../backend/openapi.json -o src/types/api-generated.ts

api-docs: openapi
	@echo ""
	@echo "=== Generating docs/API_REFERENCE.md ==="
	@$(BACKEND_VENV_ROOT) python scripts/gen-api-reference.py

api-docs-check: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Checking API_REFERENCE.md freshness ==="
	@$(BACKEND_VENV_ROOT) python scripts/gen-api-reference.py --check

openapi-check: $(BACKEND_PREREQ)
	@echo ""
	@echo "=== Checking OpenAPI spec freshness ==="
	@$(BACKEND_VENV_ROOT) python scripts/generate-openapi.py --check

openapi-types-check: openapi-check $(FRONTEND_PREREQ)
	@echo ""
	@echo "=== Checking TypeScript generated types freshness ==="
	@cd frontend-v2 && npx openapi-typescript ../backend/openapi.json -o src/types/api-generated-check.ts 2>/dev/null
	@if ! diff -q frontend-v2/src/types/api-generated.ts frontend-v2/src/types/api-generated-check.ts > /dev/null 2>&1; then \
	  rm frontend-v2/src/types/api-generated-check.ts; \
	  echo ""; \
	  echo "ERROR: Generated TypeScript types are stale."; \
	  echo "Run: make openapi-types"; \
	  echo ""; \
	  exit 1; \
	fi
	@rm frontend-v2/src/types/api-generated-check.ts
	@echo "  Generated types are up to date ✓"

# ─── Help ────────────────────────────────────────────────────────────────────

help:
	@echo "bnkscope — Commands"
	@echo ""
	@echo "  All deploy/runtime targets auto-detect your platform:"
	@echo "    Linux  → host networking (services bind directly to host ports)"
	@echo "    macOS  → bridge networking via Docker Desktop (port mappings)"
	@echo ""
	@echo "Getting Started"
	@echo "  make dev-setup             Create backend venv + install frontend deps (for local tests/lint)"
	@echo "  make install               First-time server setup (builds everything from scratch)"
	@echo "  make update                Pull latest + rebuild + restart (keeps all data)"
	@echo "  make status                Show container health and versions"
	@echo ""
	@echo "Docker Build (cached builds)"
	@echo "  make build                 Build all app images in parallel (~30s cached, ~3min first time)"
	@echo "  make build-backend         Build backend API image only"
	@echo "  make build-frontend        Build frontend image only"
	@echo "  make build-all             Build ALL images (api + frontend + mcp)"
	@echo "  make build-clean           Force rebuild without cache (only for deps/tool changes)"
	@echo "  make docker-verify         Verify baked VERSION + MCP module in built images"
	@echo "  make docker-validate       Full Docker validation (build + size + tool verification)"
	@echo ""
	@echo "Deploy (platform-aware)"
	@echo "  make deploy                Build + restart all containers + verify health"
	@echo "  make deploy-backend        Build + restart backend containers only"
	@echo "  make deploy-frontend       Build + restart frontend only"
	@echo "  make up                    Start all containers"
	@echo "  make down                  Stop all containers"
	@echo "  make restart               Restart all containers"
	@echo "  make logs                  Tail all container logs"
	@echo "  make upgrade-safe          Run strict preflight + upgrade + verification gates"
	@echo "  make test-upgrade          Test upgrade.sh policy guards (isolated temp repo)"
	@echo "  make shellcheck            Lint all shell scripts with ShellCheck"
	@echo ""
	@echo "Testing"
	@echo "  make test                  Run all tests (lint + backend + frontend)"
	@echo "  make test-docker           Run all tests inside containers (no local venv/node needed)"
	@echo "  make test-backend-docker   Backend pytest in python:3.11 container"
	@echo "  make test-frontend-docker  Frontend vitest in node:20 container"
	@echo "  make lint-backend-docker   Ruff in python:3.11 container"
	@echo "  make test-backend          Run backend tests only (pytest)"
	@echo "  make test-backend-unit     Run backend unit tests only (tests/unit/)"
	@echo "  make test-backend-component Run backend component tests only (tests/component/)"
	@echo "  make test-backend-legacy   Run backend legacy tests (flat test_*.py files)"
	@echo "  make test-frontend         Run frontend tests only (vitest)"
	@echo "  make build-frontend-check  Verify frontend builds successfully"
	@echo "  make test-contracts        Run golden contract tests (response shape verification)"
	@echo "  make test-integration    Run integration tests (default marker set)"
	@echo "  make test-integration-full Run full-mode integration tests (requires Docker stack)"
	@echo ""
	@echo "Linting & Type Checking"
	@echo "  make lint                  Run all linters (ruff + eslint)"
	@echo "  make lint-backend          Run backend linter only (ruff)"
	@echo "  make lint-frontend         Run frontend linter only (eslint)"
	@echo "  make coverage              Run tests with coverage reporting"
	@echo "  make typecheck-backend     Run mypy on core/ schemas/"
	@echo "  make typecheck-frontend    Run tsc --noEmit"
	@echo ""
	@echo "CI & Push"
	@echo "  make quick-check           Fast check (~15s): lint + mypy + openapi types"
	@echo "  make pre-push              Full CI mirror (~90s parallel): quick-check + all tests"
	@echo "  make push                  Run checks, push, then verify CI is green"
	@echo ""
	@echo "Code Generation"
	@echo "  make openapi               Generate OpenAPI spec (backend/openapi.json)"
	@echo "  make openapi-types         Generate OpenAPI spec + TypeScript types"
	@echo "  make openapi-check         Check if committed OpenAPI spec is stale"
	@echo "  make install-hooks         Install pre-commit and pre-push git hooks"
	@echo ""
	@echo "MCP Server"
	@echo "  make build-mcp             Build MCP server Docker image"
	@echo "  make test-mcp              Run MCP server tests (pytest)"
	@echo "  make smoke-mcp-live        Run bounded live MCP runtime smoke checks"
	@echo "  make mcp-readiness         Run MCP liveness + runtime readiness checks"
	@echo "  make mcp-recreate          Recreate MCP service after credential changes"
	@echo ""
	@echo "Distribution & Registry (Multi-Arch)"
	@echo "  make buildx-setup          Set up multi-arch builder with QEMU (one-time)"
	@echo "  make push-images           Build + push multi-arch images (amd64 + arm64)"
	@echo ""
	@echo "Disk & Cleanup"
	@echo "  make check-disk            Check disk space (warns if > 70%, fails if > 85%)"
	@echo "  make clean-docker          Remove dangling images + build cache > 7 days"
	@echo "  make setup-cleanup-cron    Install weekly cleanup cron job (Sunday 2 AM)"
	@echo ""
	@echo "  make help                  Show this help"
buildx-setup:
	@echo ""
	@echo "========================================="
	@echo "  Setting up multi-arch buildx builder"
	@echo "========================================="
	@echo ""
	@echo "=== Registering QEMU emulators ==="
	@if docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -q "Docker Desktop"; then \
	  echo "  Docker Desktop detected — using its built-in emulation; skipping QEMU --reset (it corrupts binfmt)"; \
	else \
	  docker run --rm --privileged multiarch/qemu-user-static --reset -p yes 2>/dev/null \
	    || docker run --rm --privileged tonistiigi/binfmt --install all 2>/dev/null \
	    || echo "  ⚠  QEMU setup skipped (may already be configured)"; \
	fi
	@echo ""
	@echo "=== Creating buildx builder: $(BUILDX_BUILDER) ==="
	@if docker buildx inspect $(BUILDX_BUILDER) > /dev/null 2>&1; then \
	  echo "  Builder '$(BUILDX_BUILDER)' already exists — reusing"; \
	else \
	  docker buildx create --name $(BUILDX_BUILDER) \
	    --driver docker-container \
	    --platform linux/amd64,linux/arm64 \
	    --bootstrap; \
	  echo "  ✓ Builder '$(BUILDX_BUILDER)' created"; \
	fi
	@echo ""
	@docker buildx inspect $(BUILDX_BUILDER) | head -10
	@echo ""
	@echo "  ✓ Multi-arch builder ready"
	@echo "  Supported platforms:"
	@docker buildx inspect $(BUILDX_BUILDER) --bootstrap 2>/dev/null | grep -oP 'linux/\w+' | sort -u | sed 's/^/    /'

# Push multi-arch images to a container registry
# Usage: make push-images BNKSCOPE_REGISTRY=ghcr.io/your-org
push-images:
	@echo ""
	@echo "========================================="
	@echo "  bnkscope — Multi-Arch Push to Registry"
	@echo "========================================="
	@if [ -z "$${BNKSCOPE_REGISTRY:-}" ]; then \
	  echo "ERROR: BNKSCOPE_REGISTRY is not set."; \
	  echo ""; \
	  echo "Usage: make push-images BNKSCOPE_REGISTRY=ghcr.io/your-org"; \
	  echo "       make push-images BNKSCOPE_REGISTRY=ghcr.io/your-org PLATFORMS=linux/amd64"; \
	  exit 1; \
	fi
	@if ! docker buildx inspect $(BUILDX_BUILDER) > /dev/null 2>&1; then \
	  echo ""; \
	  echo "ERROR: Buildx builder '$(BUILDX_BUILDER)' not found."; \
	  echo "Run first: make buildx-setup"; \
	  exit 1; \
	fi
	@VERSION=$$(cat VERSION); \
	REGISTRY=$${BNKSCOPE_REGISTRY}; \
	echo "  Registry:  $$REGISTRY"; \
	echo "  Version:   $$VERSION"; \
	echo "  Platforms: $(PLATFORMS)"; \
	echo "  Builder:   $(BUILDX_BUILDER)"; \
	echo ""; \
	echo "=== Building + pushing all images in parallel (docker buildx bake) ==="; \
	GIT_REVISION=$$(git rev-parse HEAD 2>/dev/null || echo unknown); \
	REGISTRY=$$REGISTRY VERSION=$$VERSION PLATFORMS=$(PLATFORMS) GIT_REVISION=$$GIT_REVISION \
	  docker buildx bake --builder $(BUILDX_BUILDER) --push && \
	echo ""; \
	echo "========================================="; \
	echo "  ✅ All images pushed to $$REGISTRY"; \
	echo "  Tags:      $$VERSION, latest"; \
	echo "  Platforms: $(PLATFORMS)"; \
	echo ""; \
	echo "  Verify manifests:"; \
	echo "    docker manifest inspect $${REGISTRY}/bnkscope-api:$${VERSION}"; \
	echo "========================================="
publish-signed:
	@if [ -z "$${BNKSCOPE_REGISTRY:-}" ]; then \
	  echo "ERROR: BNKSCOPE_REGISTRY is not set."; \
	  echo "Usage: make publish-signed BNKSCOPE_REGISTRY=ghcr.io/your-org"; \
	  exit 1; \
	fi
	@if [ "$${SIGN_EXECUTE:-0}" = "1" ]; then \
	  BNKSCOPE_REGISTRY=$${BNKSCOPE_REGISTRY} DRY_RUN=0 bash scripts/publish-signed-images.sh --execute; \
	else \
	  BNKSCOPE_REGISTRY=$${BNKSCOPE_REGISTRY} bash scripts/publish-signed-images.sh --dry-run; \
	fi

# Verify Docker images have expected tools and modules (catches COPY/install regressions)
# Run after `make build` or `make build-clean` to validate images before deploy/push.
docker-verify:
	@echo ""
	@echo "=== Docker Image Verification ==="
	@echo ""
	@echo "--- Version baked into the image ---"
	@expected=$$(cat VERSION); \
	failed=0; \
	for img in bnkscope-api; do \
	  actual=$$(docker run --rm --entrypoint "" $$img:latest cat /app/VERSION 2>/dev/null || echo ""); \
	  if [ "$$actual" = "$$expected" ]; then \
	    echo "  OK    $$img reports $$actual"; \
	  else \
	    echo "  FAIL  $$img reports '$$actual', expected '$$expected'"; \
	    echo "        settings.VERSION falls back to 0.0.0 when /app/VERSION is absent,"; \
	    echo "        which surfaces on /api, the OpenAPI title and X-Bnkscope-Version."; \
	    failed=1; \
	  fi; \
	done; \
	[ $$failed -eq 0 ] || exit 1
	@echo ""
	@failed=0; \
	  echo "--- MCP server module ---"; \
	  if docker run --rm bnkscope-mcp:latest python -c "import bnk_forge_mcp.server; print('OK')" > /dev/null 2>&1; then \
	    echo "  OK    bnk_forge_mcp.server"; \
	  else \
	    echo "  FAIL  bnk_forge_mcp.server"; \
	    failed=1; \
	  fi; \
	  echo ""; \
	  if [ "$$failed" = "1" ]; then \
	    echo "ERROR: Docker image verification failed"; \
	    exit 1; \
	  fi
	@echo "=== Docker verification passed ==="

# ─── Security Audit ──────────────────────────────────────────────────────────
# Slice A / #300: real recipe bodies replacing the prior no-op stubs.
# Gate: pip-audit exits non-zero on HIGH+CRITICAL; npm audit gates on all deps (prod+dev) — #303.
# Requires pip-audit to be installed (CI installs it; locally: pip install pip-audit).
#
# PYSEC-2026-1325: ecdsa is a transitive dep of python-jose[cryptography]==3.5.0 (not bumped in this PR); no fix version available yet.
# (fastapi/starlette/paramiko CVEs previously deferred have been fixed by this PR's bumps.)
PIP_AUDIT_DEFER = --ignore-vuln PYSEC-2026-1325
security-audit:
	@echo ""
	@echo "=== Security Audit ==="
	@echo ""
	@echo "--- Python: backend ---"
	@pip-audit -r backend/requirements.txt --progress-spinner=off $(PIP_AUDIT_DEFER)
	@echo ""
	@echo "--- Python: mcp-server (pyproject.toml) ---"
	# PYSEC-2026-196 is the build-env pip itself (pip<26.1.2), not a project dependency.
	# PYSEC-2026-3447 is the build-env setuptools (<83.0.0), not a project dependency.
	@cd mcp-server && pip-audit --progress-spinner=off $(PIP_AUDIT_DEFER) --ignore-vuln PYSEC-2026-196 --ignore-vuln PYSEC-2026-3447
	@echo ""
	@echo "--- JavaScript: frontend-v2 (prod deps, HIGH+) ---"
	@cd frontend-v2 && npm audit --omit=dev --audit-level=high
	@echo "--- JavaScript: frontend-v2 (dev deps, CRITICAL only) ---"
	@cd frontend-v2 && npm audit --audit-level=critical
	@echo ""
	@echo "=== Security audit passed ==="

# Slice A / #300: real Dockerfile lint using BuildKit's built-in check call.
# Uses `docker buildx build --call=check` which is available in BuildKit >= 0.12
# (Docker Desktop >= 4.27). Exits non-zero on lint failures.
# Alternative: install hadolint and run over each Dockerfile.
docker-check:
	@echo ""
	@echo "=== Docker Check (BuildKit lint) ==="
	@failed=0; \
	  for target_spec in \
	    "backend/Dockerfile:." \
	    "frontend-v2/Dockerfile:." \
	    "mcp-server/Dockerfile:mcp-server"; do \
	    dockerfile=$${target_spec%%:*}; \
	    ctx=$${target_spec##*:}; \
	    echo "  Checking $$dockerfile ..."; \
	    if ! docker buildx build --call=check --file=$$dockerfile $$ctx 2>&1; then \
	      echo "  FAIL: $$dockerfile"; \
	      failed=1; \
	    fi; \
	  done; \
	  if [ "$$failed" = "1" ]; then \
	    echo ""; \
	    echo "ERROR: docker-check failed — fix Dockerfile warnings above"; \
	    exit 1; \
	  fi
	@echo "=== Docker check passed ==="

# Full Docker validation: build + size thresholds + tool/module verification
docker-validate: docker-check docker-verify

# ─── Disk Management & Cleanup ───────────────────────────────────────────────

# Check disk space before builds
check-disk:
	@./scripts/check-disk-space.sh

# Clean up Docker disk usage (safe — keeps running containers + recent cache)
clean-docker:
	@./scripts/docker-cleanup.sh

# Remove project-prefix volumes that compose has disowned (orphans).
# Detected by `make clean`; this target acts on them with a confirmation prompt.
clean-orphans:
	@./scripts/docker-clean-orphans.sh

# Alias for convenience
clean: clean-docker

# Install automated weekly cleanup
setup-cleanup-cron:
	@./scripts/setup-cleanup-cron.sh
