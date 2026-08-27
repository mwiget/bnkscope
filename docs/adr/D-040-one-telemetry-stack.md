# D-040: One telemetry stack, discovered one way

**Status:** Accepted
**Date:** 2026-08-27
**Completes:** [D-036](D-036-tmmscope-injection-in-bnkscope.md), [D-039](D-039-fork-the-tmm-stat-exporter.md)

---

## Context & Problem Statement

bnkscope had two ways to find Prometheus and Grafana:

1. its own stack, started by `bnkscope up --telemetry`, whose negotiated ports
   arrive as environment variables, and
2. tmmscope's, read from `~/.config/tmmscope/endpoints.json` — bind-mounted
   read-only into the backend — when the first was absent.

The fallback made sense when it was written. D-036 had just moved injection into
bnkscope but left the stack outside ("Increment B moves the stack into
bnkscope's own compose file instead"), and an operator already running
`tmmscope up` should not have had it ignored.

Increment B happened. D-039 then brought the exporter itself in. Nothing in
bnkscope requires tmmscope any more — not to inject, not to receive, not to
graph — and tmmscope is being archived. What is left of the fallback is a second
code path for a stack the operator is being told to stop running.

It is not free. It is a bind mount into the backend, a directory `bnkscope up`
creates in the operator's home so Docker cannot create it as root, an
`endpoints_path()` with an XDG resolution order to match tmmscope's, a
`BNKSCOPE_TMMSCOPE_ENDPOINTS` override, the JSON-parse-and-validate around a
file written by another program, and the tests for all of it. And it is
untested in the way that matters: nobody exercises it, so it can only rot.

## Decision

**Read the environment, and nothing else.**

`read_endpoints()` is now what `_own_stack()` was: it returns the ports
`bnkscope up` passed in, or `None`. The document keeps the shape tmmscope's file
had, because everything downstream — dashboards, streaming detection,
injection's remote-write URL — already reads that shape and needs no second code
path.

Removed with it: the `~/.config/tmmscope` bind mount and the `mkdir` that kept
it from being root-owned, `endpoints_path()`, `DEFAULT_ENDPOINTS_PATH`, the
`BNKSCOPE_TMMSCOPE_ENDPOINTS` override, the "Already using tmmscope?" fold that
offered `tmmscope up` as an alternative, and the copy throughout TMM Live that
named tmmscope as the thing receiving telemetry.

`BNKSCOPE_TMMSCOPE_PROBE_HOST` is renamed `BNKSCOPE_TELEMETRY_PROBE_HOST`. It is
set by the bridge-mode compose overlay, not by operators, and the mechanism it
serves — "localhost" means the container, not the host — has nothing to do with
which program started Grafana.

### What this costs someone still running tmmscope

Their stack stops being found. Both were never running usefully at once anyway:
they compete for 9491 and 3000, and the second one up walks to different ports.
The fix is one command — `bnkscope up`, having stopped the other — and the
dashboards are the same dashboards, vendored in `telemetry/`.

The exporters they already injected keep pushing to the *old* Prometheus port,
which is exactly the stale-target state TMM Live was built to name: the page
says the exporter is running, says where it is pushing, says where Prometheus
now is, and offers the fix.

### What is deliberately kept

The 9491 default for Prometheus, rather than 9090. It is tmmscope's number, and
keeping it means an operator moving across does not have to re-point anything
that already targets 9491.

## Consequences

- One way to find the stack, exercised on every run — no path that only executes
  on a machine nobody has.
- The backend's mount list is down to the three credential directories, which
  makes "what does this container read from my home?" a shorter answer.
- Anyone still on tmmscope's stack must switch rather than coexist. That is the
  honest consequence of D-039 and this: bnkscope stopped being a thing that
  orchestrates tmmscope and became the thing itself.
- `tmmscope_service.py` is now `telemetry_service.py`, and its `TmmscopeStatus`
  is `TelemetryStatus`. The module had stopped describing what it does: it reads
  bnkscope's own stack and asks bnkscope's own Prometheus what is arriving.
- The **route** module, the API path `/api/tmmscope/...`, and
  `tmmscope_inject_service` keep their names. The path is a published contract
  and renaming it breaks callers for a nicer noun; the inject service is named
  after the operation it forked from tmmscope, which is still accurate.
