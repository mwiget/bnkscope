import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POLL_INTERVALS } from '@/lib/constants';
import { queryKeys } from '@/lib/queryKeys';

// ========================================================================
// NICo Unified Data Hook
//
// One fetch for the whole NICo picture — deployment, endpoint and Forge
// inventory. All NICo sub-views share this cache key, so switching between
// them is instant (no re-fetch).
// ========================================================================

export function useNicoData(
  clusterId: number,
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.nicoData(clusterId),
    queryFn: () => api.getNicoData(clusterId),
    enabled: options?.enabled !== false && !!clusterId,
    refetchInterval: options?.pollingEnabled !== false ? POLL_INTERVALS.SLOW : false,
    placeholderData: (previousData) => previousData,
  });
}
