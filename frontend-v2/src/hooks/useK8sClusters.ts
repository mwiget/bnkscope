/**
 * K8s cluster CRUD hooks (IMP-011: split from useK8s.ts).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  K8sClusterCreateRequest,
  K8sClusterUpdateRequest,
} from '@/types';
import { QUERY_STALE_TIME } from '@/lib/constants';
import { notify } from '@/lib/notify';
import { queryKeys } from '@/lib/queryKeys';
import { useAppMutation } from '@/hooks/lib/useAppMutation';

// Resource Types
export function useK8sResourceTypes() {
  return useQuery({
    queryKey: queryKeys.k8s.resourceTypes(),
    queryFn: api.getK8sResourceTypes,
    staleTime: QUERY_STALE_TIME.VERY_LONG, // Cache for 5 minutes (resource types don't change often)
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

