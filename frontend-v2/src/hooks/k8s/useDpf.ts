import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POLL_INTERVALS } from '@/lib/constants';
import { queryKeys } from '@/lib/queryKeys';

// ========================================================================
// DPF Detection (lightweight)
//
// Checks if DPF is installed by fetching only 3 CRD types.
// Use this to conditionally show/hide the DPF panel in the sidebar.
// ========================================================================

// ========================================================================
// DPF Unified Data Hook
//
// Single fetch for all DPF resource types. Returns health analysis and
// full resource inventory. All DPF views share this cache key, so
// switching between DPF tabs is instant (no re-fetch).
// ========================================================================

export function useDpfData(
  clusterId: number,
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.dpfData(clusterId),
    queryFn: () => api.getDpfData(clusterId),
    enabled: options?.enabled !== false && !!clusterId,
    refetchInterval: options?.pollingEnabled !== false ? POLL_INTERVALS.SLOW : false,
    placeholderData: (previousData) => previousData,
  });
}

// ========================================================================
// Typed resource selectors — extract raw K8s objects from unified data
// ========================================================================

/** Extract DPUDevice resources from the unified data response. */

/** Extract DPUCluster resources from the unified data response. */

/** Extract DPU lifecycle objects from the unified data response. */

/** Extract DPUSet resources from the unified data response. */

/** Extract BFB resources from the unified data response. */

/** Extract DPUFlavor resources from the unified data response. */

// =============================================================================
// Service resource selectors (svc.dpu.nvidia.com)
// =============================================================================

/** Extract DPUService resources from the unified data response. */

/** Extract DPUDeployment resources from the unified data response. */

/** Extract DPUServiceChain resources from the unified data response. */

/** Extract DPUServiceInterface resources from the unified data response. */

/** Extract per-DPU ServiceChain resources from the unified data response. */

/** Extract per-DPU ServiceInterface resources from the unified data response. */
