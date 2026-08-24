import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { K8sClusterCreateRequest, K8sClusterUpdateRequest } from '@/types';
import { QUERY_STALE_TIME, POLL_INTERVALS } from '@/lib/constants';
import { notify } from '@/lib/notify';
import { queryKeys } from '@/lib/queryKeys';
import { useAppMutation } from '@/hooks/lib/useAppMutation';

// Stops polling when the tab is hidden. Mirrors the pattern used by
// useSystem / useFleet / ProcessMetricsBar so background tabs don't
// hammer the backend.
function useDocumentVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(() =>
    typeof document !== 'undefined' ? !document.hidden : true
  );
  useEffect(() => {
    const handler = () => setIsVisible(!document.hidden);
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);
  return isVisible;
}

// Resource Types
export function useK8sResourceTypes() {
  return useQuery({
    queryKey: queryKeys.k8s.resourceTypes(),
    queryFn: api.getK8sResourceTypes,
    staleTime: QUERY_STALE_TIME.VERY_LONG, // Cache for 5 minutes (resource types don't change often)
  });
}

// ── Local kubeconfig discovery ──────────────────────────────────────────────

/**
 * Contexts found in the operator's own kubeconfig.
 *
 * The GET is not a read: it re-probes every context and registers the ones
 * carrying BNK. That is deliberate — "show me what is out there" and "pick up
 * what is out there" are the same action for a local tool. It is idempotent,
 * so refetching costs a sweep, never a duplicate.
 *
 * Not polled. A sweep dials every context in the file, including ones behind a
 * VPN that is down, so it runs when asked and every 10 minutes on the backend's
 * own schedule.
 */
export function useDiscovery(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.k8s.discovery,
    queryFn: api.getDiscovery,
    enabled: options?.enabled ?? true,
    staleTime: QUERY_STALE_TIME.DEFAULT,
    refetchOnWindowFocus: false,
  });
}

/** Register one discovered context that discovery did not adopt on its own. */
export function useAdoptContext() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: (context: string) => api.adoptContext(context),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.clusters.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.discovery });
      const added = data.candidates[0];
      notify.success(
        `Added ${added?.context ?? 'cluster'}`,
        added?.has_bnk
          ? 'BNK components were found on this cluster.'
          : 'No BNK components found yet — the cluster list will pick them up once they appear.',
        { category: 'cluster' },
      );
    },
  });
}

// Clusters
export function useAllClusters() {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.all,
    queryFn: api.getAllClusters,
    staleTime: QUERY_STALE_TIME.DEFAULT, // Cache for 30 seconds
  });
}

export function useCluster(clusterId: number) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.detail(clusterId),
    queryFn: () => api.getCluster(clusterId),
    enabled: !!clusterId,
  });
}

export function useCreateCluster(options?: { silent?: boolean }) {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({ data }: { data: K8sClusterCreateRequest }) => api.createCluster(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.clusters.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.clusters.batchConnectivity() });
    },
    silent: options?.silent,
  });
}

export function useUpdateCluster(options?: { silent?: boolean }) {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({ clusterId, data }: { clusterId: number; data: K8sClusterUpdateRequest }) =>
      api.updateCluster(clusterId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.clusters.all });
    },
    silent: options?.silent,
  });
}

export function useDeleteCluster() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: (clusterId: number) => api.deleteCluster(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.k8s.clusters.all });
      notify.success('Cluster deleted successfully', undefined, { category: 'cluster' });
    },
  });
}

export function useTestClusterConnection() {
  return useAppMutation({
    mutationFn: (clusterId: number) => api.testClusterConnection(clusterId),
    onSuccess: (data) => {
      if (data.success) {
        notify.success('Connection successful', `Kubernetes version: ${data.version || 'Unknown'}`, { category: 'cluster' });
      } else {
        notify.error('Connection test failed', data.message, { category: 'cluster' });
      }
    },
  });
}

// Namespaces
export function useClusterNamespaces(clusterId: number, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.namespaces(clusterId),
    queryFn: () => api.getClusterNamespaces(clusterId),
    enabled: options?.enabled !== false && !!clusterId,
    staleTime: QUERY_STALE_TIME.DEFAULT, // Cache for 30 seconds
  });
}

// Resources
export function useClusterResources(
  clusterId: number,
  resourceType: string,
  params?: { namespace?: string; label_selector?: string },
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.resources(clusterId, resourceType, params),
    queryFn: () => api.getClusterResources(clusterId, resourceType, params),
    enabled: options?.enabled !== false && !!clusterId && !!resourceType,
    refetchInterval: options?.pollingEnabled ? POLL_INTERVALS.MEDIUM : false,
    placeholderData: (previousData) => previousData,
  });
}

// Per-cluster resource summary for the sidebar badges — count + unhealthy
// per kind, scoped to the currently-selected namespace (undefined/'all' =>
// cluster-wide). Polls every 30s while the tab is visible.
export function useClusterResourceSummary(
  clusterId: number,
  namespace: string | undefined,
  options?: { enabled?: boolean }
) {
  const isVisible = useDocumentVisibility();
  return useQuery({
    queryKey: ['k8s', 'clusters', clusterId, 'resource-summary', namespace ?? 'all'],
    queryFn: () => api.getClusterResourceSummary(clusterId, namespace),
    enabled: options?.enabled !== false && !!clusterId,
    // Backend caches for 60s; match that so we don't re-request until needed.
    staleTime: 30_000,
    refetchInterval: isVisible ? 30_000 : false,
    placeholderData: (previousData) => previousData,
  });
}
