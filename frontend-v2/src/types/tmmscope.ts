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
  dashboard_url: string | null;
  inject_command: string;
  eject_command: string;
}

export interface InjectionPod {
  pod: string;
  namespace: string;
  injected: boolean;
  /** The remote-write URL baked in at injection. Immutable once injected. */
  pushing_to: string | null;
  stale: boolean;
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
