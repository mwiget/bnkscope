# bnkscope MCP Server

An MCP (Model Context Protocol) server that exposes bnkscope's API to an AI
assistant as **30 read-only tools**. It is a thin client over the REST API —
there is no business logic here and no second path to your clusters.

## Quick start

The MCP server runs as a container alongside bnkscope, on loopback:

```bash
./bnkscope up            # starts it by default, on 127.0.0.1:8081
./bnkscope up --no-mcp   # skip it
```

Point your AI assistant at `http://127.0.0.1:8081/mcp`.

> **There is no authentication, here or in the backend.** bnkscope is a
> single-user local tool; the MCP server inherits that model exactly. Where it
> listens is the only access control there is, which is why it binds loopback
> and the backend does too. See the security section of the top-level
> [README](../README.md).

### Local development

```bash
cd mcp-server
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/
```

Or from the repo root: `make test-mcp`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BNKSCOPE_API_URL` | `http://127.0.0.1:8000` | Backend API URL |
| `BNKSCOPE_API_TIMEOUT` | `30` | Per-request timeout, seconds |
| `BNKSCOPE_VERIFY_SSL` | `false` | Verify TLS when the backend URL is https |
| `MCP_HOST` | `127.0.0.1` | Listen address. A bare `0.0.0.0` would put an unauthenticated tool server on every interface |
| `MCP_PORT` | `8081` | Listen port |
| `MCP_LOG_LEVEL` | `INFO` | Logging level |

The `BNK_FORGE_*` spellings of the first three are bnk-forge's and still work as
a fallback, so an existing environment file keeps running. Prefer `BNKSCOPE_*`.

## Live smoke validation

Unit and contract tests cover shape; this covers "is the deployed thing
actually answering":

```bash
make smoke-mcp-live                                   # direct MCP container
MCP_SMOKE_URL=http://127.0.0.1:8081/mcp make smoke-mcp-live
make mcp-readiness                                    # container liveness + runtime readiness
```

Underlying script: `scripts/mcp_live_smoke.py`.

### What it verifies

1. MCP endpoint reachability + JSON-RPC round-trip (`ping`)
2. Tool discovery (`tools/list`) includes the required governed tools
3. Read-only tool execution succeeds (`system_health`, `list_clusters`)
4. A failing tool call returns a structured MCP error envelope
   (`error_class`, `retryable`, `next_action`, `status_code`)

`ping` alone does not prove readiness — the protocol answers before the backend
is reachable. A `ping` that passes while `list_clusters` fails with
`transient_error` means the MCP container is up and the backend is not.

### Scope boundaries (intentional)

This is a small smoke suite, not an e2e framework. It proves the transport, the
catalog and one controlled failure path — not every tool against every cluster
shape.

## Tools (30, all read-only)

Every tool in the catalog is `risk_class: read_only`. Nothing here restarts a
pod, scales a deployment, execs into a container or writes to a cluster —
those operations exist in the HTTP API and the UI, deliberately not on the
agent-facing surface.

### system (2)
`system_health`, `system_settings`

### cluster_management (12)
`list_clusters`, `get_cluster`, `list_namespaces`, `list_resources`,
`get_resource`, `get_pod_logs`, `describe_resource`, `get_cluster_events`,
`get_node_metrics`, `get_pod_metrics`, `rollout_history`, `rollout_status`

### bnk_operations (8)
`bnk_data`, `bnk_gateway_topology`, `bnk_health`, `bnk_policy_associations`,
`a2a_discover_agents`, `tmm_list_pods`, `tmm_configview`, `bnk_recovery_status`

### diagnostics_fleet (8)
`qkview_list`, `qkview_status`, `cluster_connectivity`,
`cluster_connectivity_batch`, `dpf_detect`, `dpf_data`, `dpf_health`,
`list_alert_channels`

## Architecture

```
AI Assistant ↔ MCP (Streamable HTTP) ↔ MCP Server (:8081) ↔ HTTP ↔ FastAPI Backend (:8000)
```

- **Transport**: Streamable HTTP (stateless), supports SSE streaming
- **Auth**: none, at either hop — see above
- **No business logic duplication**: every tool is a thin wrapper over an existing REST route

## Contract hardening conventions

Mandatory for MCP tool changes:

1. **No guessed endpoints** — verify the route decorator in `backend/routes/**`.
2. **Match parameter location** — if the backend declares a value as a query
   param, send it as `params`, not in the JSON body.
3. **Prefer typed routes** — tools backed by a `response_model` first.
4. **Use structured error semantics** — the client returns a stable envelope on
   backend errors:

```json
{
  "ok": false,
  "request": {"method": "GET", "path": "/api/..."},
  "error": {
    "status_code": 404,
    "detail": "Not found",
    "error_class": "not_found",
    "retryable": false,
    "next_action": "Verify the target ID/name exists and that the route/path parameters are correct.",
    "url": "/api/..."
  }
}
```

`error_class` values: `validation_error`, `auth_error`, `not_found`,
`transient_error`, `server_error`, `request_error`.

### Output contract truthfulness (bounded)

Output-shape verification covers the `system` and `cluster_management` typed
routes: those tools return a truthful JSON serialization of the backend payload
(structured error envelopes included) without silently dropping or rewrapping
top-level contract fields. This is scoped on purpose and does not claim full
output-contract verification for every tool.

## Governance tool catalog

- **Canonical JSON artifact:** `mcp-server/tools/mcp_tool_catalog.json`
- **Python source of truth used by tests:** `mcp-server/src/bnkscope_mcp/tool_catalog.py`

Governed modules — full catalog coverage is enforced by tests:
`system`, `cluster_management`, `bnk_operations`, `diagnostics_fleet`. That is
every module the server registers, so coverage is currently total; the mechanism
stays in place so a new module cannot arrive uncatalogued.

Each entry carries: tool name and module, HTTP method + backend path template,
auth expectation, risk class, query-vs-body usage, and lifecycle metadata
(`stability`, `since_version`, `deprecated`, `replacement_tool`, `notes`).

> **`auth_expectation` is historical.** It records the role the corresponding
> bnk-forge route required (`viewer` / `operator` / `admin`). bnkscope removed
> authentication entirely, so the field documents provenance and relative
> sensitivity — it does not gate anything at runtime.

### Lifecycle metadata conventions (enforced)

- `stability`: `experimental` | `stable` | `internal`
- `since_version`: lightweight introduction marker
- `deprecated`: boolean
- `replacement_tool`: required when `deprecated=true` and a direct replacement
  exists; otherwise `notes` must carry explicit sunset justification

### Compatibility and deprecation policy

1. **Additive-first** — prefer additive changes; avoid silent removals/renames.
2. **Deprecation trigger** — mark `deprecated=true` when superseded, keeping the
   old invocation callable during the transition.
3. **`replacement_tool` semantics** — must reference a real, different catalog
   tool; non-deprecated tools must not set it.
4. **Compatibility window** — deprecated entries keep transition guidance in
   `notes` and stay callable until an explicit removal change.
5. **`since_version`** — an introduction marker for consumers, not semver.

Current bounded example: `get_resource` is a deprecated compatibility alias of
`describe_resource`. New consumers should call `describe_resource`.

### Risk classes

`read_only`, `mutating`, `destructive` — all 30 current tools are `read_only`.

## Observability contract

Structured invocation logs at two layers:

1. **Tool boundary** (`bnkscope_mcp.observability`)
   - `event`: `tool_invocation_start` / `tool_invocation_result` / `tool_invocation_blocked`
   - `invocation_id`, `tool_name`, `module`
   - catalog context when available: `risk_class`, `auth_expectation`, `backend_method`, `backend_path`
   - `success`, `duration_ms`, `error_class` (on failure)
   - `reason` (on `tool_invocation_blocked`)
2. **HTTP client boundary** (`bnkscope_mcp.client`)
   - `method`, `path`, `success`, `duration_ms`
   - `error_class`, `status_code` (on failure)

Logs deliberately exclude tool arguments, request bodies, tokens and backend
response payloads — useful for debugging without leaking cluster contents.

### Destructive-tool confirmation gate

Tools catalogued `risk_class: destructive` are enforced at runtime, not merely
logged. Each carries an extra `confirm: bool = False` argument, and calling one
without `confirm=true` returns a `CONFIRMATION_REQUIRED` refusal without
touching the backend:

```json
{
  "ok": false,
  "error": {
    "error_class": "confirmation_required",
    "code": "CONFIRMATION_REQUIRED",
    "retryable": false,
    "next_action": "Verify this is the intended target, then re-invoke with confirm=true..."
  }
}
```

**No tool is currently destructive**, so the gate does not fire today. It is
kept armed because the backend has no authentication: if a mutating tool is ever
catalogued, one call from an autonomous agent would reach a live cluster with no
second factor. The gate follows the catalog — mark a tool `destructive` and it
is gated automatically, with no change at the registration site.

`confirm` is distinct from a tool's own `force` argument: `force` bypasses a
*backend* safety check; `confirm` asserts *intent* to run the operation at all.

Set `BNKSCOPE_MCP_REQUIRE_CONFIRMATION=false` to disable the gate for trusted
non-interactive use. It is read per call and defaults to enabled.

## Maintenance workflow

Required when changing covered tools:

1. Update the tool implementation under `src/bnkscope_mcp/tools/`.
2. Verify the backend route signature (method/path, query vs JSON body) in `backend/routes/**`.
3. Update the `tool_catalog.py` entry and regenerate `tools/mcp_tool_catalog.json`.
4. Adding or changing a tool in a governed module makes catalog coverage
   mandatory — the tests fail if it is missing.
5. Update mapping checks in `tests/test_tool_mapping_hardening.py` for
   request-shape-sensitive tools.
6. Run the targeted checks:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_tool_output_contracts.py \
  tests/test_tool_catalog.py \
  tests/test_observability.py \
  tests/test_tool_mapping_hardening.py \
  tests/test_client_error_semantics.py \
  tests/test_url_audit.py

# optional live runtime sanity (requires a running MCP deployment)
python3 ../scripts/mcp_live_smoke.py --mcp-url http://127.0.0.1:8081/mcp
```

### Enforced policy guarantees

- The JSON artifact must exactly match the Python catalog source.
- Every entry must use an allowed risk class and stability value.
- Every entry must include lifecycle metadata (`since_version`, `deprecated`, optional `replacement_tool`).
- `replacement_tool`, when set, must point to a real, different tool.
- Non-deprecated entries must not define `replacement_tool`.
- Deprecated entries must document sunset guidance in `notes`.
- Every entry must map to a known tool URL/method in the URL audit ground truth.
- Every entry must exist in the registered MCP tools.
- Every tool in a governed module must be present in the catalog.

Catalog drift fails loudly in CI.
