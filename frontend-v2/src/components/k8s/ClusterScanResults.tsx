/**
 * Cluster Scan Results
 *
 * Shows the results of a cluster prerequisite scan with:
 *   - Cluster info (version, distribution, node count)
 *   - Prerequisites status (cert-manager, Multus, SR-IOV, HugePages, storage, Gateway API)
 *   - BNK installation status (FLO, TMM, CNEInstance, VLANs)
 *   - Actionable recommendations (deploy/skip/upgrade/investigate)
 *
 * Visual pattern matches BNKHealthDashboard: card-based layout with severity badges.
 */

import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Server,
  Cpu,
  Network,
  Shield,
  HardDrive,
  Loader2,
  AlertCircle,
  ScanSearch,
  RefreshCw,
  Layers,
  Boxes,
  Zap,
  MemoryStick,
  Rocket,
  CircuitBoard,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useClusterScan,
  useClusterScanResult,
  useDeployHugePages,
} from '@/hooks/useK8s';
import { queryKeys } from '@/lib/queryKeys';
import type { BnkDeploymentSize, ClusterScanPrerequisites } from '@/types';
import { getPlatformProfileLabel } from '@/lib/platform-context';
import { HugePagesDeployDialog } from './HugePagesDeployDialog';
import {
  ScanCard,
  StatRow,
  StatusDot,
  statusConfig,
} from './scan';
import type { PrereqStatus } from './scan';

// ---- Types ----

interface ClusterScanResultsProps {
  clusterId: number;
  clusterName?: string;
}

// ---- Formatters ----

/**
 * Human-readable scan duration. Sub-second → "230 ms"; up to a minute →
 * "3.2 s"; longer → "1m 23s". Avoids the raw "52877ms" that required
 * mental math to parse.
 */
function formatScanDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
}

// ---- Status helpers ----

type RecSeverity = 'required' | 'recommended' | 'info';
type RecStatus = 'deploy' | 'skip' | 'upgrade' | 'investigate';

const OPTIONAL_PREREQ_KEYS = new Set<keyof ClusterScanPrerequisites>(['dpf', 'kamaji', 'existing_proxies']);

const recSeverityConfig: Record<RecSeverity, { color: string; bg: string; border: string }> = {
  required:    { color: 'text-destructive',      bg: 'bg-destructive/10', border: 'border-destructive/20' },
  recommended: { color: 'text-warning',          bg: 'bg-warning/10',     border: 'border-warning/20' },
  info:        { color: 'text-info',             bg: 'bg-info/10',        border: 'border-info/20' },
};

const recStatusConfig: Record<RecStatus, { label: string; color: string; bg: string }> = {
  deploy:      { label: 'Deploy',      color: 'text-success',          bg: 'bg-success/10' },
  skip:        { label: 'Skip',        color: 'text-muted-foreground', bg: 'bg-muted' },
  upgrade:     { label: 'Upgrade',     color: 'text-info',             bg: 'bg-info/10' },
  investigate: { label: 'Investigate', color: 'text-warning',          bg: 'bg-warning/10' },
};

// ---- Main component ----

export function ClusterScanResults({ clusterId, clusterName }: ClusterScanResultsProps) {
  const queryClient = useQueryClient();
  const scanMutation = useClusterScan();
  const deployHugePages = useDeployHugePages();
  const [hugePagesDialogOpen, setHugePagesDialogOpen] = useState(false);
  const handleConfirmHugePagesDeploy = (size: BnkDeploymentSize) => {
    deployHugePages.mutate(
      { clusterId, payload: { size } },
      {
        onSuccess: () => {
          setHugePagesDialogOpen(false);
          // Re-scan so the recommendation disappears once the Job lands.
          scanMutation.mutate({ clusterId, force: true });
        },
      },
    );
  };

  // Elapsed counter for the loading state — shows honest progress while the
  // scan runs. Big clusters with tens of MB of CRDs can take a minute; a
  // still spinner makes users wonder if it's stuck.
  const [scanElapsedSec, setScanElapsedSec] = useState(0);
  useEffect(() => {
    if (!scanMutation.isPending) {
      setScanElapsedSec(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(() => {
      setScanElapsedSec(Math.floor((Date.now() - start) / 1000));
    }, 500);
    return () => clearInterval(interval);
  }, [scanMutation.isPending]);

  // A mutation is not keyed by anything: `scanMutation.data` is just the last
  // result it produced, for whichever cluster that was. Switching clusters
  // used to leave every tile below showing the previous cluster's scan — and
  // worse, the stale data satisfied the auto-scan guard below, so no scan for
  // the new cluster was ever started. The node count in the header changed
  // because it comes from the cluster list, which *is* keyed.
  //
  // So the mutation's own state counts only when its variables name the
  // cluster currently on screen.
  const mutationClusterId =
    typeof scanMutation.variables === 'number'
      ? scanMutation.variables
      : scanMutation.variables?.clusterId;
  const isThisCluster = mutationClusterId === clusterId;

  // The cached result, read through a query rather than getQueryData so the
  // component re-renders when it lands. Keyed by cluster; never fetches on
  // its own (see useClusterScanResult) — the mutation populates it.
  const { data: cachedScan } = useClusterScanResult(clusterId);

  const scanData = (isThisCluster ? scanMutation.data : undefined) ?? cachedScan;
  const isScanning = scanMutation.isPending && isThisCluster;
  const scanFailed = scanMutation.isError && isThisCluster;

  // Auto-trigger the scan when there is nothing cached for THIS cluster.
  // Keeps the Dashboard view from landing on an empty "Scan Cluster"
  // call-to-action — the user picked a cluster, they want to see its
  // readiness *now*. Users can still click Rescan once results are shown.
  useEffect(() => {
    const cached = queryClient.getQueryData(queryKeys.k8s.clusters.scan(clusterId));
    if (!cached && !scanMutation.isPending) {
      scanMutation.mutate(clusterId);
    }
    // Intentionally only runs for this clusterId — mutation state is
    // captured by closure, and we don't want to re-scan on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterId]);

  // The Rescan button passes force=true so the backend bypasses its per-cluster
  // scan cache and runs a fresh scan. The auto-scan on mount uses the cached
  // path (force=false) so tab switches / page reloads stay instant.
  const handleScan = () => {
    scanMutation.mutate({ clusterId, force: true });
  };

  // --- No scan yet: show loading state (scan auto-runs on mount) ---
  if (!scanData && !scanFailed) {
    return (
      <div className="space-y-4">
        <div className={cn(
          'rounded-lg border p-8 text-center',
          'bg-card border-border',
        )}>
          {isScanning ? (
            <>
              <Loader2 className={cn('h-12 w-12 mx-auto mb-4 animate-spin', 'text-primary')} />
              <h3 className="text-lg font-semibold mb-2">
                Scanning cluster for BNK readiness
                <span className={cn('ml-2 font-mono text-sm tabular-nums', 'text-muted-foreground')}>
                  {scanElapsedSec}s
                </span>
              </h3>
              <p className={cn('text-sm max-w-lg mx-auto', 'text-muted-foreground')}>
                Checking {clusterName ? <span className="font-medium">{clusterName}</span> : 'this cluster'} for
                prerequisites (cert-manager, Multus, SR-IOV, HugePages, storage, Gateway API)
                and any existing F5 BIG-IP Next for Kubernetes installation.
                Usually a few seconds — results are cached for 10 minutes.
              </p>
            </>
          ) : (
            <>
              <ScanSearch className={cn('h-12 w-12 mx-auto mb-4', 'text-muted-foreground')} />
              <h3 className="text-lg font-semibold mb-2">Scan Cluster Prerequisites</h3>
              <p className={cn('text-sm mb-6 max-w-lg mx-auto', 'text-muted-foreground')}>
                Detect installed prerequisites and any existing F5 BNK installation on{' '}
                {clusterName ? <span className="font-medium">{clusterName}</span> : 'this cluster'}.
              </p>
              <Button onClick={handleScan} size="lg">
                <ScanSearch className="h-4 w-4 mr-2" />
                Scan Cluster
              </Button>
            </>
          )}
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (scanFailed && !scanData) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <AlertCircle className="h-10 w-10 text-destructive" />
        <p className="text-sm text-destructive">Cluster scan failed</p>
        <p className="text-xs text-muted-foreground">{(scanMutation.error as Error)?.message || 'Unknown error'}</p>
        <Button variant="outline" size="sm" onClick={handleScan}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Retry
        </Button>
      </div>
    );
  }

  // --- Scan results ---
  const { cluster_info, prerequisites, bnk_install, recommendations, scan_metadata } = scanData!;
  const detectedPlatformProfile = scanData?.platform_context?.detected_platform_profile;
  const isGenericOnpremBaseline = detectedPlatformProfile === 'generic_onprem';

  // Effective enabled-prereq IDs for this cluster (backend resolves the
  // user's per-cluster selection or falls back to defaults). Used to hide
  // status cards the user opted out of.
  const enabledPrereqs = new Set<string>(
    ((scanData as unknown as { enabled_prerequisites?: string[] })?.enabled_prerequisites) ?? [
      'cert-manager', 'multus', 'storage', 'gateway-api',
    ],
  );
  const showPrereq = (id: string) => enabledPrereqs.has(id);

  // Map prereq dict keys (cert_manager, gateway_api…) to canonical IDs
  // (cert-manager, gateway-api…) used by the per-cluster enabled set.
  const PREREQ_KEY_TO_ID: Record<string, string> = {
    cert_manager: 'cert-manager',
    multus: 'multus',
    sriov: 'sriov',
    hugepages: 'hugepages',
    storage: 'storage',
    gateway_api: 'gateway-api',
  };
  const isPrereqEnabledByKey = (key: string) => {
    const id = PREREQ_KEY_TO_ID[key];
    return id ? enabledPrereqs.has(id) : true;
  };

  // Overall summary should reflect required prerequisites only.
  // Optional prerequisites (DPF/Kamaji) stay visible as cards but should not
  // make the top-level readiness summary fail when they are missing.
  const requiredPrereqStatuses = Object.entries(prerequisites || {}).flatMap(([key, prereq]) => {
    if (OPTIONAL_PREREQ_KEYS.has(key as keyof ClusterScanPrerequisites)) {
      return [];
    }
    if (!isPrereqEnabledByKey(key)) {
      return [];
    }

    const status = (prereq as { status?: PrereqStatus } | undefined)?.status;
    return status ? [{ key, status }] : [];
  });

  // A missing prereq only counts toward the red "Prerequisites Missing" banner
  // if the backend emitted a recommendation for it with severity==='required'
  // and status==='deploy'. This prevents prereqs like Gateway API (severity
  // 'info', FLO auto-installs) from triggering the alarm banner.
  const requiredSeverityIds = new Set(
    (recommendations ?? [])
      .filter(
        (r) =>
          (r as { category?: string }).category === 'prerequisite' &&
          r.severity === 'required' &&
          r.status === 'deploy',
      )
      .map((r) => r.id),
  );

  const requiredMissingCount = requiredPrereqStatuses.filter(
    ({ key, status }) =>
      status === 'missing' &&
      requiredSeverityIds.has(PREREQ_KEY_TO_ID[key] ?? key),
  ).length;
  const requiredPartialCount = requiredPrereqStatuses.filter(({ status }) => status === 'partial').length;
  const requiredDetectedCount = requiredPrereqStatuses.filter(({ status }) => status === 'detected').length;

  const bnkStatus = bnk_install?.status as string;
  const overallStatus: PrereqStatus =
    bnkStatus === 'installed' && requiredMissingCount === 0 ? 'detected' :
    requiredMissingCount > 0 ? 'missing' :
    requiredPartialCount > 0 ? 'partial' : 'detected';

  const overallConfig = statusConfig[overallStatus];
  const OverallIcon = overallConfig.icon;

  const deployRecs = recommendations?.filter((r) => r.status === 'deploy') || [];
  const skipRecs = recommendations?.filter((r) => r.status === 'skip') || [];
  const investigateRecs = recommendations?.filter((r) => r.status === 'investigate') || [];

  return (
    <div className="space-y-6">
      {/* Overall Status Banner */}
      <div className={cn(
        'rounded-lg border p-4 flex items-center justify-between',
        overallConfig.bg,
        overallConfig.border,
      )}>
        <div className="flex items-center gap-3">
          <OverallIcon className={cn('h-6 w-6', overallConfig.color)} />
          <div>
            <h2 className="font-semibold text-lg">
              {overallStatus === 'detected' ? 'Cluster Ready' :
               overallStatus === 'missing' ? 'Prerequisites Missing' :
               overallStatus === 'partial' ? 'Partial Configuration' : 'Scan Complete'}
            </h2>
            <p className={cn('text-sm', 'text-muted-foreground')}>
              {cluster_info?.distribution} {cluster_info?.version}
              {' · '}
              {cluster_info?.nodes_ready}/{cluster_info?.node_count} nodes ready
              {' · '}
              {requiredDetectedCount}/{requiredPrereqStatuses.length} prerequisites detected
              {bnkStatus === 'installed' && ' · BNK installed'}
            </p>
            {isGenericOnpremBaseline && (
              <p className={cn('text-xs mt-1', 'text-muted-foreground')}>
                Baseline profile: {getPlatformProfileLabel(detectedPlatformProfile)} —
                current recommendations reflect kubeconfig-first, manual-friendly assumptions.
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {scan_metadata?.duration_ms && (
            <span className={cn('text-xs', 'text-muted-foreground')}>
              Scanned in {formatScanDuration(scan_metadata.duration_ms)}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleScan}
            disabled={isScanning}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isScanning && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {/* Recommendations Summary */}
      {(deployRecs.length > 0 || investigateRecs.length > 0) && (
        <div className={cn(
          'rounded-lg border p-5',
          'bg-card border-border',
        )}>
          <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" />
            Recommendations
          </h3>
          <div className="space-y-3">
            {[...deployRecs, ...investigateRecs].map((rec) => {
              const sevCfg = recSeverityConfig[rec.severity as RecSeverity] || recSeverityConfig.info;
              const statusCfg = recStatusConfig[rec.status as RecStatus] || recStatusConfig.investigate;
              const isHugePagesDeploy = rec.id === 'hugepages' && rec.status === 'deploy';
              return (
                <div
                  key={rec.id}
                  className={cn(
                    'flex items-start gap-3 p-3 rounded-lg border',
                    'border-border bg-muted/50',
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium">{rec.title}</span>
                      <Badge className={cn('text-[10px] h-5', sevCfg.bg, sevCfg.color, sevCfg.border)}>
                        {rec.severity}
                      </Badge>
                      {!isHugePagesDeploy && (
                        <Badge className={cn('text-[10px] h-5', statusCfg.bg, statusCfg.color)}>
                          {statusCfg.label}
                        </Badge>
                      )}
                    </div>
                    <p className={cn('text-xs', 'text-muted-foreground')}>
                      {rec.description}
                    </p>
                    {rec.module && (
                      <p className={cn('text-xs mt-1 font-mono', 'text-muted-foreground')}>
                        Module: {rec.module}
                      </p>
                    )}
                  </div>
                  {isHugePagesDeploy && (
                    <Button
                      size="sm"
                      variant="default"
                      onClick={() => setHugePagesDialogOpen(true)}
                      disabled={deployHugePages.isPending}
                      className="shrink-0"
                    >
                      {deployHugePages.isPending ? (
                        <>
                          <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                          Deploying
                        </>
                      ) : (
                        <>
                          <Rocket className="mr-1.5 h-3 w-3" />
                          Deploy
                        </>
                      )}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Detail Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">

        {/* Cluster Info */}
        <ScanCard
          title="Cluster"
          icon={Server}
          status={cluster_info?.nodes_ready === cluster_info?.node_count ? 'detected' : 'partial'}
        >
          <StatRow label="Distribution" value={cluster_info?.distribution || 'Unknown'} />
          <StatRow label="Version" value={cluster_info?.version || 'Unknown'} mono />
          <StatRow label="Nodes" value={cluster_info?.nodes_ready ?? 0} total={cluster_info?.node_count ?? 0} suffix="ready" />
          {cluster_info?.hp_nodes > 0 && (
            <StatRow label="HP Nodes (f5-tmm)" value={cluster_info.hp_nodes} status="detected" />
          )}
          <StatRow label="Namespaces" value={cluster_info?.namespaces ?? 0} />
          {cluster_info?.cloud_provider && (
            <StatRow label="Cloud" value={`${cluster_info.cloud_provider}${cluster_info.region ? ` (${cluster_info.region})` : ''}`} />
          )}
          {cluster_info?.hp_node_details?.length > 0 && (
            <div className={cn('pt-2 border-t', 'border-border')}>
              <p className={cn('text-xs mb-2', 'text-muted-foreground')}>
                High-Performance Nodes
              </p>
              {cluster_info.hp_node_details.map((n) => (
                <div key={n.name} className={cn(
                  'flex items-center justify-between text-xs',
                  'text-muted-foreground',
                )}>
                  <span className="font-mono truncate max-w-[160px]">{n.name}</span>
                  <span>{n.instance_type}</span>
                </div>
              ))}
            </div>
          )}
        </ScanCard>

        {/* cert-manager */}
        {showPrereq('cert-manager') && (
        <ScanCard
          title="cert-manager"
          icon={Shield}
          status={prerequisites?.cert_manager?.status || 'unknown'}
        >
          {prerequisites?.cert_manager?.version && (
            <StatRow label="Version" value={`v${prerequisites.cert_manager.version}`} mono />
          )}
          <StatRow
            label="CRDs"
            value={prerequisites?.cert_manager?.crd_count ?? 0}
            status={prerequisites?.cert_manager?.crds_installed ? 'detected' : 'missing'}
          />
          <StatRow
            label="Pods Running"
            value={prerequisites?.cert_manager?.pods?.total_running ?? 0}
            status={
              (prerequisites?.cert_manager?.pods?.total_running ?? 0) > 0 ? 'detected' : 'missing'
            }
          />
          {(prerequisites?.cert_manager?.pods?.total_running ?? 0) > 0 && (
            <>
              <StatRow label="  Controller" value={prerequisites.cert_manager.pods.controller} />
              <StatRow label="  Webhook" value={prerequisites.cert_manager.pods.webhook} />
              <StatRow label="  CA Injector" value={prerequisites.cert_manager.pods.cainjector} />
            </>
          )}
          {prerequisites?.cert_manager?.helm_release && (
            <div className={cn('text-xs', 'text-muted-foreground')}>
              Helm: {prerequisites.cert_manager.helm_release.name} ({prerequisites.cert_manager.helm_release.status})
            </div>
          )}
        </ScanCard>
        )}

        {/* Multus CNI */}
        {showPrereq('multus') && (
        <ScanCard
          title="Multus CNI"
          icon={Network}
          status={prerequisites?.multus?.status || 'unknown'}
        >
          <StatRow
            label="NAD CRD"
            value={prerequisites?.multus?.nad_crd_installed ? 'Installed' : 'Not Found'}
            status={prerequisites?.multus?.nad_crd_installed ? 'detected' : 'missing'}
          />
          <StatRow
            label="Running Pods"
            value={prerequisites?.multus?.running_pods ?? 0}
            status={
              (prerequisites?.multus?.running_pods ?? 0) > 0 ? 'detected' : 'missing'
            }
          />
          {prerequisites?.multus?.daemonset && (
            <>
              <StatRow
                label="DaemonSet"
                value={prerequisites.multus.daemonset.name}
              />
              <StatRow
                label="Ready / Desired"
                value={prerequisites.multus.daemonset.ready}
                total={prerequisites.multus.daemonset.desired}
              />
            </>
          )}
        </ScanCard>
        )}

        {/* SR-IOV */}
        {showPrereq('sriov') && (
        <ScanCard
          title="SR-IOV"
          icon={Cpu}
          status={prerequisites?.sriov?.status || 'unknown'}
        >
          <StatRow
            label="Device Plugin"
            value={prerequisites?.sriov?.device_plugin ? 'Installed' : 'Not Found'}
            status={prerequisites?.sriov?.device_plugin ? 'detected' : 'missing'}
          />
          <StatRow
            label="Nodes with VFs"
            value={prerequisites?.sriov?.nodes_with_vfs ?? 0}
          />
          <StatRow
            label="Total VFs"
            value={prerequisites?.sriov?.total_vfs ?? 0}
          />
          {prerequisites?.sriov?.device_plugin && (
            <div className={cn('text-xs font-mono', 'text-muted-foreground')}>
              {prerequisites.sriov.device_plugin.name}
              {' '}({prerequisites.sriov.device_plugin.ready}/{prerequisites.sriov.device_plugin.desired})
            </div>
          )}
          {prerequisites?.sriov?.node_details?.length > 0 && (
            <div className={cn('pt-2 border-t', 'border-border')}>
              <p className={cn('text-xs mb-2', 'text-muted-foreground')}>
                Node VF Resources
              </p>
              {prerequisites.sriov.node_details.map((n) => (
                <div key={n.name} className={cn(
                  'flex items-center justify-between text-xs mb-1',
                  'text-muted-foreground',
                )}>
                  <span className="font-mono truncate max-w-[140px]">{n.name}</span>
                  <span>{n.vf_count} VFs ({n.instance_type})</span>
                </div>
              ))}
            </div>
          )}
        </ScanCard>
        )}

        {/* HugePages */}
        {showPrereq('hugepages') && (
        <ScanCard
          title="HugePages"
          icon={MemoryStick}
          status={prerequisites?.hugepages?.status || 'unknown'}
        >
          <StatRow
            label="Nodes with HugePages"
            value={prerequisites?.hugepages?.nodes_with_hugepages ?? 0}
          />
          {prerequisites?.hugepages?.node_details?.map((n) => (
            <div key={n.name} className={cn(
              'flex items-center justify-between text-xs',
              'text-muted-foreground',
            )}>
              <span className="font-mono truncate max-w-[140px]">{n.name}</span>
              <div className="flex gap-2">
                {n.hugepages_2mi && n.hugepages_2mi !== '0' && (
                  <Badge variant="outline" className="text-[10px]">2Mi: {n.hugepages_2mi}</Badge>
                )}
                {n.hugepages_1gi && n.hugepages_1gi !== '0' && (
                  <Badge variant="outline" className="text-[10px]">1Gi: {n.hugepages_1gi}</Badge>
                )}
              </div>
            </div>
          ))}
          {(prerequisites?.hugepages?.nodes_with_hugepages ?? 0) === 0 && (
            <p className={cn('text-xs', 'text-muted-foreground')}>
              No HugePages configured. Consider enabling 2Mi or 1Gi HugePages on high-performance nodes for TMM.
            </p>
          )}
        </ScanCard>
        )}

        {/* Storage Classes */}
        {showPrereq('storage') && (
        <ScanCard
          title="Storage"
          icon={HardDrive}
          status={prerequisites?.storage?.status || 'unknown'}
        >
          <StatRow
            label="Storage Classes"
            value={prerequisites?.storage?.count ?? 0}
          />
          {prerequisites?.storage?.default && (
            <StatRow
              label="Default"
              value={prerequisites.storage.default}
              mono
            />
          )}
          {!prerequisites?.storage?.default && (prerequisites?.storage?.count ?? 0) > 0 && (
            <div className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 text-warning" />
              <span className="text-xs text-warning">No default storage class set</span>
            </div>
          )}
          {prerequisites?.storage?.classes?.length > 0 && (
            <div className={cn('pt-2 border-t', 'border-border')}>
              {prerequisites.storage.classes.map((sc) => (
                <div key={sc.name} className={cn(
                  'flex items-center justify-between text-xs mb-1',
                  'text-muted-foreground',
                )}>
                  <span className={cn('font-mono', sc.is_default && 'font-semibold text-primary')}>
                    {sc.name}{sc.is_default ? ' (default)' : ''}
                  </span>
                  <span className="truncate max-w-[160px] text-right">{sc.provisioner}</span>
                </div>
              ))}
            </div>
          )}
        </ScanCard>
        )}

        {/* Gateway API */}
        {showPrereq('gateway-api') && (
        <ScanCard
          title="Gateway API"
          icon={Layers}
          status={prerequisites?.gateway_api?.status || 'unknown'}
        >
          <StatRow label="CRDs Installed" value={prerequisites?.gateway_api?.crds_installed ?? 0} />
          <StatRow label="GatewayClasses" value={prerequisites?.gateway_api?.gatewayclasses ?? 0} />
          <StatRow label="Gateways" value={prerequisites?.gateway_api?.gateways ?? 0} />
          {prerequisites?.gateway_api?.api_versions?.length > 0 && (
            <div className="flex items-center gap-2">
              <span className={cn('text-xs', 'text-muted-foreground')}>API Versions:</span>
              <div className="flex gap-1">
                {prerequisites.gateway_api.api_versions.map((v: string) => (
                  <Badge key={v} variant="outline" className="text-[10px] font-mono">{v}</Badge>
                ))}
              </div>
            </div>
          )}
          {prerequisites?.gateway_api?.standard_crds_missing?.length > 0 && (
            <div className={cn('pt-2 border-t', 'border-border')}>
              <p className={cn('text-xs mb-1', 'text-muted-foreground')}>
                Missing standard CRDs:
              </p>
              {prerequisites.gateway_api.standard_crds_missing.map((crd: string) => (
                <div key={crd} className="flex items-center gap-1.5 text-xs text-warning">
                  <XCircle className="h-3 w-3" />
                  <span className="font-mono">{crd}</span>
                </div>
              ))}
            </div>
          )}
          {prerequisites?.gateway_api?.status === 'missing' && (
            <p className={cn('text-xs', 'text-muted-foreground')}>
              Gateway API CRDs are installed when BNK is deployed (FLO installs them automatically in the
              Forge deploy flow; a manual/helm install must install the Gateway API CRDs itself).
            </p>
          )}
        </ScanCard>
        )}

        {/* NVIDIA DPF — optional add-on, only render when actually present */}
        {prerequisites?.dpf && prerequisites.dpf.status !== 'missing' && (
          <ScanCard
            title="NVIDIA DPF"
            icon={CircuitBoard}
            status={prerequisites.dpf.status || 'unknown'}
            collapsible
            defaultOpen
          >
            <>
              {prerequisites.dpf.version && (
                  <StatRow label="Version" value={prerequisites.dpf.version} mono />
                )}
                <StatRow
                  label="CRDs Installed"
                  value={prerequisites.dpf.crds_installed}
                  status={prerequisites.dpf.crds_installed > 0 ? 'detected' : 'missing'}
                />
                <StatRow
                  label="Operator"
                  value={prerequisites.dpf.operator?.ready ? 'Ready' : prerequisites.dpf.operator?.configured ? 'Configured' : 'Not Found'}
                  status={prerequisites.dpf.operator?.ready ? 'detected' : prerequisites.dpf.operator?.configured ? 'partial' : 'missing'}
                />
                <StatRow
                  label="DPU Devices"
                  value={prerequisites.dpf.devices?.ready ?? 0}
                  total={prerequisites.dpf.devices?.total ?? 0}
                  suffix="ready"
                  status={(prerequisites.dpf.devices?.ready ?? 0) > 0 ? 'detected' : (prerequisites.dpf.devices?.total ?? 0) > 0 ? 'partial' : 'missing'}
                />
                <StatRow label="DPU Clusters" value={prerequisites.dpf.dpuclusters ?? 0} />
                <StatRow label="DPU Sets" value={prerequisites.dpf.dpusets ?? 0} />
                <StatRow label="BFB Images" value={prerequisites.dpf.bfbs ?? 0} />
                <StatRow label="DPU Services" value={prerequisites.dpf.dpuservices ?? 0} />

                {/* Operator conditions */}
                {prerequisites.dpf.operator?.conditions?.length > 0 && (
                  <div className={cn('pt-2 border-t', 'border-border')}>
                    <p className={cn('text-xs mb-2', 'text-muted-foreground')}>
                      Operator Conditions
                    </p>
                    {prerequisites.dpf.operator.conditions.map((c) => (
                      <div key={c.type} className={cn(
                        'flex items-center justify-between text-xs mb-1',
                        'text-muted-foreground',
                      )}>
                        <div className="flex items-center gap-1.5">
                          <StatusDot status={c.status === 'True' ? 'detected' : 'partial'} />
                          <span>{c.type}</span>
                        </div>
                        <span className="font-mono text-[10px]">{c.reason || c.status}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Core CRDs missing */}
                {prerequisites.dpf.core_crds_missing?.length > 0 && (
                  <div className={cn('pt-2 border-t', 'border-border')}>
                    <p className={cn('text-xs mb-1', 'text-muted-foreground')}>
                      Missing core CRDs:
                    </p>
                    {prerequisites.dpf.core_crds_missing.map((crd: string) => (
                      <div key={crd} className="flex items-center gap-1.5 text-xs text-warning">
                        <XCircle className="h-3 w-3" />
                        <span className="font-mono text-[10px]">{crd}</span>
                      </div>
                    ))}
                  </div>
                )}

              {prerequisites.dpf.helm_release && (
                <div className={cn('text-xs', 'text-muted-foreground')}>
                  Helm: {prerequisites.dpf.helm_release.name} ({prerequisites.dpf.helm_release.status})
                </div>
              )}
            </>
          </ScanCard>
        )}

        {/* Kamaji — optional add-on, only render when actually present */}
        {prerequisites?.kamaji && prerequisites.kamaji.status !== 'missing' && (
          <ScanCard
            title="Kamaji Control Plane"
            icon={Layers}
            status={prerequisites.kamaji.status || 'unknown'}
            collapsible
            defaultOpen
          >
            <>
              {prerequisites.kamaji.version && (
                  <StatRow label="Version" value={prerequisites.kamaji.version} mono />
                )}
                <StatRow
                  label="CRDs Installed"
                  value={prerequisites.kamaji.crds_installed}
                  status={prerequisites.kamaji.crds_installed > 0 ? 'detected' : 'missing'}
                />
                <StatRow
                  label="Pods Running"
                  value={prerequisites.kamaji.pods_running}
                  status={prerequisites.kamaji.pods_running > 0 ? 'detected' : 'missing'}
                />
                <StatRow
                  label="Tenant Control Planes"
                  value={prerequisites.kamaji.tenant_control_planes}
                  status={prerequisites.kamaji.tenant_control_planes > 0 ? 'detected' : 'missing'}
                />

                {/* Core CRDs missing */}
                {prerequisites.kamaji.core_crds_missing?.length > 0 && (
                  <div className={cn('pt-2 border-t', 'border-border')}>
                    <p className={cn('text-xs mb-1', 'text-muted-foreground')}>
                      Missing core CRDs:
                    </p>
                    {prerequisites.kamaji.core_crds_missing.map((crd: string) => (
                      <div key={crd} className="flex items-center gap-1.5 text-xs text-warning">
                        <XCircle className="h-3 w-3" />
                        <span className="font-mono text-[10px]">{crd}</span>
                      </div>
                    ))}
                  </div>
                )}

              {prerequisites.kamaji.helm_release && (
                <div className={cn('text-xs', 'text-muted-foreground')}>
                  Helm: {prerequisites.kamaji.helm_release.name} ({prerequisites.kamaji.helm_release.status})
                </div>
              )}
            </>
          </ScanCard>
        )}

        {/* BNK Installation */}
        <ScanCard
          title="F5 BNK Installation"
          icon={Boxes}
          status={
            bnk_install?.status === 'installed' ? 'detected' :
            bnk_install?.status === 'partial' ? 'partial' :
            bnk_install?.status === 'not_installed' ? 'missing' : 'unknown'
          }
          className="md:col-span-2"
        >
          {bnk_install?.status === 'not_installed' ? (
            <p className={cn('text-sm', 'text-muted-foreground')}>
              No F5 BNK components detected. Use the BNK stack to deploy a full installation.
            </p>
          ) : (
            <>
              {/* Install method */}
              {bnk_install?.install_shape && bnk_install.install_shape !== 'unknown' && (
                <StatRow
                  label="Install Method"
                  value={bnk_install.install_shape === 'flo' ? 'FLO deploy flow' : 'Helm / manual'}
                  status="detected"
                />
              )}

              {/* Namespaces */}
              <div className="flex items-center gap-3">
                <span className={cn('text-sm', 'text-muted-foreground')}>Namespaces</span>
                <div className="flex gap-1.5">
                  <Badge
                    variant="outline"
                    className={cn('text-xs gap-1',
                      bnk_install?.namespaces?.f5_operator
                        ? 'border-success/20 text-success'
                        : 'border-border text-muted-foreground'
                    )}
                  >
                    {bnk_install?.namespaces?.f5_operator ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                    f5-operator
                  </Badge>
                  <Badge
                    variant="outline"
                    className={cn('text-xs gap-1',
                      bnk_install?.namespaces?.f5_utils
                        ? 'border-success/20 text-success'
                        : 'border-border text-muted-foreground'
                    )}
                  >
                    {bnk_install?.namespaces?.f5_utils ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                    f5-utils
                  </Badge>
                </div>
              </div>

              {/* F5 CRDs */}
              <StatRow
                label="F5 CRDs"
                value={bnk_install?.crds?.total ?? 0}
                status={(bnk_install?.crds?.total ?? 0) > 0 ? 'detected' : 'missing'}
              />
              {bnk_install?.crds?.groups?.length > 0 && (
                <div className="flex flex-wrap gap-1 pl-4">
                  {bnk_install.crds.groups.map((g: string) => (
                    <Badge key={g} variant="outline" className="text-[10px] font-mono">{g}</Badge>
                  ))}
                </div>
              )}

              {/* FLO (only meaningful for a confirmed FLO deploy flow install) */}
              {bnk_install?.install_shape === 'flo' && (
                <>
                  <StatRow
                    label="FLO Operator"
                    value={bnk_install?.flo?.running ?? 0}
                    total={bnk_install?.flo?.pods ?? 0}
                    suffix="running"
                    status={
                      (bnk_install?.flo?.running ?? 0) > 0 ? 'detected' :
                      (bnk_install?.flo?.pods ?? 0) > 0 ? 'partial' : 'missing'
                    }
                  />
                  {bnk_install?.flo?.version && (
                    <StatRow label="FLO Version" value={bnk_install.flo.version} mono />
                  )}
                </>
              )}

              {/* TMM */}
              <StatRow
                label="TMM Pods"
                value={bnk_install?.tmm?.running ?? 0}
                total={bnk_install?.tmm?.pods ?? 0}
                suffix="running"
                status={
                  (bnk_install?.tmm?.running ?? 0) > 0 ? 'detected' :
                  (bnk_install?.tmm?.pods ?? 0) > 0 ? 'partial' : 'missing'
                }
              />
              {bnk_install?.tmm?.containers && (
                <StatRow
                  label="TMM Containers"
                  value={bnk_install.tmm.containers.containers}
                  suffix="ready"
                />
              )}

              {/* Controller + Analyzer */}
              <StatRow
                label="CNE Controller"
                value={bnk_install?.controller?.running ?? 0}
                total={bnk_install?.controller?.pods ?? 0}
                suffix="running"
              />
              {(bnk_install?.analyzer?.pods ?? 0) > 0 && (
                <StatRow
                  label="F5 Analyzer"
                  value={bnk_install?.analyzer?.running ?? 0}
                  total={bnk_install?.analyzer?.pods ?? 0}
                  suffix="running"
                />
              )}

              {/* CRD Installer (FLO deploy flow artifact — no crd-installer Job on helm/manual installs) */}
              {bnk_install?.install_shape === 'flo' && (
                <StatRow
                  label="CRD Installer"
                  value={bnk_install?.crd_installer?.completed ? 'Completed' : 'Pending'}
                  status={bnk_install?.crd_installer?.completed ? 'detected' : 'partial'}
                />
              )}

              {/* CNEInstance */}
              {bnk_install?.cne_instance && (
                <div className={cn('pt-2 border-t', 'border-border')}>
                  <p className={cn('text-xs mb-2', 'text-muted-foreground')}>
                    CNEInstance: {bnk_install.cne_instance.name}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(bnk_install.cne_instance.features || {}).map(([key, enabled]) => (
                      <Badge
                        key={key}
                        variant="outline"
                        className={cn(
                          'text-xs gap-1',
                          enabled
                            ? 'border-success/20 text-success bg-success/5'
                            : 'border-border text-muted-foreground bg-muted'
                        )}
                      >
                        {enabled ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                        {key}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* VLANs */}
              {bnk_install?.vlans?.length > 0 && (
                <div className={cn('pt-2 border-t', 'border-border')}>
                  <p className={cn('text-xs mb-2', 'text-muted-foreground')}>
                    VLANs
                  </p>
                  {bnk_install.vlans.map((v) => (
                    <div key={v.name} className={cn(
                      'flex items-center justify-between text-xs mb-1',
                      'text-muted-foreground',
                    )}>
                      <div className="flex items-center gap-2">
                        <StatusDot status={v.programmed ? 'detected' : 'partial'} />
                        <span className="font-mono">{v.name}</span>
                      </div>
                      <span className="font-mono">
                        {v.self_ips?.join(', ')} ({v.interfaces?.join(', ')})
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </ScanCard>
      </div>

      {/* All OK summary */}
      {skipRecs.length > 0 && deployRecs.length === 0 && investigateRecs.length === 0 && (
        <div className={cn(
          'rounded-lg border p-4 flex items-center gap-3',
          'bg-success/10 border-success/20',
        )}>
          <CheckCircle2 className="h-5 w-5 text-success" />
          <div>
            <p className="text-sm font-medium text-success">All prerequisites detected</p>
            <p className={cn('text-xs', 'text-muted-foreground')}>
              {skipRecs.length} components verified. Cluster is ready for BNK deployment.
            </p>
          </div>
        </div>
      )}

      {/* The "Deploy BNK" section lived here: node-readiness probing as step 1,
          an adaptive deployment plan as step 2. Both went with the deployment
          pipeline — bnkscope reports on a cluster, it does not install onto
          one, and a plan for work this tool cannot do is worse than no plan. */}

      {/* HugePages Deploy Dialog */}
      <HugePagesDeployDialog
        open={hugePagesDialogOpen}
        onOpenChange={setHugePagesDialogOpen}
        onConfirm={handleConfirmHugePagesDeploy}
        isLoading={deployHugePages.isPending}
      />
    </div>
  );
}

