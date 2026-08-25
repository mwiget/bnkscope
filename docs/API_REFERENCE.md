# bnkscope — API Reference

> **Generated from `backend/openapi.json` by `scripts/gen-api-reference.py`.**
> Do not edit by hand — run `make api-docs` (or the script) instead.
> `--check` runs in CI, so this file cannot drift from the code.

bnkscope serves **135 operations** across **120 paths**.

Summaries are FastAPI's, derived from the handler name — they are terse
because the code is, not because the doc is abridged. A `—` under **Returns**
means the endpoint declares no `response_model`; 71 of 135 do
not, so the shape there is whatever the handler returns.

## Authentication — there is none

**Every endpoint below is unauthenticated.** bnkscope is a single-user local
troubleshooting tool; authentication, users, roles and sessions were removed
deliberately.

This is safe *because of where it listens*, and only that:

| | |
|---|---|
| API (`bnkscope-backend`) | binds loopback only — not reachable off the host |
| UI (`bnkscope-frontend`) | binds `127.0.0.1` by default, and proxies `/api` to the API |
| `./bnkscope up --listen 0.0.0.0` | **exposes every operation below, unauthenticated, to your network** |

Nothing takes over when the bind widens — there is no token and no password to
add. Anyone who can reach the port gets a shell in any pod (`/ws/.../exec`), and
`POST /api/system/backup` hands back the database together with the key that
decrypts it, so every kubeconfig and cloud credential leaves in one request.
Traffic is plain HTTP, so all of it is readable and modifiable in flight.

Use it only on a network you would trust with all of that: a private lab
network, or a VPN (Tailscale/WireGuard) with `--listen` bound to the VPN
interface. Otherwise leave the bind at its loopback default and tunnel:

```sh
ssh -N -L 8080:localhost:8080 you@the-host
```

`--listen` governs the UI only. Prometheus (`9491`) always binds `0.0.0.0`,
because your clusters push to it; see
the README for what each exposes.

Interactive versions of this reference are served by the running backend at
`/docs` (Swagger UI) and `/redoc`.

---

## Contents

- [System](#system) — 18
- [Connectivity](#connectivity) — 3
- [Clusters](#clusters) — 16
- [Kubernetes Resources](#kubernetes-resources) — 25
- [Custom Resource Definitions](#custom-resource-definitions) — 1
- [Topology](#topology) — 1
- [F5 BNK](#f5-bnk) — 7
- [NVIDIA DPF](#nvidia-dpf) — 3
- [TMM Debug](#tmm-debug) — 6
- [LLM Observability](#llm-observability) — 6
- [Cluster Recovery](#cluster-recovery) — 3
- [tmmscope](#tmmscope) — 6
- [qkview](#qkview) — 9
- [Alert Channels](#alert-channels) — 9
- [Notifications](#notifications) — 6
- [Meta](#meta) — 8
- [k8s-nico](#k8s-nico) — 6
- [logs](#logs) — 2


## System

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `POST` | `/api/system/backup` | Create Backup | — | BackupCreateRequest | — |
| `GET` | `/api/system/backup/status` | Get Backup Status | — | — | BackupStatusResponse |
| `POST` | `/api/system/database/vacuum` | Vacuum Database | — | — | — |
| `GET` | `/api/system/defaults` | Get System Defaults | — | — | — |
| `PUT` | `/api/system/defaults` | Update System Defaults | — | DefaultsUpdateRequest | — |
| `GET` | `/api/system/defaults/status` | Get Defaults Status | — | — | — |
| `PUT` | `/api/system/defaults/{key}` | Update Single Default | `{key}` `value` | — | — |
| `GET` | `/api/system/errors` | Get Recent Errors | `limit`? | — | — |
| `GET` | `/api/system/health` | Get System Health | — | — | SystemHealthResponse |
| `GET` | `/api/system/maintenance` | Get Maintenance Mode | — | — | MaintenanceStatusResponse |
| `GET` | `/api/system/mcp/status` | Get Mcp Status | — | — | — |
| `GET` | `/api/system/performance` | Get Performance Metrics | — | — | — |
| `GET` | `/api/system/process-metrics` | Get Process Metrics | — | — | ProcessMetricsResponse |
| `POST` | `/api/system/restore` | Restore Backup | — | Body_restore_backup_api_system_restore_post | RestoreResponse |
| `POST` | `/api/system/upgrade` | Trigger System Upgrade | — | — | — |
| `GET` | `/api/system/upgrade/status` | Get Upgrade Status | — | — | — |
| `GET` | `/api/system/upgrade/verify` | Verify Post Upgrade | — | — | — |
| `GET` | `/api/system/version` | Get System Version | — | — | — |


## Connectivity

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `POST` | `/api/connectivity/probe/{target_type}/{target_id}` | Force Probe | `{target_id}` `{target_type}` | — | ReachabilityStateResponse |
| `GET` | `/api/connectivity/state` | Get State | — | — | StateListResponse |
| `GET` | `/api/connectivity/watch` | Watch | — | — | — |


## Clusters

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters` | List All Clusters | — | — | ClusterListResponse |
| `POST` | `/api/k8s/clusters` | Add Cluster | — | ClusterCreateRequest | ClusterCreateResponse |
| `GET` | `/api/k8s/clusters/connectivity` | Batch Connectivity Check | — | — | BatchConnectivityResponse |
| `DELETE` | `/api/k8s/clusters/{cluster_id}` | Delete Cluster | `{cluster_id}` | — | ClusterOperationResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}` | Get Cluster Details | `{cluster_id}` | — | ClusterDetailResponse |
| `PUT` | `/api/k8s/clusters/{cluster_id}` | Update Cluster | `{cluster_id}` | ClusterUpdateRequest | ClusterSummary |
| `GET` | `/api/k8s/clusters/{cluster_id}/connectivity` | Check Cluster Connectivity | `{cluster_id}` | — | ClusterConnectivityResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/namespaces` | List Cluster Namespaces | `{cluster_id}` | — | NamespaceListResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/node-readiness/probe` | Probe Node Readiness | `{cluster_id}` | NodeReadinessProbeRequest | NodeReadinessProbeResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/nodes/count` | Get Cluster Node Count | `{cluster_id}` | — | NodeCountResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/recommendations/hugepages/deploy` | Deploy Hugepages | `{cluster_id}` | HugePagesDeployRequest | HugePagesDeployResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/scan` | Scan Cluster | `{cluster_id}` `force`? | — | ClusterScanEnvelope |
| `POST` | `/api/k8s/clusters/{cluster_id}/test` | Test Cluster Connection | `{cluster_id}` | — | ClusterConnectionTestResponse |
| `GET` | `/api/k8s/discovery` | List Discovery Candidates | — | — | DiscoveryResponse |
| `POST` | `/api/k8s/discovery/adopt` | Adopt Kube Context | — | DiscoveryAdoptRequest | DiscoveryResponse |
| `GET` | `/api/k8s/resource-types` | List Supported Resource Types | — | — | ResourceTypeCatalogResponse |


## Kubernetes Resources

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/history` | Get Rollout History | `{cluster_id}` `{deployment_name}` `namespace` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/pause` | Rollout Pause | `{cluster_id}` `{deployment_name}` `namespace` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/restart` | Rollout Restart | `{cluster_id}` `{deployment_name}` `namespace` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/resume` | Rollout Resume | `{cluster_id}` `{deployment_name}` `namespace` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/status` | Get Rollout Status | `{cluster_id}` `{deployment_name}` `namespace` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/undo` | Rollout Undo | `{cluster_id}` `{deployment_name}` `namespace` `revision`? | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/scale` | Scale Deployment | `{cluster_id}` `{deployment_name}` | ScaleDeploymentRequest | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/events` | Get Cluster Events | `{cluster_id}` `event_type`? `namespace`? `resource_name`? `resource_type`? | — | ClusterEventsResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/nodes/{node_name}/cordon` | Cordon Node | `{cluster_id}` `{node_name}` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/nodes/{node_name}/drain` | Drain Node | `{cluster_id}` `{node_name}` `delete_emptydir_data`? `force`? `grace_period`? `ignore_daemonsets`? | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/nodes/{node_name}/uncordon` | Uncordon Node | `{cluster_id}` `{node_name}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/pods/{pod_name}/containers` | List Pod Containers | `{cluster_id}` `{pod_name}` `namespace` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/pods/{pod_name}/logs` | Get Pod Logs | `{cluster_id}` `{pod_name}` `container`? `namespace` `tail_lines`? | — | PodLogsResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/pods/{pod_name}/restart` | Restart Pod | `{cluster_id}` `{pod_name}` `namespace` | — | PodRestartResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/resource-summary` | Get Cluster Resource Summary | `{cluster_id}` `namespace`? | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}` | Get Cluster Resources | `{cluster_id}` `{resource_type}` `group`? `label_selector`? `namespace`? | — | ResourceListEnvelope |
| `POST` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}` | Create Resource | `{cluster_id}` `{resource_type}` | ResourceCreateRequest | — |
| `DELETE` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}` | Delete Resource | `{cluster_id}` `{resource_name}` `{resource_type}` `dry_run`? `namespace`? | — | — |
| `PATCH` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}` | Patch Resource | `{cluster_id}` `{resource_name}` `{resource_type}` | ResourcePatchRequest | — |
| `PUT` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}` | Update Resource | `{cluster_id}` `{resource_name}` `{resource_type}` | ResourceUpdateRequest | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}/annotate` | Annotate Resource | `{cluster_id}` `{resource_name}` `{resource_type}` | AnnotateResourceRequest | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}/describe` | Describe Resource | `{cluster_id}` `{resource_name}` `{resource_type}` `namespace`? | — | ResourceDescribeEnvelope |
| `POST` | `/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{resource_name}/label` | Label Resource | `{cluster_id}` `{resource_name}` `{resource_type}` | LabelResourceRequest | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/top/nodes` | Get Node Metrics | `{cluster_id}` `sort_by`? | — | NodeTopResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/top/pods` | Get Pod Metrics | `{cluster_id}` `namespace`? `sort_by`? | — | PodTopResponse |


## Custom Resource Definitions

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/crds` | Get Cluster Crds | `{cluster_id}` `group`? | — | CrdListEnvelope |


## Topology

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/topology` | Get Cluster Topology | `{cluster_id}` `namespace`? | — | TopologyGraphResponse |


## F5 BNK

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/analyzers/{namespace}/{name}/backend-health` | Get Backend Health Route | `{cluster_id}` `{name}` `{namespace}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/analyzers/{namespace}/{name}/runtime-metrics` | Get Analyzer Metrics | `{cluster_id}` `{name}` `{namespace}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/f5bnk/a2a/agents` | Get A2A Agents | `{cluster_id}` `namespace`? `probe`? | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/f5bnk/data` | Get Bnk Data | `{cluster_id}` `namespace`? | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/f5bnk/gateway-topology` | Get Gateway Topology | `{cluster_id}` `namespace`? | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/f5bnk/health` | Get Bnk Health | `{cluster_id}` `namespace`? | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/f5bnk/policy-gateway-associations` | Get Policy Gateway Associations | `{cluster_id}` `namespace`? | — | — |


## NVIDIA DPF

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/dpf/data` | Get Dpf Data | `{cluster_id}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/dpf/detect` | Get Dpf Detect | `{cluster_id}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/dpf/health` | Get Dpf Health | `{cluster_id}` | — | — |


## TMM Debug

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `POST` | `/api/k8s/clusters/{cluster_id}/tmm-debug/bdt` | Post Tmm Debug Bdt | `{cluster_id}` | TMMDebugBdtRequest | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/tmm-debug/configview` | Post Tmm Debug Configview | `{cluster_id}` | TMMDebugConfigviewRequest | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/tmm-debug/configview/uuids` | Post Tmm Debug Configview Uuids | `{cluster_id}` | TMMDebugConfigviewUuidsRequest | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/tmm-debug/exec` | Post Tmm Debug Exec | `{cluster_id}` | TMMDebugExecRequest | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/tmm-debug/pods` | Get Tmm Debug Pods | `{cluster_id}` | — | — |
| `POST` | `/api/k8s/clusters/{cluster_id}/tmm-debug/tmctl` | Post Tmm Debug Tmctl | `{cluster_id}` | TMMDebugTmctlRequest | — |


## LLM Observability

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/filterdata` | Get Llm Filterdata | `{cluster_id}` `range`? | — | LlmFilterDataResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/histogram` | Get Llm Histogram | `{cluster_id}` `metric`? `model`? `range`? `status`? | — | LlmHistogramResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/logs` | Get Llm Logs | `{cluster_id}` `content_search`? `end`? `limit`? `model`? `range`? `status`? | — | LlmLogsResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/provider-usage` | Get Llm Provider Usage | `{cluster_id}` `metric`? `model`? `range`? `status`? | — | LlmProviderUsageResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/rankings` | Get Llm Rankings | `{cluster_id}` `model`? `range`? `status`? | — | LlmRankingsResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/llm-observability/stats` | Get Llm Stats | `{cluster_id}` `model`? `range`? `status`? | — | LlmStatsResponse |


## Cluster Recovery

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `POST` | `/api/k8s/clusters/{cluster_id}/recovery/cwc-certs` | Resync Cwc Certs | `{cluster_id}` | — | CWCCertResyncResponse |
| `POST` | `/api/k8s/clusters/{cluster_id}/recovery/platform-restart` | Platform Restart | `{cluster_id}` | PlatformRestartRequest | PlatformRestartResponse |
| `GET` | `/api/k8s/clusters/{cluster_id}/recovery/status` | Get Recovery Status | `{cluster_id}` | — | RecoveryStatusResponse |


## tmmscope

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/tmmscope/clusters/{cluster_id}` | Get Cluster Telemetry | `{cluster_id}` `theme`? | — | ClusterTelemetryResponse |
| `DELETE` | `/api/tmmscope/clusters/{cluster_id}/injection` | Remove Exporter | `{cluster_id}` | — | InjectionStateResponse |
| `GET` | `/api/tmmscope/clusters/{cluster_id}/injection` | Get Injection | `{cluster_id}` | — | InjectionStateResponse |
| `POST` | `/api/tmmscope/clusters/{cluster_id}/injection` | Inject Exporter | `{cluster_id}` | InjectRequest | InjectionStateResponse |
| `PUT` | `/api/tmmscope/clusters/{cluster_id}/label` | Bind Cluster Label | `{cluster_id}` `theme`? | BindLabelRequest | ClusterTelemetryResponse |
| `GET` | `/api/tmmscope/status` | Get Tmmscope Status | — | — | TmmscopeStatusResponse |


## qkview

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/qkview/check` | Check Cwc | `cluster_id` | — | QKViewCheckResponse |
| `POST` | `/api/qkview/cleanup-pods` | Cleanup Pods Endpoint | `cluster_id` | — | QKViewCleanupResponse |
| `POST` | `/api/qkview/create` | Create Qkview Endpoint | — | QKViewCreateRequest | QKViewCreateResponse |
| `GET` | `/api/qkview/list` | List Qkviews Endpoint | `cluster_id` | — | QKViewListResponse |
| `DELETE` | `/api/qkview/{qkview_id}` | Delete Qkview Endpoint | `{qkview_id}` `cluster_id` | — | QKViewDeleteResponse |
| `GET` | `/api/qkview/{qkview_id}` | Get Qkview Endpoint | `{qkview_id}` `cluster_id` | — | QKViewGetResponse |
| `POST` | `/api/qkview/{qkview_id}/cancel` | Cancel Qkview Endpoint | `{qkview_id}` `cluster_id` | — | QKViewCancelResponse |
| `GET` | `/api/qkview/{qkview_id}/download` | Download Qkview Endpoint | `{qkview_id}` `cluster_id` | — | — |
| `GET` | `/api/qkview/{qkview_id}/status` | Get Qkview Status Endpoint | `{qkview_id}` `cluster_id` | — | QKViewStatusResponse |


## Alert Channels

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/alert-channels` | List Alert Channels | `channel_type`? `enabled`? | — | — |
| `POST` | `/api/alert-channels` | Create Alert Channel | — | AlertChannelCreate | — |
| `GET` | `/api/alert-channels/history/recent` | Get Recent Alerts | `event_type`? `limit`? `severity`? | — | — |
| `DELETE` | `/api/alert-channels/{channel_id}` | Delete Alert Channel | `{channel_id}` | — | — |
| `GET` | `/api/alert-channels/{channel_id}` | Get Alert Channel | `{channel_id}` | — | — |
| `PUT` | `/api/alert-channels/{channel_id}` | Update Alert Channel | `{channel_id}` | AlertChannelUpdate | — |
| `GET` | `/api/alert-channels/{channel_id}/history` | Get Channel History | `{channel_id}` `event_type`? `limit`? `offset`? `status`? | — | — |
| `POST` | `/api/alert-channels/{channel_id}/test` | Test Alert Channel | `{channel_id}` | — | — |
| `POST` | `/api/alert-channels/{channel_id}/toggle` | Toggle Alert Channel | `{channel_id}` | — | — |


## Notifications

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/notifications` | Get Notifications | `before_id`? `category`? `limit`? `severity`? `unread_only`? `user`? | — | NotificationResponse[] |
| `POST` | `/api/notifications` | Create Notification | — | NotificationCreate | NotificationResponse |
| `POST` | `/api/notifications/mark-all-read` | Mark All Read | `user`? | — | NotificationActionResponse |
| `GET` | `/api/notifications/unread-count` | Get Unread Count | `user`? | — | UnreadCountResponse |
| `DELETE` | `/api/notifications/{notification_id}` | Delete Notification | `{notification_id}` | — | NotificationActionResponse |
| `PATCH` | `/api/notifications/{notification_id}/read` | Mark Notification Read | `{notification_id}` | — | NotificationActionResponse |


## Meta

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/` | Root | — | — | — |
| `GET` | `/api/database/stats` | Get Database Stats | — | — | — |
| `GET` | `/api/health` | Health Check Api | — | — | — |
| `GET` | `/api/settings` | Get Settings | — | — | SettingsResponse |
| `PUT` | `/api/settings` | Batch Update Settings | — | SettingsBatchUpdate | — |
| `PUT` | `/api/settings/{key}` | Update Setting | `{key}` `value` | — | — |
| `GET` | `/health` | Health Check | — | — | — |
| `GET` | `/ping` | Ping | — | — | — |


## k8s-nico

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/k8s/clusters/{cluster_id}/nico/data` | Get Nico Data | `{cluster_id}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/nico/deployment` | Get Nico Deployment | `{cluster_id}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/nico/detect` | Get Nico Detect | `{cluster_id}` | — | — |
| `PUT` | `/api/k8s/clusters/{cluster_id}/nico/endpoint` | Put Nico Endpoint | `{cluster_id}` | ForgeEndpointRequest | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/nico/health` | Get Nico Health | `{cluster_id}` | — | — |
| `GET` | `/api/k8s/clusters/{cluster_id}/nico/inventory` | Get Nico Inventory | `{cluster_id}` | — | — |


## logs

| Method | Path | Summary | Params | Body | Returns |
|---|---|---|---|---|---|
| `GET` | `/api/logs/filters` | Get Filters | — | — | LogFiltersResponse |
| `GET` | `/api/logs/search` | Search Logs | `cluster`? `container`? `level`? `limit`? `logql`? `minutes`? `namespace`? `pod`? `search`? | — | LogSearchResponse |


---

*Schemas for every model named above are in `backend/openapi.json`, and rendered at `/redoc` on a running backend.*
