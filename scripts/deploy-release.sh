#!/usr/bin/env bash
# deploy-release.sh — run bnkscope from published images instead of building it.
#
# `./bnkscope up` builds all three images from source, which is the right
# default for a repository you are working in and the wrong one for a host that
# only wants to run the thing: a Vite build and a Python image, per machine,
# per upgrade. This pulls what a release already published — multi-arch, signed,
# with an SBOM and provenance — and starts it.
#
#   make deploy-release                    # latest
#   make deploy-release VERSION=0.1.2      # a specific release
#   ./scripts/deploy-release.sh 0.1.2 --listen 0.0.0.0
#
# Anything after the version is passed through to `bnkscope up`.
#
# It does NOT call `docker compose` itself. The CLI negotiates ports, writes the
# discovery file, creates the host mount directories as you rather than as root,
# and loads the Grafana password; a bare compose call skips all of that and
# quietly breaks a running install. This sets BNKSCOPE_COMPOSE_EXTRA and hands
# off — the same reason upgrade.sh delegates rather than driving compose.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="${BNKSCOPE_RELEASE_REGISTRY:-ghcr.io/mwiget}"
OVERLAY="${REPO_DIR}/docker-compose.release.yml"

RED=''; YELLOW=''; BOLD=''; DIM=''; RESET=''
if [ -t 1 ]; then
  RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
fi
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }

# A leading bare version, or --version=X. Everything else is bnkscope's.
VERSION="${BNKSCOPE_RELEASE_VERSION:-latest}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  VERSION="$1"; shift
fi
# `v0.1.2` is what the git tag and the release page say; the image tags do not
# carry the v. Accept either rather than failing on the one people will copy.
VERSION="${VERSION#v}"

[ -f "$OVERLAY" ] || die "missing $OVERLAY — is this a complete checkout?"
command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH"

IMAGES=(bnkscope-api bnkscope-frontend bnkscope-mcp)

echo ""
echo "========================================================"
echo "  bnkscope — deploy from published images"
echo "========================================================"
echo "  Registry:  ${REGISTRY}"
echo "  Version:   ${VERSION}"
echo ""

# Pull explicitly rather than letting compose do it on demand. A missing tag is
# the most likely thing to go wrong here — a version that was never released, or
# one whose images were withdrawn — and compose reports that from inside an
# `up`, half-way through starting containers.
step "Pulling images"
for name in "${IMAGES[@]}"; do
  ref="${REGISTRY}/${name}:${VERSION}"
  printf '  %s ... ' "$ref"
  if ! docker pull -q "$ref" >/dev/null 2>&1; then
    echo ""
    die "could not pull ${ref}

Check that this version was published, and that its images are still there:
  https://github.com/mwiget/bnkscope/pkgs/container/${name}

Released images are listed at https://github.com/mwiget/bnkscope/releases"
  fi
  digest="$(docker image inspect "$ref" --format '{{index .RepoDigests 0}}' 2>/dev/null | sed 's/.*@//')"
  printf '%s%s%s\n' "$DIM" "${digest:-pulled}" "$RESET"
done

# Verification is offered, not enforced. Every release since v0.1.2 is signed
# keylessly, but cosign is not a dependency of running bnkscope and refusing to
# start without it would be a poor trade for a lab tool.
if command -v cosign >/dev/null 2>&1; then
  step "Verifying signatures (cosign)"
  for name in "${IMAGES[@]}"; do
    ref="${REGISTRY}/${name}:${VERSION}"
    if cosign verify \
        --certificate-identity-regexp '^https://github\.com/mwiget/bnkscope/' \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        "$ref" >/dev/null 2>&1; then
      printf '  %s %sok%s\n' "$ref" "$DIM" "$RESET"
    else
      warn "could not verify ${ref} — see docs/DOCKER.md for what a valid signature looks like"
    fi
  done
else
  printf '  %sinstall cosign to verify these signatures — see docs/DOCKER.md%s\n' "$DIM" "$RESET"
fi

step "Starting bnkscope"
export BNKSCOPE_COMPOSE_EXTRA="$OVERLAY"
export BNKSCOPE_RELEASE_VERSION="$VERSION"
export BNKSCOPE_RELEASE_REGISTRY="$REGISTRY"
exec "${REPO_DIR}/bnkscope" up --no-build "$@"
