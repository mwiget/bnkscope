/**
 * tmmscope — the standalone TMM telemetry stack bnkscope orchestrates.
 *
 * `tmmscope up` is still a host command: starting Prometheus and Grafana needs
 * the Docker socket. Injection is not — see D-036. bnkscope adds the exporter
 * as an *ephemeral container*, which does not restart TMM and works on
 * operator-managed BNK.
 */

export interface TmmscopeDashboard {
  uid: string;
  title: string;
  description: string;
}

export interface TmmscopeStatus {
  /** The discovery file exists and claims the stack is up. */
  configured: boolean;
  /** Grafana actually answered. `configured` without this is a stale file. */
  running: boolean;
  grafana_url: string | null;
  prometheus_url: string | null;
  updated_at: string | null;
  /** cluster= labels Prometheus holds f5tmm_up series for — what "injected"
   *  actually means, as opposed to what a file claims. */
  streaming_clusters: string[];
  /** cluster= label -> seconds since its last sample. Carries labels that have
   *  *stopped*, which `streaming_clusters` cannot: five minutes after a cluster
   *  goes quiet it drops out and looks like one that never streamed. */
  last_seen: Record<string, number>;
  dashboards: TmmscopeDashboard[];
  detail: string | null;
}

export interface ClusterTelemetry {
  cluster_id: number;
  cluster_name: string;
  context: string | null;
  streaming_as: string | null;
  streaming: boolean;
  /** The label came from an explicit binding rather than a name match. */
  label_pinned: boolean;
  available_labels: string[];
  /** Seconds since this cluster's most recent sample, streaming or not. */
  last_seen_age: number | null;
  dashboard_url: string | null;
}

/** Exactly one holds per cluster, and each names a different action. Only
 *  `stale_target` is the one that re-installing the exporter actually fixes. */
export type InjectionVerdict =
  | 'no_tmm'
  | 'not_installed'
  | 'settling'
  | 'streaming'
  | 'partial_delivery'
  | 'stale_target'
  | 'node_not_ready'
  | 'not_delivering';

export interface InjectionPod {
  pod: string;
  namespace: string;
  injected: boolean;
  /** In the pod template, or bolted on. Only an ephemeral one can be cleared
   *  by recreating the pod; a permanent one comes straight back. */
  kind: 'permanent' | 'ephemeral' | null;
  /** For a permanent sidecar, the workload whose pod template defines it —
   *  the only place it can actually be removed. Null for an ephemeral one. */
  owner: string | null;
  /** The node this pod is on, and whether Kubernetes reports it Ready. Null
   *  readiness is unknown, which must not render as "not ready". */
  node: string | null;
  node_ready: boolean | null;
  /** The remote-write URL baked in at injection. Immutable once injected. */
  pushing_to: string | null;
  stale: boolean;
  started_at: string | null;
  /** Seconds the exporter container has been running. Bounds "settling". */
  running_for: number | null;
  /** Prometheus holds live series for *this pod*. */
  streaming: boolean;
  /** The exporter's own last remote_write complaint — the line that names the
   *  actual cause. Populated only when something is wrong. */
  last_push_error: string | null;
  /** Why that line could not be read. The read goes through the kubelet, so a
   *  node that is gone breaks it for the same reason the metrics stopped. */
  log_unavailable: string | null;
}

export interface InjectionState {
  ok: boolean;
  cluster_id: number;
  tmm_pods: number;
  injected_pods: number;
  /** True only when *every* running f5-tmm pod carries the exporter. */
  injected: boolean;
  /** Some but not all — the state a pod restart leaves behind. */
  partial: boolean;
  pods: InjectionPod[];
  /** Injected and running, but pushing at a port nothing is listening on. */
  stale: boolean;
  stale_pods: number;
  stale_target: string | null;
  expected_port: number | null;
  /** Pods whose node Kubernetes reports NotReady. Not a telemetry fault. */
  not_ready_pods: number;
  not_ready_nodes: string[];
  /** Exporters that are part of the pod template rather than injected here. */
  permanent_pods: number;
  /** The workload that defines them, when there is one to name. */
  permanent_owner: string | null;
  streaming_pods: number;
  silent_pods: number;
  verdict: InjectionVerdict | null;
  verdict_detail: string | null;
  settle_seconds: number | null;
  added: string[];
  skipped: string[];
  deleted: string[];
  failed: { pod: string; error: string }[];
  remote_write_url: string | null;
  /** Which heuristic found the push address, shown when it picks wrong. */
  remote_write_derivation: string | null;
  cluster_label: string | null;
  detail: string | null;
}
