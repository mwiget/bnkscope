/**
 * The bnkscope home page.
 *
 * bnk-forge's Command Center led with projects, modules, drift and the task
 * log — a deploy tool's front page. This one answers a different question,
 * the only one bnkscope exists for: **is anything wrong right now, and where?**
 *
 * So the ordering is by trouble, not by name. A cluster that is unreachable or
 * whose BNK is unhealthy sorts to the top; healthy ones fall to the bottom and
 * get one line each. On a good day the page is boring, which is the point.
 *
 * With no clusters registered, it hands over to discovery rather than showing
 * an empty grid — on a machine that talks to these clusters, "no clusters" is
 * almost always "not adopted yet".
 */
import type { ElementType } from 'react';
import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, HelpCircle, XCircle } from 'lucide-react';

import { SectionCard } from '@/components/ui/section-card';
import { SkeletonTable } from '@/components/ui/skeleton-table';
import { ErrorState } from '@/components/ui/error-state';
import { ClusterDiscoveryPanel } from '@/components/k8s/ClusterDiscoveryPanel';
import { ClusterStatusBadge } from '@/components/ui/ClusterStatusBadge';
import { useAllClusters } from '@/hooks/useK8s';
import { useConnectivity } from '@/hooks/useConnectivity';
import { useNotifications } from '@/hooks/useNotifications';
import { formatAge } from '@/lib/time-utils';
import { cn } from '@/lib/utils';
import type { K8sCluster } from '@/types';

// How a cluster sorts. Lower is more urgent — an operator opening bnkscope is
// looking for the top of this list, so "unknown" outranks "fine": something we
// cannot see is more interesting than something we can see is healthy.
const RANK = { unreachable: 0, unknown: 1, reachable: 2 } as const;
type Reachability = keyof typeof RANK;

interface RankedCluster {
  cluster: K8sCluster;
  reachability: Reachability;
}

function ClusterRow({ cluster, reachability }: RankedCluster) {
  const trouble = reachability !== 'reachable';

  return (
    <Link
      to="/kubernetes"
      className={cn(
        'flex items-center justify-between gap-4 rounded-lg border px-4 py-3 transition-colors',
        trouble
          ? 'border-destructive/30 bg-destructive/5 hover:bg-destructive/10'
          : 'border-border hover:bg-muted/50',
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <ClusterStatusBadge cluster={cluster} showStatusLabel />
          <span className="truncate font-medium text-foreground">{cluster.name}</span>
        </div>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {cluster.api_server ?? 'no API server'}
          {cluster.version && ` · v${cluster.version}`}
          {cluster.cloud_provider && cluster.cloud_provider !== 'on-prem' && (
            <> · {cluster.cloud_provider}</>
          )}
        </p>
      </div>

      <div className="flex flex-none items-center gap-3">
        {cluster.last_synced_at && (
          <span className="hidden text-xs text-muted-foreground sm:inline">
            seen {formatAge(cluster.last_synced_at)} ago
          </span>
        )}
        <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
    </Link>
  );
}

export default function CommandCenter() {
  const {
    data: clustersResponse,
    isLoading,
    isError,
    error,
    refetch,
  } = useAllClusters();
  const { states } = useConnectivity();
  const { data: notifications } = useNotifications();

  const clusters = useMemo(
    () => clustersResponse?.clusters ?? [],
    [clustersResponse?.clusters],
  );

  const ranked = useMemo<RankedCluster[]>(() => {
    const rows = clusters.map((cluster) => {
      const probe = states?.[`cluster:${cluster.id}`];
      const reachability: Reachability =
        probe?.state === 'reachable'
          ? 'reachable'
          : probe?.state === 'unreachable'
            ? 'unreachable'
            : 'unknown';
      return { cluster, reachability };
    });
    // Trouble first, then alphabetical so the order is stable between renders
    // rather than shuffling as probes land.
    return rows.sort(
      (a, b) =>
        RANK[a.reachability] - RANK[b.reachability] ||
        a.cluster.name.localeCompare(b.cluster.name),
    );
  }, [clusters, states]);

  const troubled = ranked.filter((r) => r.reachability !== 'reachable');
  const alerts = (notifications ?? []).filter(
    (n) => !n.is_read && (n.type === 'error' || n.type === 'warning'),
  );

  if (isError) {
    return <ErrorState error={error} onRetry={refetch} />;
  }

  if (isLoading) {
    return <SkeletonTable rows={4} columns={3} />;
  }

  if (clusters.length === 0) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">bnkscope</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Nothing registered yet. Clusters running BNK are picked up from your kubeconfig
            automatically — anything else can be added below.
          </p>
        </div>
        <ClusterDiscoveryPanel />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {troubled.length === 0 ? 'Everything is reachable' : 'Needs attention'}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {troubled.length === 0 ? (
            <>
              {clusters.length} cluster{clusters.length === 1 ? '' : 's'} responding.
            </>
          ) : (
            <>
              {troubled.length} of {clusters.length} cluster
              {clusters.length === 1 ? '' : 's'} not responding.
            </>
          )}
        </p>
      </header>

      {alerts.length > 0 && (
        <SectionCard title="Unread alerts" compact>
          <ul className="space-y-2">
            {alerts.slice(0, 5).map((n) => (
              <li key={n.id} className="flex items-start gap-2 text-sm">
                {n.type === 'error' ? (
                  <XCircle className="mt-0.5 h-4 w-4 flex-none text-destructive" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-warning" />
                )}
                <div className="min-w-0">
                  <span className="font-medium text-foreground">{n.title}</span>
                  <span className="text-muted-foreground"> — {n.message}</span>
                  <span className="ml-1 text-xs text-muted-foreground">
                    {formatAge(n.created_at)} ago
                  </span>
                </div>
              </li>
            ))}
          </ul>
          {alerts.length > 5 && (
            <p className="mt-2 text-xs text-muted-foreground">
              and {alerts.length - 5} more
            </p>
          )}
        </SectionCard>
      )}

      <SectionCard title="Clusters">
        <div className="space-y-2">
          {ranked.map((row) => (
            <ClusterRow key={row.cluster.id} {...row} />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Where to look next" compact>
        <div className="grid gap-3 sm:grid-cols-3">
          <NextStep
            to="/bnk"
            icon={CheckCircle2}
            title="BNK Health"
            body="TMM, gateways, traffic flow, and tmctl diagnostics."
          />
          <NextStep
            to="/kubernetes"
            icon={ArrowRight}
            title="Cluster browser"
            body="Pods, logs, exec, events — every resource on a cluster."
          />
          <NextStep
            to="/cnf"
            icon={HelpCircle}
            title="CNF resources"
            body="F5 custom resources and the conditions they report."
          />
        </div>
      </SectionCard>
    </div>
  );
}

function NextStep({
  to,
  icon: Icon,
  title,
  body,
}: {
  to: string;
  icon: ElementType;
  title: string;
  body: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-border p-3 transition-colors hover:bg-muted/50"
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        <span className="text-sm font-medium text-foreground">{title}</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{body}</p>
    </Link>
  );
}
