import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { notify } from '@/lib/notify';
import { queryKeys } from '@/lib/queryKeys';
import type { ParseApiErrorContext } from '@/lib/error-handler';
import { useAppMutation } from '@/hooks/lib/useAppMutation';
import type { HugePagesDeployRequest } from '@/types';

// ========================================================================
// Resource Management (Phase 5)
// ========================================================================

export function useCreateK8sResource(errorContext?: ParseApiErrorContext) {
  const queryClient = useQueryClient();

  return useAppMutation({
    errorContext,
    mutationFn: ({
      clusterId,
      resourceType,
      resourceYaml,
      namespace,
      dryRun = false,
    }: {
      clusterId: number;
      resourceType: string;
      resourceYaml: string;
      namespace?: string;
      dryRun?: boolean;
    }) =>
      api.createK8sResource(clusterId, resourceType, {
        resource_yaml: resourceYaml,
        namespace,
        dry_run: dryRun,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.k8s.clusters.allResources(variables.clusterId),
      });
      if (!variables.dryRun) {
        notify.success('Resource created successfully', undefined, { category: 'cluster' });
      }
    },
  });
}

export function useUpdateK8sResource(errorContext?: ParseApiErrorContext) {
  const queryClient = useQueryClient();

  return useAppMutation({
    errorContext,
    mutationFn: ({
      clusterId,
      resourceType,
      resourceName,
      resourceYaml,
      namespace,
      dryRun = false,
    }: {
      clusterId: number;
      resourceType: string;
      resourceName: string;
      resourceYaml: string;
      namespace?: string;
      dryRun?: boolean;
    }) =>
      api.updateK8sResource(clusterId, resourceType, resourceName, {
        resource_yaml: resourceYaml,
        namespace,
        dry_run: dryRun,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.k8s.clusters.allResources(variables.clusterId),
      });
      if (!variables.dryRun) {
        notify.success('Resource updated successfully', undefined, { category: 'cluster' });
      }
    },
  });
}

export function useDeleteK8sResource(errorContext?: ParseApiErrorContext) {
  const queryClient = useQueryClient();

  return useAppMutation({
    errorContext,
    mutationFn: ({
      clusterId,
      resourceType,
      resourceName,
      namespace,
      dryRun = false,
    }: {
      clusterId: number;
      resourceType: string;
      resourceName: string;
      namespace?: string;
      dryRun?: boolean;
    }) =>
      api.deleteK8sResource(clusterId, resourceType, resourceName, {
        namespace,
        dry_run: dryRun,
      }),
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.k8s.clusters.allResources(variables.clusterId),
      });
      const message = data.message || 'Resource deleted successfully';
      notify.success(message, undefined, { category: 'cluster' });
    },
  });
}

export function useScaleDeployment() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({
      clusterId,
      deploymentName,
      namespace,
      replicas,
    }: {
      clusterId: number;
      deploymentName: string;
      namespace: string;
      replicas: number;
    }) =>
      api.scaleDeployment(clusterId, deploymentName, {
        replicas,
        namespace,
      }),
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.k8s.clusters.allResources(variables.clusterId),
      });
      const message = data.message || `Deployment scaled to ${data.replicas} replicas`;
      notify.success(message, undefined, { category: 'cluster' });
    },
  });
}

// ========================================================================
// Cluster Scanner
// ========================================================================

export function useClusterScan() {
  const queryClient = useQueryClient();

  // Accepts either a bare cluster ID (normal scan, backend cache allowed)
  // or { clusterId, force: true } (user-initiated rescan via the Rescan
  // button — bypasses the backend's scan cache for a fresh run).
  return useAppMutation({
    mutationFn: (input: number | { clusterId: number; force?: boolean }) => {
      if (typeof input === 'number') {
        return api.scanCluster(input);
      }
      return api.scanCluster(input.clusterId, input.force);
    },
    onSuccess: (data, input) => {
      const clusterId = typeof input === 'number' ? input : input.clusterId;
      // Cache the scan result so ClusterScanResults can display it
      queryClient.setQueryData(queryKeys.k8s.clusters.scan(clusterId), data);
      notify.success('Cluster scan complete', undefined, { category: 'cluster' });
    },
  });
}

export function useClusterScanResult(clusterId: number | null) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.scan(clusterId!),
    queryFn: () => api.scanCluster(clusterId!),
    enabled: false, // Only populated by the mutation above; never auto-fetches
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });
}

// ========================================================================
// Adaptive Module Selection
// ========================================================================

// ========================================================================
// Recommendation Actions
// ========================================================================

export function useDeployHugePages() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({
      clusterId,
      payload,
    }: {
      clusterId: number;
      payload: HugePagesDeployRequest;
    }) => api.deployHugePages(clusterId, payload),
    onSuccess: (data, { clusterId }) => {
      notify.success(data.message, undefined, { category: 'cluster' });
      // Drop cached scan so the UI re-fetches and the HugePages recommendation disappears once the Job lands.
      queryClient.removeQueries({ queryKey: queryKeys.k8s.clusters.scan(clusterId) });
    },
  });
}

// ========================================================================
// Node Readiness Probe (issue #387 part A — detection only)
// ========================================================================

// ========================================================================
// Proxy Translation (D-021 P2)
// ========================================================================

/**
 * Mutation hook to request a BNK migration preview for a detected proxy.
 *
 * Read-only — the endpoint performs LIST/GET only on the cluster. The
 * returned YAML is for user inspection/copy; no cluster apply occurs.
 */
/**
 * Preview BNK Gateway API equivalent of CIS VirtualServer/TransportServer CRs.
 *
 * Read-only — re-fetches full CIS CR specs from the cluster, calls the pure
 * CIS translator.  Policy refs route to unmapped[] (escalation: BNK security
 * CRD kind unverified).  No cluster mutations.
 */
