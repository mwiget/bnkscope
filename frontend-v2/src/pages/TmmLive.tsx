/**
 * TMM Live — the TMM Grafana dashboard, embedded and scoped to one cluster.
 *
 * The stack is bnkscope's own: `bnkscope up` starts Prometheus and Grafana, and
 * that stays a host command because starting containers needs the Docker
 * socket. This page reads Prometheus and embeds the dashboard.
 *
 * Injection is not (D-036). It is one Kubernetes API call against a cluster we
 * already hold a client for, so it is a button. Removal is deliberately harder:
 * an ephemeral container cannot be taken out of a running pod, so clearing one
 * means recreating the TMM pods, which drops traffic. Inject is one click;
 * remove is a typed confirmation.
 *
 * "Injected" is not read from a config file here. It means Prometheus is
 * holding `f5tmm_up` series for this cluster's label right now, which is the
 * only claim that cannot be stale.
 *
 * Installed and delivering are separate facts, and the page keeps them
 * separate. An exporter that is present, running and pushing into a black hole
 * used to render as "waiting for the first metrics — this takes a few seconds"
 * indefinitely, which is the most confident possible way to be wrong. The
 * backend now returns a verdict naming *why* nothing is arriving, because only
 * one of the reasons (a stale target address) is fixed by re-installing.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  Copy,
  ExternalLink,
  Check,
  Download,
  RefreshCw,
  Terminal,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SectionCard } from '@/components/ui/section-card';
import { EmptyState } from '@/components/ui/empty-state';
import { ResourcePageHeader } from '@/components/layout/ResourcePageHeader';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useAllClusters } from '@/hooks/useK8s';
import {
  useBindTmmscopeLabel,
  useClusterTelemetry,
  useInjectExporter,
  useInjectionState,
  useRemoveInjection,
  useTmmscopeStatus,
} from '@/hooks/useTmmscope';
import { DestructiveConfirmDialog } from '@/components/ui/destructive-confirm-dialog';
import { useTheme } from '@/context/ThemeContext';
import { useSelectedCluster } from '@/hooks/useSelectedCluster';
import { notify } from '@/lib/notify';
import { formatDuration } from '@/lib/time-utils';
import type { InjectionState } from '@/types/tmmscope';

/** A command the operator runs on the host, with a copy button. */
function HostCommand({ command, hint }: { command: string; hint: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      notify.error('Could not copy to clipboard', undefined, { category: 'cluster' });
    }
  };

  return (
    <div>
      <p className="mb-2 text-sm text-muted-foreground">{hint}</p>
      <div className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
        <Terminal className="h-4 w-4 flex-none text-muted-foreground" aria-hidden="true" />
        <code className="flex-1 overflow-x-auto whitespace-pre font-mono text-[13px] text-foreground">
          {command}
        </code>
        <Button size="sm" variant="ghost" onClick={copy} aria-label="Copy command">
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}

/** What the exporter itself last said, verbatim — or why it could not be asked.
 *
 * The whole reason "installed but silent" was hard to diagnose is that every
 * symptom lives inside the pod. The exporter logs the reason on every failed
 * push — "connection refused", "context deadline exceeded", a 4xx — and one of
 * those lines is worth more than any amount of state bnkscope can infer from
 * outside.
 *
 * The read goes through the kubelet, though, so the one failure it cannot
 * describe is a node that is gone: the log request fails for the same reason
 * the metrics stopped. Saying so is better than the blank this used to render.
 */
function PushError({ pods }: { pods: InjectionState['pods'] }) {
  const failing = pods.filter((p) => p.last_push_error);
  // Kept apart from the exporter's own words on purpose: this is bnkscope
  // failing to read, not the exporter reporting. Conflating them would put a
  // sentence in the exporter's mouth at exactly the moment it cannot speak.
  const unreadable = pods.filter((p) => !p.last_push_error && p.log_unavailable);
  if (failing.length === 0 && unreadable.length === 0) return null;

  return (
    <div className="space-y-1">
      {failing.length > 0 && (
        <>
          <p className="text-xs font-medium text-muted-foreground">
            Last error from the exporter:
          </p>
          {failing.map((p) => (
            <pre
              key={p.pod}
              className="overflow-x-auto rounded border border-border bg-muted/30 px-2 py-1.5 font-mono text-[11px] text-muted-foreground"
            >
              {p.pod}: {p.last_push_error}
            </pre>
          ))}
        </>
      )}
      {unreadable.length > 0 && (
        <>
          <p className="text-xs font-medium text-muted-foreground">
            The exporter&apos;s log could not be read:
          </p>
          {unreadable.map((p) => (
            <pre
              key={p.pod}
              className="overflow-x-auto rounded border border-border bg-muted/30 px-2 py-1.5 font-mono text-[11px] text-muted-foreground"
            >
              {p.pod}: {p.log_unavailable}
            </pre>
          ))}
        </>
      )}
    </div>
  );
}

export default function TmmLive() {
  const { isDark } = useTheme();
  const theme = isDark ? 'dark' : 'light';

  const { data: clustersResponse } = useAllClusters();
  const clusters = useMemo(
    () => clustersResponse?.clusters ?? [],
    [clustersResponse?.clusters],
  );

  const [selectedCluster, setSelectedCluster] = useSelectedCluster();

  // Follow the cluster selection the rest of the app uses, so arriving here
  // from BNK Health lands on the cluster you were already looking at.
  useEffect(() => {
    if (clusters.length === 0) return;
    if (!clusters.some((c) => c.id === selectedCluster)) {
      setSelectedCluster(clusters[0].id);
    }
  }, [clusters, selectedCluster, setSelectedCluster]);


  const { data: status, refetch: refetchStatus, isFetching } = useTmmscopeStatus();
  const injectExporter = useInjectExporter();
  const removeInjection = useRemoveInjection();

  // Patching the pod and the first metrics arriving are seconds apart. Poll
  // fast across that gap, or the page sits unchanged for up to a SLOW interval
  // and the obvious move is to press inject again.
  const justInjected = injectExporter.isSuccess;
  const { data: telemetry } = useClusterTelemetry(selectedCluster, theme, justInjected);
  const { data: injection } = useInjectionState(selectedCluster, justInjected);
  const bindLabel = useBindTmmscopeLabel(theme);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Metrics arrived — stop polling fast.
  useEffect(() => {
    if (justInjected && telemetry?.streaming) injectExporter.reset();
  }, [justInjected, telemetry?.streaming, injectExporter]);

  // One verdict, from the backend, naming *why* metrics are or are not
  // arriving. Replaces a local `injected && !streaming` guess that could only
  // ever mean "still settling" — and so said so forever.
  // The backend verdict is the refined answer; `telemetry.streaming` is the
  // base fact it refines. Falling back matters when the injection probe has not
  // answered yet, or cannot: reporting a fault bnkscope has not established is
  // the same class of mistake as the optimism this replaces, pointed the other
  // way.
  const verdict =
    injection?.verdict ?? (telemetry?.streaming ? ('streaming' as const) : undefined);
  // A permanent sidecar lives in the pod template. Recreating the pod drops
  // dataplane traffic and brings the exporter straight back, so the remove
  // affordance must not be offered for one.
  const removable = !!injection?.injected_pods && injection.permanent_pods === 0;

  const cluster = clusters.find((c) => c.id === selectedCluster);
  // Recorded by discovery when it finds the DPF operator — the same signal
  // the Clusters page uses to land such a cluster on its DPF view.
  const clusterHasDpf = Boolean(cluster?.meta_data?.has_dpf);
  // `undefined` while the probe is in flight: only claim "no TMM" once the
  // backend has actually looked.
  const noTmmPods = injection?.tmm_pods === 0;

  return (
    <div className="space-y-4">
      <ResourcePageHeader
        title="TMM Live"
        subtitle="Real-time TMM telemetry"
        clusters={clusters}
        selectedClusterId={selectedCluster}
        onClusterChange={setSelectedCluster}
        onRefresh={() => void refetchStatus()}
        isRefreshing={isFetching}
      >
        {/* Two facts, two badges. One green "telemetry up" for the *stack*
            answering its own health check read as "telemetry is arriving" and
            stayed green through a cluster that had stopped delivering entirely.
            The stack badge is now neutral, and the green one is about this
            cluster's metrics. */}
        {status?.running && (
          <Badge variant="muted">
            <Activity className="mr-1 h-3 w-3" />
            stack up
          </Badge>
        )}
        {status?.running && telemetry && (
          <Badge
            variant={
              verdict === 'streaming'
                ? 'success'
                : verdict === 'settling'
                  ? 'info'
                  : verdict === 'no_tmm' || verdict === 'not_installed'
                    ? 'muted'
                    : 'warning'
            }
          >
            {verdict === 'streaming'
              ? 'streaming'
              : verdict === 'partial_delivery'
                ? `${injection?.silent_pods} of ${injection?.injected_pods} silent`
                : verdict === 'settling'
                  ? 'starting up'
                  : verdict === 'not_installed'
                    ? 'no exporter'
                    : verdict === 'no_tmm'
                      ? 'no TMM'
                      : typeof telemetry.last_seen_age === 'number'
                        ? `stopped ${formatDuration(telemetry.last_seen_age)} ago`
                        : 'not delivering'}
          </Badge>
        )}
        {status?.grafana_url && (
          <Button size="sm" variant="outline" asChild>
            {/* /dashboards, not /. Grafana's home for an anonymous Viewer is a
                welcome screen, and the TMM dashboards sit in a folder — landing
                there looks like an empty Grafana with nothing to select. */}
            <a
              href={`${status.grafana_url.replace(/\/$/, '')}/dashboards`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="mr-1 h-4 w-4" />
              Open Grafana
            </a>
          </Button>
        )}
      </ResourcePageHeader>

      {/* 1. The stack is not running at all. */}
      {status && !status.running && (
        <SectionCard title="No telemetry stack is running">
          <p className="mb-4 text-sm text-muted-foreground">{status.detail}</p>
          <HostCommand
            command="bnkscope up --telemetry"
            hint="Start bnkscope's own Prometheus + Grafana:"
          />
          <p className="mt-4 text-xs text-muted-foreground">
            Starting containers needs the Docker socket, which an API with no authentication
            in front of it should not have — so this one stays a command you run.
          </p>
        </SectionCard>
      )}

      {/* 2. Stack up, this cluster streaming: the dashboard. */}
      {status?.running && telemetry?.streaming && telemetry.dashboard_url && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>
              as <code className="font-mono text-foreground">{telemetry.streaming_as}</code>
              {telemetry.label_pinned && ' (bound manually)'}
            </span>
          </div>

          {/* The cluster is streaming, but not from every pod. This is the
              state a reinstalled node leaves behind: its siblings keep the
              cluster-level answer green while it delivers nothing, and the
              dashboard below is simply missing a node with no hint of it. */}
          {verdict === 'partial_delivery' && injection && (
            <div className="space-y-3 rounded-md border border-warning/30 bg-warning/10 p-3">
              <p className="flex items-start gap-2 text-sm text-foreground">
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 flex-none text-warning"
                  aria-hidden="true"
                />
                <span>{injection.verdict_detail}</span>
              </p>
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {injection.pods
                  .filter((p) => p.injected && !p.streaming)
                  .map((p) => (
                    <li key={p.pod} className="font-mono">
                      {p.pod} — running {formatDuration(p.running_for)}
                    </li>
                  ))}
              </ul>
              <PushError pods={injection.pods} />
            </div>
          )}

          <div className="overflow-hidden rounded-lg border border-border">
            <iframe
              // Remounts on cluster or theme change; Grafana reads both from
              // the URL and will not pick up a change to it in place.
              key={telemetry.dashboard_url}
              src={telemetry.dashboard_url}
              title={`TMM Real-Time — ${telemetry.cluster_name}`}
              className="h-[calc(100vh-16rem)] w-full border-0 bg-background"
              // The dashboard is same-machine, but it is still a separate
              // origin: give it no more than it needs to render.
              sandbox="allow-scripts allow-same-origin allow-popups"
              referrerPolicy="no-referrer"
              loading="lazy"
            />
          </div>
        </>
      )}

      {/* 3a. Stack up, but this cluster has no TMM to stream from. Checked
          before anything else here: every affordance below is about getting
          an exporter into an f5-tmm pod, and there is not one. */}
      {status?.running && telemetry && !telemetry.streaming && noTmmPods && (
        <SectionCard title={`No TMM on ${telemetry.cluster_name}`}>
          <p className="text-sm text-muted-foreground">
            {clusterHasDpf ? (
              <>
                This is a DPF infrastructure cluster — it runs the DPF operator and
                the DPUs. TMM runs on the Kamaji tenant cluster, which is where the
                exporter belongs. There is nothing to stream from here.
              </>
            ) : (
              <>
                bnkscope found no running <code className="font-mono">f5-tmm</code>{' '}
                pods on this cluster, so there is nothing to inject the exporter into.
                It looks for pods labelled{' '}
                <code className="font-mono">app=f5-tmm</code>.
              </>
            )}
          </p>
          {clusterHasDpf && (
            <p className="mt-3 text-sm text-muted-foreground">
              Its DPUs, BFB images and DPUSets are under{' '}
              <Link to="/kubernetes" className="underline underline-offset-2">
                Clusters &rsaquo; DPF
              </Link>
              .
            </p>
          )}
        </SectionCard>
      )}

      {/* 3. Stack up, nothing streaming under a label we recognise. */}
      {status?.running && telemetry && !telemetry.streaming && !noTmmPods && (
        <SectionCard title={`${telemetry.cluster_name} is not streaming`}>
          {telemetry.available_labels.length > 0 ? (
            <>
              <p className="mb-3 text-sm text-muted-foreground">
                Prometheus is receiving telemetry, but none of it is labelled for this
                cluster. bnkscope matches on the kube context, its <code>user@cluster</code>{' '}
                half, and the namespace — an exporter can be injected under any label at
                all, so pick the right one if it is here:
              </p>
              <Select
                onValueChange={(label) =>
                  bindLabel.mutate({ clusterId: telemetry.cluster_id, label })
                }
              >
                <SelectTrigger className="w-72">
                  <SelectValue placeholder="Bind to a streaming label…" />
                </SelectTrigger>
                <SelectContent>
                  {telemetry.available_labels.map((label) => (
                    <SelectItem key={label} value={label}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-4 text-sm text-muted-foreground">
                Or add the exporter to this cluster:
              </p>
            </>
          ) : (
            <p className="mb-3 text-sm text-muted-foreground">
              The telemetry stack is up but nothing is streaming to it yet. Add the
              exporter to this cluster's TMM pods:
            </p>
          )}

          {/* It streamed once and stopped. Without this the page reads the
              same as one that never streamed at all, which sends you looking
              for a missing exporter that is in fact installed and running. */}
          {typeof telemetry.last_seen_age === 'number' && (
            <p className="mb-3 text-sm text-foreground">
              This cluster last delivered metrics{' '}
              <strong>{formatDuration(telemetry.last_seen_age)} ago</strong>
              {telemetry.streaming_as && (
                <>
                  , as <code className="font-mono">{telemetry.streaming_as}</code>
                </>
              )}
              .
            </p>
          )}

          <div className="mt-2 space-y-4">
            {verdict === 'stale_target' && injection ? (
              // Injected, running, and pushing into a closed socket. Without
              // saying so this is indistinguishable from never having injected
              // — the exporter looks healthy and no metrics ever arrive. This
              // is the one case re-installing actually fixes.
              <div className="space-y-3 rounded-md border border-warning/30 bg-warning/10 p-3">
                <p className="text-sm text-foreground">
                  The exporter is running in {injection.stale_pods} pod
                  {injection.stale_pods === 1 ? '' : 's'}, but pushing to{' '}
                  <code className="font-mono">{injection.stale_target}</code> — and
                  Prometheus is now on port{' '}
                  <code className="font-mono">{injection.expected_port}</code>.
                </p>
                <p className="text-xs text-muted-foreground">
                  The address is fixed when the exporter is injected and cannot be
                  edited in place, so this needs the TMM pods recreated: remove the
                  exporter, then add it again. Removing restarts TMM and drops
                  traffic.
                </p>
                <PushError pods={injection.pods} />
                {removable ? (
                  <Button variant="outline" size="sm" onClick={() => setConfirmRemove(true)}>
                    Remove the exporter — restarts TMM
                  </Button>
                ) : (
                  /* Permanent: the push URL is an env var in the pod template,
                     so the fix is to correct it there and roll the workload —
                     not to inject a second exporter over the top of this one. */
                  <p className="text-xs text-muted-foreground">
                    The exporter here is part of the TMM pod template, so the address
                    is set where that template is defined
                    {injection.permanent_owner ? (
                      <>
                        :{' '}
                        <code className="font-mono text-foreground">
                          {injection.permanent_owner}
                        </code>
                      </>
                    ) : null}
                    . Point it at port{' '}
                    <code className="font-mono">{injection.expected_port}</code> and
                    roll it.
                  </p>
                )}
              </div>
            ) : verdict === 'node_not_ready' && injection ? (
              // Not a telemetry fault at all. The pods still say Running —
              // the control plane cannot know a container died, only that the
              // kubelet went quiet — so every other reading here looks healthy
              // and the page used to send the operator after a network path.
              <div className="space-y-3 rounded-md border border-warning/30 bg-warning/10 p-3">
                <p className="flex items-start gap-2 text-sm text-foreground">
                  <AlertTriangle
                    className="mt-0.5 h-4 w-4 flex-none text-warning"
                    aria-hidden="true"
                  />
                  <span>{injection.verdict_detail}</span>
                </p>
                <PushError pods={injection.pods} />
                <p className="text-xs text-muted-foreground">
                  Bring the node{injection.not_ready_nodes.length === 1 ? '' : 's'} back
                  and the exporter resumes on its own — it is part of the pod, and the
                  pod comes back with the node. Nothing needs re-installing.
                </p>
              </div>
            ) : verdict === 'not_delivering' && injection ? (
              // Installed, running, pushing at the right address, and nothing
              // arrives. Re-installing changes nothing — the pod cannot reach
              // the collector — so this state deliberately offers no button
              // that pretends otherwise.
              <div className="space-y-3 rounded-md border border-warning/30 bg-warning/10 p-3">
                <p className="flex items-start gap-2 text-sm text-foreground">
                  <AlertTriangle
                    className="mt-0.5 h-4 w-4 flex-none text-warning"
                    aria-hidden="true"
                  />
                  <span>{injection.verdict_detail}</span>
                </p>
                <PushError pods={injection.pods} />
                <p className="text-xs text-muted-foreground">
                  Check the path from the TMM pod to{' '}
                  <code className="font-mono">
                    {injection.pods.find((p) => p.pushing_to)?.pushing_to ?? 'the collector'}
                  </code>
                  : the exporter shares the TMM pod's network namespace, so it egresses
                  the way TMM does. A node that reaches Prometheus while its TMM pod
                  does not is a dataplane routing problem, not a telemetry one.
                </p>
              </div>
            ) : verdict === 'settling' && injection ? (
              // The exporter is in the pods but Prometheus has nothing yet.
              // Showing the inject button here is what got it pressed twice.
              // Bounded by the backend: past the settle window this becomes one
              // of the two states above instead of spinning forever.
              <div className="flex flex-wrap items-center gap-3">
                <RefreshCw
                  className="h-4 w-4 animate-spin text-muted-foreground"
                  aria-hidden="true"
                />
                <span className="text-sm text-muted-foreground" role="status">
                  Exporter running in {injection.injected_pods} of{' '}
                  {injection.tmm_pods} f5-tmm pod
                  {injection.tmm_pods === 1 ? '' : 's'} — waiting for the first
                  metrics. This takes a few seconds.
                </span>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  onClick={() =>
                    injectExporter.mutate({ clusterId: telemetry.cluster_id })
                  }
                  disabled={injectExporter.isPending || injection?.tmm_pods === 0}
                >
                  {injectExporter.isPending ? (
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                  )}
                  {injectExporter.isPending ? 'Injecting…' : 'Add the exporter'}
                </Button>
                {injection !== undefined && (
                  <span className="text-sm text-muted-foreground">
                    {injection.tmm_pods === 0
                      ? 'No running f5-tmm pods on this cluster.'
                      : `${injection.tmm_pods} f5-tmm pod${injection.tmm_pods === 1 ? '' : 's'}`}
                    {injection.partial &&
                      ` — ${injection.injected_pods} already carry it`}
                  </span>
                )}
                {/* Belongs with the button it describes. Under
                    `not_delivering` the exporter is already there and working,
                    and offering to add another is the same wrong answer the old
                    spinner gave, in more words. */}
                <p className="w-full text-xs text-muted-foreground">
                  Adds the exporter as an <strong>ephemeral container</strong>, which does
                  not restart TMM. It is transient: it does not survive a pod restart, and
                  nothing re-adds it.
                </p>
              </div>
            )}
          </div>
        </SectionCard>
      )}

      {/* 4. Nothing to show at all. */}
      {clusters.length === 0 && (
        <EmptyState
          icon={Activity}
          title="No clusters registered"
          description="Add a cluster first — TMM Live watches telemetry from a cluster bnkscope knows about."
        />
      )}

      {status?.running && telemetry?.streaming && cluster && (
        <details className="rounded-lg border border-border p-4">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            Stop streaming from this cluster
          </summary>
          <div className="mt-3 space-y-4">
            {removable ? (
              <>
                <p className="text-sm text-muted-foreground">
                  An ephemeral container cannot be removed from a running pod. Clearing the
                  exporter means <strong>recreating the f5-tmm pod(s)</strong>, which drops
                  dataplane traffic while they come back.
                </p>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setConfirmRemove(true)}
                  disabled={removeInjection.isPending}
                >
                  Remove the exporter — restarts TMM
                </Button>
              </>
            ) : injection?.permanent_pods ? (
              /* Not bnkscope's to remove, and not one command's either: a
                 permanent sidecar comes from whatever built the cluster, so
                 the only useful thing to say is which workload defines it. */
              <p className="text-sm text-muted-foreground">
                This cluster&apos;s exporter is a permanent sidecar in the TMM pod
                template — recreating the pods would only bring it back. Remove it
                where the template is defined
                {injection.permanent_owner ? (
                  <>
                    :{' '}
                    <code className="font-mono text-foreground">
                      {injection.permanent_owner}
                    </code>
                    .
                  </>
                ) : (
                  ', in whatever installed it.'
                )}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                bnkscope did not inject this cluster&apos;s exporter, so there is
                nothing here to remove.
              </p>
            )}
          </div>
        </details>
      )}

      {cluster && (
        <DestructiveConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title="Restart TMM to remove the exporter?"
          description="Ephemeral containers cannot be removed in place. The only way to clear one is to recreate the pod."
          confirmText={cluster.name}
          warningItems={[
            `${injection?.injected_pods ?? 0} f5-tmm pod(s) will be deleted and recreated`,
          ]}
          consequences={[
            'Dataplane traffic is dropped while the pods restart',
            'Telemetry for this cluster stops',
          ]}
          // `warning`, not `danger`: the confirm button in danger mode reads
          // "Delete Permanently", and nothing here is deleted permanently — the
          // pods come back, without the exporter.
          variant="warning"
          isPending={removeInjection.isPending}
          onConfirm={() => {
            removeInjection.mutate({ clusterId: cluster.id });
            setConfirmRemove(false);
          }}
        />
      )}

    </div>
  );
}
