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

// The one image bnkscope publishes. It is the only one that has to be pulled by
// something other than the machine that built it: the exporter runs inside the
// operator's f5-tmm pods, so their clusters need it from a registry.
//
// bnkscope's own three — api, frontend, mcp — are built from source by
// `./bnkscope up` and are not published. Publishing them bought nothing: the
// compose file, the telemetry configs and VERSION are all bind-mounted from the
// checkout, so a released image still needs the repository next to it. See
// D-041.
group "default" {
  targets = ["exporter"]
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

// Its own Go module, so the context is its directory rather than the repo root.
target "exporter" {
  inherits = ["_common"]
  context  = "./tmm-stat-exporter"
  tags = concat(
    ["${REGISTRY}/bnkscope-tmm-stat-exporter:${VERSION}"],
    ROLLING_TAG != "" ? ["${REGISTRY}/bnkscope-tmm-stat-exporter:${ROLLING_TAG}"] : [],
  )
}

