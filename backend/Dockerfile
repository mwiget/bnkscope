# syntax=docker/dockerfile:1
# =============================================================================
# BNK-Forge Backend — Multi-Target Dockerfile
# =============================================================================
#
# Builds role-specific images from a shared base:
#
#   docker build --target api    -t bnk-forge-api    backend/   (~300-400MB)
#
# Build args:
#
# Layer hierarchy:
#   python:3.11-slim → base (system deps + user)
#     → dependencies (pip install, cached)
#     → app-base (base + deps + app code)
#        ├── api  (uvicorn — no CLI tools)
#        └── test (app-base + pytest/ruff/mypy)
#
# PERFORMANCE NOTES:
#   - BuildKit cache mounts for pip survive across builds
#   - The CLI-tool download stage is gone (Phase 4); the image is Python only
#   - Use `docker compose build` (not --no-cache) for normal code changes


# =============================================================================
# Stage 1: BASE — Python runtime + system deps (shared by ALL targets)
# =============================================================================
# python:3.11-slim — digest-pinned (Slice B / #300); re-pin when bumping the tag.
# Pull-through cache prefix for the base image. Empty by default, so a plain
# `docker build` behaves exactly as before. `bnkscope up` sets it to the local
# regcachectl docker.io cache when that fleet is running, which stops a
# rebuilt-from-scratch stack re-pulling the same base layers from Docker Hub.
# The digest pin below is what makes this safe: the cache can serve a different
# *path*, never different bytes.
ARG DOCKERHUB_PREFIX=
FROM ${DOCKERHUB_PREFIX}library/python:3.11-slim@sha256:f9fa7f851e38bfb19c9de3afbc4b86ae7176ea7aaf94535c31df5458d5849457 AS base
ARG TARGETARCH=amd64

# Create non-root user for running the application
# UID/GID 1000 is standard for first non-root user
ARG UID=1000
ARG GID=1000
# Create docker group with GID 999 (common on Linux hosts) for socket access
RUN groupadd -g 999 docker || true && \
    groupadd -g ${GID} bnkforge && \
    useradd -m -u ${UID} -g bnkforge -G docker -s /bin/bash bnkforge

# Minimal system deps for the base image (curl for health checks, ca-certs for TLS)
# postgresql-client: pg_dump + psql for backup/restore operations (BR-002).
# Use the distro metapackage so the image stays buildable as Debian advances majors.
# --only-upgrade: the python:3.11-slim base lags Debian point releases and can
# ship base packages flagged CRITICAL — libgnutls30t64 (CVE-2026-42010 RSA-PSK
# auth bypass, CVE-2026-33845) and libssh2-1t64 (CVE-2026-55200 out-of-bounds
# write, fixed in 1.11.1-1+deb13u1). Pull the trixie-security builds explicitly;
# drop each once the base image tracks the fixed point release itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    openssh-client \
    postgresql-client \
    && apt-get install -y --only-upgrade libgnutls30t64 libssh2-1t64 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


# =============================================================================
# Stage 2: DEPENDENCIES — Python packages (cached across builds)
# =============================================================================
# BuildKit cache mount keeps pip's download cache across builds.
# First build: downloads everything (~60s). Subsequent: near-instant.
#
FROM base AS dependencies
ARG BUILD_DEV=false
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$BUILD_DEV" = "true" ]; then \
      pip install --prefix=/install -r requirements-dev.txt; \
    else \
      pip install --prefix=/install -r requirements.txt; \
    fi


# =============================================================================
# Stage 3: APP-BASE — Base + dependencies + application code
# =============================================================================
# This is the shared foundation for all targets. It has the full Python app
# but NO infrastructure CLI tools. Rebuilds only on code changes (fast).
#
FROM base AS app-base
# Copy pre-built Python packages from dependencies stage
COPY --from=dependencies /install /usr/local

# Copy application code (ordered by change frequency — least-changing first)
# The repo-root VERSION file. core/config.py._read_version_file() has always
# looked for /app/VERSION; nothing copied it, so settings.VERSION fell back to
# "0.0.0" in every backend image — visible on /api, in the OpenAPI title and in
# the X-Bnkscope-Version header. This is why the build context is the repo root
# rather than ./backend: VERSION lives above backend/ and cannot be reached from
# a context rooted inside it. The frontend image already builds this way.
COPY VERSION ./VERSION
COPY backend/core/ ./core/
COPY backend/models/ ./models/
COPY backend/schemas/ ./schemas/
COPY backend/utils/ ./utils/
COPY backend/services/ ./services/
COPY backend/routes/ ./routes/
COPY backend/jobs/ ./jobs/
# Python entry points change most often — copy last for best cache hits
COPY backend/*.py ./

# Create required directories and set ownership to bnkforge user
# /app/bfb-cache is pre-created so the named Docker volume inherits
# correct ownership on first mount (otherwise it initializes as root).
RUN mkdir -p /tmp/bnkscope-logs /tmp/bnkscope-modules /app/state /app/helm_charts /app/projects /app/keys /app/agent-token /app/workspaces /app/bfb-cache /app/provider-cache && \
    chown -R bnkforge:bnkforge /app /tmp/bnkscope-logs /tmp/bnkscope-modules

# Shared OpenTofu provider cache path (mounted from compose volume at runtime)
ENV TF_PLUGIN_CACHE_DIR=/app/provider-cache

# Copy entrypoint script
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]


# =============================================================================
# Stage 4: TOOLING-DEPS — Infrastructure CLI tools (independent of app code)
# =============================================================================
# For: the backend service (uvicorn). Runs everything: HTTP API, WebSocket
# fan-out, reachability probes, periodic jobs and the background thread pool.
#
FROM app-base AS api

# No CLI tools. Everything bnkscope does against a cluster goes through the
# Python kubernetes client, so tofu / helm / kubectl / aws-cli / oras — the
# slowest, most network-flaky layer in the old image — are all gone with the
# pipeline (Phase 1) and the tooling-deps stage (Phase 4).
#
# The database lives here; the volume is mounted over it at runtime.
RUN mkdir -p /app/data && chown -R bnkforge:bnkforge /app/data
# The log collector's shared volume. Created here, and owned by the app user,
# because a *fresh* named volume inherits the ownership of the image directory
# it is mounted over — without this it arrives root-owned and the backend
# cannot write the collector's config into it.
RUN mkdir -p /telemetry && chown -R bnkforge:bnkforge /telemetry
EXPOSE 8000
USER bnkforge
# Loopback bind. bnkscope has no authentication (Phase 3) — it is a local
# single-user tool, and the bind address IS the access control. The compose
# file runs this with network_mode: host, so 127.0.0.1 keeps the API off the
# network. Override BNKSCOPE_API_HOST only if you have put your own
# authenticating proxy in front of it.
#
# The port is settable because host networking means bnkscope shares the port
# space with whatever else the operator runs — including, on a developer's box,
# a full bnk-forge stack already holding 8000.
#
# --proxy-headers/--forwarded-allow-ips: trust X-Forwarded-* from loopback only.
CMD ["sh", "-c", "exec uvicorn main:app --host ${BNKSCOPE_API_HOST:-127.0.0.1} --port ${BNKSCOPE_API_PORT:-8000} --proxy-headers --forwarded-allow-ips=127.0.0.1"]


# Source code is NOT baked in; mount the repo at /app at runtime so iterative
# edits don't trigger rebuilds. Used by `make test-backend-docker` etc.
# Size: ~400MB (base + dev deps).
#
FROM base AS test
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-dev.txt
WORKDIR /app
ENTRYPOINT []
CMD ["python", "-m", "pytest", "tests/", "--tb=short", "-q"]
