/**
 * KubernetesV2 — Kubernetes Resource Explorer page
 *
 * FE-002: Decomposed from 1,069-line god-component into thin orchestrator.
 *
 * Sub-components live in ./kubernetes/:
 *   - K8sSidebar            — category navigation + cluster scan / export buttons
 *   - K8sResourceTable      — table with status logic & per-row action menus
 *   - K8sDetailPanel        — right-side resource detail (metadata, labels, Gateway/HTTPRoute)
 *   - K8sDialogs            — all Suspense-wrapped dialogs + API callbacks
 *   - k8s-status            — resource status determination logic
 *   - k8s-constants         — resource tree, calculateAge, getStatusColor (pre-existing)
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import { ResourcePageHeader } from '@/components/layout/ResourcePageHeader';
import { ResourceExplorerLayout } from '@/components/layout/ResourceExplorerLayout';
import { ResourceViewTabs } from '@/components/layout/ResourceViewTabs';
import { ResourceCategorySidebarTrigger } from '@/components/layout/ResourceCategorySidebar';
import {
  Container,
  Database,
  Server,
  Columns,
  Plus,
  RefreshCw,
  Cpu,
  LayoutDashboard,
  Wrench,
  ScanSearch,
  SlidersHorizontal,
  MoreVertical,
} from 'lucide-react';
import { useClusterNamespaces, useClusterResources, useClusterResourceSummary } from '@/hooks/useK8s';
import { useAllClusters } from '@/hooks/useK8sClusters';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { queryKeys } from '@/lib/queryKeys';
import { notify } from '@/lib/notify';
import type { K8sCluster } from '@/types';
import { parseApiError } from '@/lib/error-handler';
import { getPlatformProfileLabel } from '@/lib/platform-context';
import { SkeletonTable } from '@/components/ui/skeleton-table';
import { AddClusterDialog } from '@/components/k8s/AddClusterDialog';
import { ClusterDiscoveryPanel } from '@/components/k8s/ClusterDiscoveryPanel';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { useDebounce } from '@/hooks/useDebounce';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useSelectedCluster } from '@/hooks/useSelectedCluster';
import { ConnectivityGate } from '@/components/ConnectivityGate';
import { DEBOUNCE_MS } from '@/lib/constants';
import type { K8sResource } from '@/types';

import {
  K8sSidebar,
  K8sResourceTable,
  K8sDetailPanel,
  K8sDialogs,
  K8sClusterScanView,
  K8sDpfInfraView,
  isResourceUnhealthy,
  useK8sDialogs,
} from './kubernetes';
import type { ResourceAction } from './kubernetes';



// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function KubernetesV2() {
  const borderDefault = 'border-border';
  const bgCard = 'bg-card';
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── Selection State (persisted to localStorage) ────────────────────────
  // Strip ?project= once it's been consumed so refresh/back doesn't keep
  // re-asserting the param after the user picks a different project.
  useEffect(() => {
    if (searchParams.get('project')) {
      const next = new URLSearchParams(searchParams);
      next.delete('project');
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [selectedCluster, setSelectedCluster] = useSelectedCluster();
  const [selectedResourceType, setSelectedResourceType] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEYS.K8S_RESOURCE_TYPE) || 'pod';
  });
  // Default to a real namespace rather than 'all'. Cluster-wide mode is
  // expensive on real clusters (thousands of pods, MB of data per kind) and
  // it doesn't serve the deployment-focused goal of this tool — users should
  // opt in via the explicit "Load all namespaces" button in the sidebar.
  // Namespace selection is persisted per-cluster so switching clusters
  // doesn't carry a namespace that doesn't exist on the new cluster.
  const [selectedNamespace, setSelectedNamespace] = useState<string>(() => {
    const clusterId = localStorage.getItem(STORAGE_KEYS.K8S_CLUSTER);
    if (!clusterId) return 'default';
    const stored = localStorage.getItem(`${STORAGE_KEYS.K8S_NAMESPACE}:${clusterId}`);
    return stored || 'default';
  });
  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearchQuery = useDebounce(searchQuery, DEBOUNCE_MS.SEARCH);
  const [selectedResource, setSelectedResource] = useState<K8sResource | null>(null);

  // "Only unhealthy" view filter — hides healthy kinds in the sidebar and
  // healthy rows in the main table. Persisted across sessions.
  const [showOnlyUnhealthy, setShowOnlyUnhealthy] = useState<boolean>(() => {
    return localStorage.getItem(STORAGE_KEYS.K8S_UNHEALTHY_ONLY) === 'true';
  });

  // View mode — "dashboard" shows the BNK-deployment-focused scan view as the
  // default landing. "advanced" shows the generic resource browser (sidebar
  // tree + table). "migration" shows the proxy/CIS migration surface.
  const [viewMode, setViewMode] = useState<'dashboard' | 'advanced' | 'dpf'>(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.K8S_VIEW_MODE);
    if (stored === 'advanced') return stored;
    return 'dashboard';
  });

  // ── UI State ───────────────────────────────────────────────────────────
  const [expandedCategories, setExpandedCategories] = useState(['Workloads', 'Networking']);
  const [detailedView, setDetailedView] = useState(true);
  const [showClusterScan, setShowClusterScan] = useState(false);
  const [showAddCluster, setShowAddCluster] = useState(false);
  // Below `lg` the category tree is a drawer rather than a column.
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  // DPF Infrastructure removed from K8s page — lives in Fleet only



  // ── Dialog State (managed by useK8sDialogs hook) ───────────────────────
  const { state: dialogState, handleAction: handleDialogAction, openCreateDialog, setDialogOpen } = useK8sDialogs();

  // ── Persist selections to localStorage ─────────────────────────────────

  // Persist the selected resource type (same across clusters — Pods is Pods).
  useEffect(() => {
    if (selectedResourceType) {
      localStorage.setItem(STORAGE_KEYS.K8S_RESOURCE_TYPE, selectedResourceType);
    }
  }, [selectedResourceType]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.K8S_UNHEALTHY_ONLY, showOnlyUnhealthy ? 'true' : 'false');
  }, [showOnlyUnhealthy]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.K8S_VIEW_MODE, viewMode);
  }, [viewMode]);


  // Persist namespace per cluster. "default on cluster A, kube-system on B"
  // survives cluster switching without leaking a nonexistent namespace.
  useEffect(() => {
    if (selectedCluster !== null && selectedNamespace) {
      localStorage.setItem(
        `${STORAGE_KEYS.K8S_NAMESPACE}:${selectedCluster}`,
        selectedNamespace
      );
    }
  }, [selectedCluster, selectedNamespace]);

  // Restore the persisted namespace whenever the cluster changes (e.g. user
  // navigates away, comes back, the K8S_CLUSTER was already set).
  useEffect(() => {
    if (selectedCluster !== null) {
      const stored = localStorage.getItem(
        `${STORAGE_KEYS.K8S_NAMESPACE}:${selectedCluster}`
      );
      if (stored && stored !== selectedNamespace) {
        setSelectedNamespace(stored);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCluster]);

  // ── Data Fetching ──────────────────────────────────────────────────────
  // Clusters are a flat list now (bnkscope Phase 1) — no project scoping.
  const {
    data: allClustersResponse,
    isError: clustersError,
    error: clustersErrorData,
    isLoading: isClustersLoading,
    refetch: refetchClusters,
  } = useAllClusters();
  const clusters = useMemo(() => allClustersResponse?.clusters ?? [], [allClustersResponse?.clusters]);
  const visibleClusters = clusters;

  // Recorded by discovery when it finds the DPF operator on this cluster.
  const selectedClusterHasDpf = Boolean(
    clusters.find((c) => c.id === selectedCluster)?.meta_data?.has_dpf,
  );

  // The right landing view depends on which cluster you picked. DPF runs on
  // the infrastructure cluster; BNK runs on the Kamaji tenant. Landing a DPF
  // cluster on the BNK readiness Dashboard shows a scan for a deployment that
  // is not going to happen there, and the Dashboard tab is hidden on those
  // clusters for the same reason — so leaving viewMode on 'dashboard' would
  // also strand you on a tab that is no longer offered.
  //
  // 'advanced' is left alone in both directions: it is the one view that means
  // the same thing everywhere, and picking it is an explicit choice.
  useEffect(() => {
    if (viewMode === 'advanced') return;
    if (selectedClusterHasDpf && viewMode !== 'dpf') setViewMode('dpf');
    if (!selectedClusterHasDpf && viewMode === 'dpf') setViewMode('dashboard');
  }, [selectedCluster, selectedClusterHasDpf, viewMode]);

  // Select the first cluster when nothing valid is selected yet.
  useEffect(() => {
    if (clusters.length === 0) return;
    const stillValid = selectedCluster
      ? clusters.some((c: K8sCluster) => c.id === selectedCluster)
      : false;
    if (!stillValid) setSelectedCluster(clusters[0].id);
  }, [clusters, selectedCluster, setSelectedCluster]);

  const { data: namespacesResponse, isLoading: isNamespacesLoading, error: namespacesError } = useClusterNamespaces(selectedCluster ?? 0, {
    enabled: !!selectedCluster,
  });
  const namespaces = useMemo(() => namespacesResponse?.namespaces || [], [namespacesResponse?.namespaces]);

  useEffect(() => {
    if (namespaces.length === 0) return;
    // Keep an explicit "all namespaces" choice — user opted in via the
    // big-hammer button and we shouldn't second-guess them.
    if (selectedNamespace === 'all') return;
    // If the currently-selected namespace doesn't exist on this cluster
    // (stale per-cluster localStorage, or the initial 'default' fallback
    // when the cluster doesn't have a 'default' namespace), pick a sane
    // one: 'default' if present, else the first listed namespace.
    const names = namespaces.map((ns) => ns.name);
    if (!selectedNamespace || !names.includes(selectedNamespace)) {
      setSelectedNamespace(names.includes('default') ? 'default' : names[0]);
    }
  }, [namespaces, selectedNamespace]);

  // K8s resource fetching
  const { data: resourcesData, isFetching: isRefreshing, isLoading: isResourcesLoading, fetchStatus: resourcesFetchStatus } = useClusterResources(
    selectedCluster ?? 0,
    selectedResourceType,
    { namespace: selectedNamespace === 'all' ? undefined : selectedNamespace },
    {
      enabled: !!selectedCluster && !!selectedResourceType,
      pollingEnabled: false,
    }
  );
  const resources = useMemo(() => resourcesData?.resources || [], [resourcesData?.resources]);

  // Per-kind counts + unhealthy for the sidebar badges. Scoped to the same
  // namespace as the selected view so the dot/count reflect what the user
  // would actually see if they clicked in.
  const { data: resourceSummaryData, isLoading: isResourceSummaryLoading } = useClusterResourceSummary(
    selectedCluster ?? 0,
    selectedNamespace === 'all' ? undefined : selectedNamespace,
    { enabled: !!selectedCluster }
  );
  const resourceSummary = resourceSummaryData?.summary;


  const { data: nodeCount = 0 } = useQuery({
    queryKey: ['k8s', 'clusters', selectedCluster, 'node-count'],
    queryFn: () => api.getClusterNodeCount(selectedCluster!),
    enabled: !!selectedCluster,
    staleTime: 30000,
  });

  // ── Derived / Memoized ─────────────────────────────────────────────────
  const toggleCategory = useCallback((category: string) => {
    setExpandedCategories((prev) =>
      prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]
    );
  }, []);

  const filteredResources = useMemo(
    () =>
      resources.filter((r) => {
        if (!r.metadata?.name?.toLowerCase().includes(debouncedSearchQuery.toLowerCase())) {
          return false;
        }
        if (showOnlyUnhealthy && !isResourceUnhealthy(r, selectedResourceType)) {
          return false;
        }
        return true;
      }),
    [resources, debouncedSearchQuery, showOnlyUnhealthy, selectedResourceType]
  );


  const selectedClusterData = useMemo(
    () => visibleClusters.find((c: K8sCluster) => c.id === selectedCluster) ?? null,
    [visibleClusters, selectedCluster]
  );

  const isDetectedOcp = selectedClusterData?.detected_platform_profile === 'ocp';
  const nodeOperationsDisabledReason = useMemo(() => {
    if (!isDetectedOcp) {
      return null;
    }

    const hasMachineConfigConstraint =
      selectedClusterData?.platform_capabilities?.machine_config
      || selectedClusterData?.platform_constraints?.direct_node_package_mutation_not_supported;

    if (!hasMachineConfigConstraint) {
      return null;
    }

    return 'OpenShift worker node day-2 changes are typically managed via MachineConfig and operator workflows; direct cordon/uncordon/drain from Forge is intentionally disabled in this context.';
  }, [
    isDetectedOcp,
    selectedClusterData?.platform_capabilities?.machine_config,
    selectedClusterData?.platform_constraints?.direct_node_package_mutation_not_supported,
  ]);

  const createResourceDisabledReason = useMemo(() => {
    if (!isDetectedOcp || selectedResourceType !== 'ingress') {
      return null;
    }

    const hasRouteOrOperatorSignals =
      selectedClusterData?.platform_capabilities?.openshift_routes
      || selectedClusterData?.platform_constraints?.operator_required_for_networking;

    if (!hasRouteOrOperatorSignals) {
      return null;
    }

    return 'On OpenShift, north-south exposure is commonly Route/operator-managed. Forge does not create this platform-managed path directly; generic Ingress create is disabled for this cluster context.';
  }, [
    isDetectedOcp,
    selectedResourceType,
    selectedClusterData?.platform_capabilities?.openshift_routes,
    selectedClusterData?.platform_constraints?.operator_required_for_networking,
  ]);

  const ingressMutationBoundaryNotice = useMemo(() => {
    if (!isDetectedOcp) {
      return null;
    }

    if (selectedResourceType !== 'ingress') {
      return null;
    }

    const operatorManagedNetworking =
      selectedClusterData?.platform_constraints?.operator_required_for_networking
      || selectedClusterData?.platform_capabilities?.openshift_routes;

    if (!operatorManagedNetworking) {
      return null;
    }

    return 'Forge can mutate a selected Ingress object directly, but OpenShift north-south exposure is commonly Route/operator-managed and remains outside Forge platform mutation scope.';
  }, [
    isDetectedOcp,
    selectedResourceType,
    selectedClusterData?.platform_constraints?.operator_required_for_networking,
    selectedClusterData?.platform_capabilities?.openshift_routes,
  ]);

  // ── Handlers ───────────────────────────────────────────────────────────
  const handleRefresh = async () => {
    if (!selectedCluster) return;
    // The toolbar shows the refetch via isRefreshing (isFetching) — no toast needed.
    await queryClient.invalidateQueries({ queryKey: ['k8s', 'clusters', selectedCluster] });
  };


  const handleSelectResourceType = (type: string) => {
    setSelectedResourceType(type);
    setShowClusterScan(false);
  };

  /** Unified action handler for K8s resources — delegates restart inline, everything else to dialogs */
  const handleResourceAction = useCallback(
    async (action: ResourceAction) => {
      if (action.type === 'nodeOps' && nodeOperationsDisabledReason) {
        notify.warning(nodeOperationsDisabledReason, undefined, { category: 'cluster' });
        return;
      }

      if ((action.type === 'edit' || action.type === 'delete') && ingressMutationBoundaryNotice) {
        notify.warning(
          'Direct object mutation only',
          ingressMutationBoundaryNotice,
          { category: 'cluster' },
        );
      }

      if (action.type === 'restart') {
        if (selectedCluster && action.resource.metadata?.name && action.resource.metadata?.namespace) {
          try {
            await api.deleteK8sResource(
              selectedCluster,
              'pod',
              action.resource.metadata.name,
              { namespace: action.resource.metadata.namespace }
            );
            notify.success('Pod restarted (deleted, will be recreated by controller)', undefined, { category: 'cluster' });
            queryClient.invalidateQueries({
              queryKey: queryKeys.k8s.clusters.allResources(selectedCluster),
            });
          } catch (error) {
            const parsed = parseApiError(error);
            notify.error(parsed.title, parsed.message, { category: 'cluster' });
          }
        }
        return;
      }
      handleDialogAction(action);
    },
    [selectedCluster, queryClient, handleDialogAction, nodeOperationsDisabledReason, ingressMutationBoundaryNotice]
  );


  // ── Content count for header ───────────────────────────────────────────
  const contentCount = filteredResources.length;

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <ResourceExplorerLayout className="text-foreground">
      {/* Unified Command Bar */}
      <ResourcePageHeader
        title="Kubernetes"
        subtitle="Browse, inspect, and manage resources across your clusters"
        clusters={visibleClusters}
        selectedClusterId={selectedCluster}
        onClusterChange={setSelectedCluster}
        namespaces={namespaces}
        selectedNamespace={selectedNamespace}
        onNamespaceChange={setSelectedNamespace}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
        leading={
          viewMode === 'advanced' ? (
            <ResourceCategorySidebarTrigger
              label="Resources"
              onClick={() => setCategoriesOpen(true)}
            />
          ) : undefined
        }
      >
        <div className="flex items-center gap-4 px-4 py-1.5 rounded-lg text-xs hidden md:flex bg-muted/50">
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-success" />
            <span className="text-muted-foreground">
              {nodeCount} nodes
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Container className="h-3.5 w-3.5 text-primary" />
            <span className="text-muted-foreground">
              {contentCount} resources
            </span>
          </div>
        </div>

        {/* Filters — Advanced mode only (they only affect the raw resource tree). */}
        {viewMode === 'advanced' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-9 gap-1.5"
                disabled={!selectedCluster}
                title="Filters"
              >
                <SlidersHorizontal className="h-4 w-4" />
                {(showOnlyUnhealthy || selectedNamespace === 'all') && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Filters</DropdownMenuLabel>
              <DropdownMenuCheckboxItem
                checked={showOnlyUnhealthy}
                onCheckedChange={() => setShowOnlyUnhealthy((v) => !v)}
              >
                Only unhealthy
              </DropdownMenuCheckboxItem>
              <DropdownMenuCheckboxItem
                checked={selectedNamespace === 'all'}
                onCheckedChange={(checked) => {
                  if (checked) {
                    setSelectedNamespace('all');
                  } else {
                    const names = namespaces.map((ns) => ns.name);
                    setSelectedNamespace(names.includes('default') ? 'default' : names[0] || 'default');
                  }
                }}
              >
                Load all namespaces
              </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Overflow actions — Cluster Scan (D-020 relocation). */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-9 w-9 p-0"
              title="More actions"
              aria-label="More actions"
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {viewMode === 'advanced' && (
              <DropdownMenuItem
                onClick={() => setShowClusterScan(true)}
                disabled={!selectedCluster}
              >
                <ScanSearch className="mr-2 h-4 w-4" />
                Cluster Scan
              </DropdownMenuItem>
            )}
            {/* Reachable whether or not clusters exist. The discovery panel is
                the empty-state landing, but adding a *second* cluster needs a
                way in too — and this is also the only route to the manual
                kubeconfig form for a cluster that is not in ~/.kube/config. */}
            <DropdownMenuItem onClick={() => setShowAddCluster(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Add cluster
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </ResourcePageHeader>

      <AddClusterDialog open={showAddCluster} onOpenChange={setShowAddCluster} />

      {/* View-mode tab strip. DPF only appears on a cluster that actually runs
          the DPF operator — that is the *infra* cluster, a different one from
          the Kamaji tenant BNK lives on, so offering the tab everywhere would
          be an empty panel on most clusters. */}
      {selectedCluster && (
        <ResourceViewTabs
          aria-label="Kubernetes view mode"
          active={viewMode}
          onChange={(key) => setViewMode(key as 'dashboard' | 'advanced' | 'dpf')}
          tabs={[
            // Dashboard is BNK readiness, which a DPF infrastructure cluster
            // is not a candidate for — so it gives way to DPF there rather
            // than sitting alongside it reporting on a deployment that
            // belongs on the tenant cluster.
            ...(selectedClusterHasDpf
              ? [{ key: 'dpf', label: 'DPF', icon: Cpu, title: 'NVIDIA DPF infrastructure — DPUs, BFB images, DPUSets' }]
              : [{ key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, title: 'BNK readiness and health' }]),
            { key: 'advanced', label: 'Advanced', icon: Wrench, title: 'Generic Kubernetes resource browser for troubleshooting' },
          ]}
        />
      )}

      {/* Main Content Area */}
      <ResourceExplorerLayout.Body>
        {/* Left Sidebar — Advanced mode only. In Dashboard mode the BNK
            readiness view spans full width (no category tree needed). */}
        {viewMode === 'advanced' && (
          <K8sSidebar
            open={categoriesOpen}
            onOpenChange={setCategoriesOpen}
            clusterId={selectedCluster}
            selectedResourceType={selectedResourceType}
            onSelectResourceType={handleSelectResourceType}
            expandedCategories={expandedCategories}
            onToggleCategory={toggleCategory}
            filteredResourceCount={contentCount}
            showClusterScan={showClusterScan}
            resourceSummary={resourceSummary}
            isResourceSummaryLoading={isResourceSummaryLoading}
            showOnlyUnhealthy={showOnlyUnhealthy}
          />
        )}

        {/* Middle: Resource Table / Empty / Scan View */}
        <ResourceExplorerLayout.Content
          className="flex flex-col bg-muted/30"
        >
          {clustersError ? (
            <ErrorState error={clustersErrorData} onRetry={refetchClusters} />
          ) : !isClustersLoading && clusters.length === 0 ? (
            /* Nothing registered yet. Showing the discovery panel rather than
               an empty state is the point of Phase 5: on a machine that talks
               to these clusters, "no clusters" is almost always "not adopted
               yet", and the fix is one click away rather than a form.
               Gated on isLoading: the list is empty for a moment on every
               mount, and flashing a kubeconfig sweep during that moment both
               looks broken and costs a real probe of every context. */
            <div className="overflow-y-auto p-6">
              <ClusterDiscoveryPanel />
            </div>
          ) : !selectedCluster ? (
            <EmptyState
              icon={Server}
              title="No cluster selected"
              description="Select a cluster from the dropdown above to view and manage Kubernetes resources"
            />
          ) : viewMode === 'dpf' ? (
            <ConnectivityGate
              target={{
                type: 'cluster',
                id: selectedCluster,
                displayName: clusters?.find((c) => c.id === selectedCluster)?.name,
              }}
            >
              <K8sDpfInfraView clusterId={selectedCluster} />
            </ConnectivityGate>
          ) : viewMode === 'dashboard' || showClusterScan ? (
            /* Dashboard mode: BNK-deployment-focused scan view. Always the
               default landing when a cluster is selected, unless the user
               has explicitly flipped to Advanced mode in the sidebar. */
            <ConnectivityGate
              target={{
                type: 'cluster',
                id: selectedCluster,
                displayName: clusters?.find((c) => c.id === selectedCluster)?.name,
              }}
            >
              <K8sClusterScanView
                clusterId={selectedCluster}
                clusterName={clusters?.find((c) => c.id === selectedCluster)?.name}
              />
            </ConnectivityGate>
          ) : (
            /* ── Standard K8s Resource View ──────────────────────────── */
            <ConnectivityGate
              target={{
                type: 'cluster',
                id: selectedCluster,
                displayName: clusters?.find((c) => c.id === selectedCluster)?.name,
              }}
            >
              {/* Toolbar */}
              <div className="flex items-center justify-between px-4 py-2 border-b border-border">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold">
                    {selectedResourceType.charAt(0).toUpperCase() +
                      selectedResourceType.slice(1)}
                    s{' '}
                    <span className="text-muted-foreground">
                      ({filteredResources.length})
                    </span>
                  </h2>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDetailedView(!detailedView)}
                    className="h-8"
                  >
                    <Columns className="h-3.5 w-3.5 mr-1.5" />
                    {detailedView ? 'Detailed' : 'Compact'}
                  </Button>
                  <Button
                    size="sm"
                    className="h-8"
                    onClick={openCreateDialog}
                    disabled={!selectedCluster || !!createResourceDisabledReason}
                    title={createResourceDisabledReason ?? undefined}
                  >
                    <Plus className="h-3.5 w-3.5 mr-1.5" />
                    Create
                  </Button>
                </div>
              </div>

              {selectedNamespace === 'all' && (
                <div className="px-4 py-2 border-b border-border text-xs flex items-center justify-between gap-3 bg-warning/10 text-warning">
                  <span>
                    Showing resources from <strong>all namespaces</strong>. This is an
                    expensive cluster-wide fetch — scope back to a single namespace for faster loads.
                  </span>
                  <button
                    onClick={() => {
                      const names = namespaces.map((ns) => ns.name);
                      setSelectedNamespace(names.includes('default') ? 'default' : names[0] || 'default');
                    }}
                    className="underline underline-offset-2 hover:no-underline whitespace-nowrap font-medium"
                  >
                    Scope to current namespace
                  </button>
                </div>
              )}

              {createResourceDisabledReason && (
                <div className="px-4 py-2 border-b border-border text-xs text-warning">
                  {createResourceDisabledReason}
                </div>
              )}

              {ingressMutationBoundaryNotice && (
                <div className="px-4 py-2 border-b border-border text-xs text-info">
                  {ingressMutationBoundaryNotice}
                </div>
              )}

              {selectedResourceType === 'node' && nodeOperationsDisabledReason && (
                <div className="px-4 py-2 border-b border-border text-xs text-warning">
                  Node operations disabled for detected {getPlatformProfileLabel(selectedClusterData?.detected_platform_profile)} context: {nodeOperationsDisabledReason}
                </div>
              )}

              {/* Content Area */}
              {namespacesError ? (
                <div className="flex-1 overflow-auto p-4">
                  <div className="rounded-md border-l-2 border-l-destructive border border-border bg-card px-4 py-4">
                    <div className="flex items-start gap-3">
                      <Server className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-destructive">Failed to connect to cluster</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Could not list namespaces. The cluster may be unreachable, the kubeconfig may be invalid, or authentication may have failed.
                        </p>
                        <pre className="text-xs text-muted-foreground mt-2 p-2 bg-background/50 rounded border border-border overflow-auto max-h-32">
{(namespacesError as Error)?.message || String(namespacesError)}
                        </pre>
                      </div>
                    </div>
                  </div>
                </div>
              ) : isNamespacesLoading ? (
                <div className="flex-1 overflow-auto p-4">
                  <div className="flex items-center gap-3 rounded-md border border-info/20 bg-info/5 px-4 py-3">
                    <RefreshCw className="h-4 w-4 text-info animate-spin shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-info">Connecting to cluster...</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Listing namespaces via Kubernetes API</p>
                    </div>
                  </div>
                </div>
              ) : isResourcesLoading && resourcesFetchStatus === 'fetching' ? (
                <div className="flex-1 overflow-auto p-4 space-y-4">
                  <div className="flex items-center gap-3 rounded-md border border-info/20 bg-info/5 px-4 py-3">
                    <RefreshCw className="h-4 w-4 text-info animate-spin shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-info">Fetching {selectedResourceType} resources...</p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Querying cluster via Kubernetes API ({selectedNamespace === '' || selectedNamespace === 'all' ? 'all namespaces' : `namespace: ${selectedNamespace}`})
                      </p>
                    </div>
                  </div>
                  <SkeletonTable rows={6} columns={detailedView ? 7 : 4} />
                </div>
              ) : filteredResources.length === 0 ? (
                <EmptyState
                  icon={Database}
                  title={
                    showOnlyUnhealthy
                      ? 'No unhealthy resources'
                      : searchQuery
                        ? 'No matching resources'
                        : 'No resources found'
                  }
                  description={
                    showOnlyUnhealthy
                      ? `All ${selectedResourceType} resources in ${selectedNamespace === 'all' ? 'this cluster' : `namespace ${selectedNamespace}`} are healthy. Click the toggle again to see everything.`
                      : searchQuery
                        ? `No ${selectedResourceType} resources match "${searchQuery}"`
                        : `No ${selectedResourceType} resources in namespace ${selectedNamespace}. Try switching namespaces or checking filters.`
                  }
                  action={
                    showOnlyUnhealthy
                      ? {
                          label: 'Show all',
                          onClick: () => setShowOnlyUnhealthy(false),
                          variant: 'outline' as const,
                        }
                      : searchQuery
                        ? {
                            label: 'Clear Search',
                            onClick: () => setSearchQuery(''),
                            variant: 'outline' as const,
                          }
                        : undefined
                  }
                />
              ) : (
                <K8sResourceTable
                  resources={filteredResources}
                  selectedResourceType={selectedResourceType}
                  selectedResource={selectedResource}
                  detailedView={detailedView}
                  nodeOperationsDisabledReason={nodeOperationsDisabledReason}
                  networkMutationBoundaryNotice={ingressMutationBoundaryNotice}
                  onSelectResource={setSelectedResource}
                  onAction={handleResourceAction}
                  borderDefault={borderDefault}
                />
              )}
            </ConnectivityGate>
          )}
        </ResourceExplorerLayout.Content>

        {/* Right Panel: Resource Details */}
          <ResourceExplorerLayout.DetailPanel
            open={!!selectedResource}
            onOpenChange={(next) => !next && setSelectedResource(null)}
            label="Resource details"
            className={bgCard}
          >
            {selectedResource && (
                <K8sDetailPanel
                  resource={selectedResource}
                  selectedResourceType={selectedResourceType}
                  nodeOperationsDisabledReason={nodeOperationsDisabledReason}
                  networkMutationBoundaryNotice={ingressMutationBoundaryNotice}
                  onClose={() => setSelectedResource(null)}
                  onAction={handleResourceAction}
                />
            )}
          </ResourceExplorerLayout.DetailPanel>
      </ResourceExplorerLayout.Body>

      {/* K8s Dialogs */}
      <K8sDialogs
        clusterId={selectedCluster}
        selectedResourceType={selectedResourceType}
        selectedNamespace={selectedNamespace}
        errorContext={{
          detectedPlatformProfile: selectedClusterData?.detected_platform_profile,
          platformCapabilities: selectedClusterData?.platform_capabilities,
          platformConstraints: selectedClusterData?.platform_constraints,
        }}
        dialogState={dialogState}
        setDialogOpen={setDialogOpen}
        onResourceDeleted={() => setSelectedResource(null)}
      />

    </ResourceExplorerLayout>
  );
}
