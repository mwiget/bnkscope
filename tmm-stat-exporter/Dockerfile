# The tmm-stat-exporter sidecar — the container TMM Live injects into f5-tmm
# pods. Multi-stage and self-contained, so the same file serves a local
# `make exporter-image` and the multi-arch buildx in release.yml
# (--platform linux/amd64,linux/arm64 sets TARGETARCH).
#
#   docker build -t tmm-stat-exporter:dev tmm-stat-exporter/
#
# The build context is this directory, not the repo root: the exporter is its
# own Go module and shares nothing with the Python and TypeScript above it.
FROM --platform=$BUILDPLATFORM golang:1.26 AS build
ARG TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH \
    go build -trimpath -ldflags "-s -w" -o /tmm-stat-exporter .

# scratch, not distroless: a static binary that reads one memory-mapped file and
# makes outbound HTTP needs no libc, no shell, and nothing to exec. It also runs
# with readOnlyRootFilesystem and every capability dropped — see
# backend/services/tmmscope_inject_service.py for the spec it is injected with.
FROM scratch
COPY --from=build /tmm-stat-exporter /tmm-stat-exporter
USER 65532:65532
ENTRYPOINT ["/tmm-stat-exporter"]
