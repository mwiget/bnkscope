variable "REGISTRY" {}
variable "VERSION" {}
variable "PLATFORMS" {
  default = "linux/amd64,linux/arm64"
}
# Floating tag pushed alongside the immutable :VERSION tag.
#   "latest"        -> conventional floating tag (default)
#   "customer-build"-> rolling tag for the customer-build line
#   ""              -> push ONLY the versioned tag (e.g. registries that forbid overwriting an existing floating manifest)
variable "ROLLING_TAG" {
  default = "latest"
}
# OCI image labels — injectable at build time.
#   GIT_REVISION  -> git commit SHA (set by make push-images / CI)
#   SOURCE_URL    -> canonical repo URL (default: upstream)
variable "GIT_REVISION" {
  default = "unknown"
}
variable "SOURCE_URL" {
  default = "https://github.com/mwiget/bnkscope"
}

group "default" {
  targets = ["api", "frontend", "mcp", "exporter"]
}

target "_common" {
  platforms = split(",", PLATFORMS)
  labels = {
    "org.opencontainers.image.source"   = SOURCE_URL
    "org.opencontainers.image.revision" = GIT_REVISION
    "org.opencontainers.image.version"  = VERSION
    "org.opencontainers.image.created"  = timestamp()
  }
}

target "_backend" {
  inherits   = ["_common"]
  // Repo root, not ./backend — the VERSION file lives above backend/ and the
  // image needs it (see backend/Dockerfile). Matches the frontend target.
  context    = "."
  dockerfile = "backend/Dockerfile"
}

target "api" {
  inherits = ["_backend"]
  target   = "api"
  tags = concat(
    ["${REGISTRY}/bnkscope-api:${VERSION}"],
    ROLLING_TAG != "" ? ["${REGISTRY}/bnkscope-api:${ROLLING_TAG}"] : [],
  )
}

target "frontend" {
  inherits   = ["_common"]
  context    = "."
  dockerfile = "frontend-v2/Dockerfile"
  tags = concat(
    ["${REGISTRY}/bnkscope-frontend:${VERSION}"],
    ROLLING_TAG != "" ? ["${REGISTRY}/bnkscope-frontend:${ROLLING_TAG}"] : [],
  )
}

target "mcp" {
  inherits = ["_common"]
  context  = "./mcp-server"
  tags = concat(
    ["${REGISTRY}/bnkscope-mcp:${VERSION}"],
    ROLLING_TAG != "" ? ["${REGISTRY}/bnkscope-mcp:${ROLLING_TAG}"] : [],
  )
}

// The tmm-stat-exporter sidecar. Unlike the other three this one does not run
// here — it is injected into f5-tmm pods on the operator's clusters, so those
// clusters must be able to pull it. Its own Go module; context is its
// directory, not the repo root.
target "exporter" {
  inherits = ["_common"]
  context  = "./tmm-stat-exporter"
  tags = concat(
    ["${REGISTRY}/bnkscope-tmm-stat-exporter:${VERSION}"],
    ROLLING_TAG != "" ? ["${REGISTRY}/bnkscope-tmm-stat-exporter:${ROLLING_TAG}"] : [],
  )
}

