import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POLL_INTERVALS } from '@/lib/constants';
import { queryKeys } from '@/lib/queryKeys';

// ========================================================================
// NICo Data Hooks
//
// The picture comes in two halves because they cost very different amounts.
// Measured on the reference lab over a VPN:
//
//   deployment  ~6s  and stable — a bounded set of Kubernetes reads
//   inventory   ~2s warm, ~13s on a cold descriptor cache, worse on a bad
//               VPN moment — reflection plus the Forge RPCs
//
// Fetched together, every render waited on the slower one. Split, the page
// paints a true header at a predictable ~6s and the inventory fills in behind
// it. `useNicoData` remains for a caller that wants one request.
// ========================================================================

export function useNicoDeployment(
  clusterId: number,
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.nicoDeployment(clusterId),
    queryFn: () => api.getNicoDeployment(clusterId),
    enabled: options?.enabled !== false && !!clusterId,
    refetchInterval: options?.pollingEnabled !== false ? POLL_INTERVALS.SLOW : false,
    placeholderData: (previousData) => previousData,
  });
}

export function useNicoInventory(
  clusterId: number,
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.nicoInventory(clusterId),
    queryFn: () => api.getNicoInventory(clusterId),
    // Gated on the deployment half by the caller, not merely for ordering:
    // that request memoizes the endpoint resolution (~2.9s of TCP screening),
    // and firing both at once would make each pay it separately.
    enabled: options?.enabled !== false && !!clusterId,
    refetchInterval: options?.pollingEnabled !== false ? POLL_INTERVALS.SLOW : false,
    placeholderData: (previousData) => previousData,
  });
}

/**
 * Both halves in one request. Kept for callers that want the whole picture
 * without orchestrating two queries; the panel uses the split hooks above.
 */
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
