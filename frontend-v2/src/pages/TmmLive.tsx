/**
 * TMM Live — tmmscope's Grafana dashboard, embedded and scoped to one cluster.
 *
 * bnkscope orchestrates tmmscope rather than absorbing it: read the discovery
 * file, read Prometheus, embed the dashboard. `tmmscope up` is still a host
 * command, because starting the stack needs the Docker socket.
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
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, Copy, ExternalLink, Check, Download, RefreshCw, Terminal } from 'lucide-react';

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
  const settling = injectExporter.isSuccess;
  const { data: telemetry } = useClusterTelemetry(selectedCluster, theme, settling);
  const { data: injection } = useInjectionState(selectedCluster, settling);
  const bindLabel = useBindTmmscopeLabel(theme);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Metrics arrived — stop polling fast.
  useEffect(() => {
    if (settling && telemetry?.streaming) injectExporter.reset();
  }, [settling, telemetry?.streaming, injectExporter]);

  // Injected, but nothing is arriving yet. Derived from the data rather than
  // from "did I just click", so a reload mid-wait still explains itself.
  const awaitingMetrics =
    !!injection?.injected_pods && !!telemetry && !telemetry.streaming;

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
        subtitle="Real-time TMM telemetry from tmmscope"
        clusters={clusters}
        selectedClusterId={selectedCluster}
        onClusterChange={setSelectedCluster}
        onRefresh={() => void refetchStatus()}
        isRefreshing={isFetching}
      >
        {status?.running && (
          <Badge variant="success">
            <Activity className="mr-1 h-3 w-3" />
            telemetry up
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
          <details className="mt-4 text-xs text-muted-foreground">
            <summary className="cursor-pointer">Already using tmmscope?</summary>
            <div className="mt-3">
              <HostCommand command="tmmscope up" hint="That works too — bnkscope finds either:" />
            </div>
          </details>
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
            <Badge variant="success">streaming</Badge>
            <span>
              as <code className="font-mono text-foreground">{telemetry.streaming_as}</code>
              {telemetry.label_pinned && ' (bound manually)'}
            </span>
          </div>

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
                tmmscope is receiving telemetry, but none of it is labelled for this
                cluster. bnkscope matches on the kube context, its <code>user@cluster</code>{' '}
                half, and the namespace — <code>tmmscope inject --cluster</code> can use any
                name, so pick the right one if it is here:
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
              tmmscope is up but nothing is streaming to it yet. Add the exporter to this
              cluster's TMM pods:
            </p>
          )}

          <div className="mt-2 space-y-4">
            {injection?.stale ? (
              // Injected, running, and pushing into a closed socket. Without
              // saying so this is indistinguishable from never having injected
              // — the exporter looks healthy and no metrics ever arrive.
              <div className="space-y-3 rounded-md border border-warning/30 bg-warning/10 p-3">
                <p className="text-sm text-foreground">
                  The exporter is running in {injection.stale_pods} pod
                  {injection.stale_pods === 1 ? '' : 's'}, but pushing to{' '}
                  <code className="font-mono">{injection.stale_target}</code> — and
                  Prometheus is now on port{' '}
                  <code className="font-mono">{injection.expected_port}</code>.
                </p>
                <p className="text-xs text-muted-foreground">
                  The address is fixed when the exporter is injected and an ephemeral
                  container cannot be edited, so this needs the TMM pods recreated:
                  remove the exporter, then add it again. Removing restarts TMM and
                  drops traffic.
                </p>
                <Button variant="outline" size="sm" onClick={() => setConfirmRemove(true)}>
                  Remove the exporter — restarts TMM
                </Button>
              </div>
            ) : awaitingMetrics ? (
              // The exporter is in the pods but Prometheus has nothing yet.
              // Showing the inject button here is what got it pressed twice.
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
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              Adds the exporter as an <strong>ephemeral container</strong>, which does not
              restart TMM. It is transient: it does not survive a pod restart, and nothing
              re-adds it.
            </p>

            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Or run it on the host</summary>
              <div className="mt-3">
                <HostCommand
                  command={telemetry.inject_command}
                  hint="The tmmscope CLI does the same thing, and is the only way to get a durable sidecar:"
                />
                <p className="mt-2">
                  <code>--permanent</code> patches the Deployment instead. That persists
                  across pod restarts, but restarts TMM to do it — which is why it is not a
                  button here.
                </p>
              </div>
            </details>
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
            {injection?.injected_pods ? (
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
            ) : (
              <p className="text-sm text-muted-foreground">
                bnkscope did not inject this cluster's exporter, so there is nothing here to
                remove. If a durable sidecar was installed with{' '}
                <code>tmmscope inject --permanent</code>, remove it the same way:
              </p>
            )}
            {!injection?.injected_pods && (
              <HostCommand
                command={telemetry.eject_command}
                hint="Run on the host:"
              />
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

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <RefreshCw className="h-3 w-3" aria-hidden="true" />
        tmmscope runs independently of bnkscope — it works with neither this UI nor a
        cluster registered here.
      </p>
    </div>
  );
}
