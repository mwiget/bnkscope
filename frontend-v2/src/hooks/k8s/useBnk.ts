import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  BnkHealthResponse,
  GatewayTopologyResponse,
  F5PolicyGatewayAssociationsResponse,
} from '@/types';
import { POLL_INTERVALS } from '@/lib/constants';
import { queryKeys } from '@/lib/queryKeys';

// ========================================================================
// F5 BNK Unified Data Hook
//
// Single fetch for all BNK insight views. Returns health, topology,
// and policy data in one response. All BNK insight tabs share this
// cache key, so switching tabs is instant (no re-fetch).
// ========================================================================

export function useBnkData(
  clusterId: number,
  params?: { namespace?: string },
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.k8s.clusters.bnkData(clusterId, params),
    queryFn: () => api.getBnkData(clusterId, params),
    enabled: options?.enabled !== false && !!clusterId,
    refetchInterval: options?.pollingEnabled !== false ? POLL_INTERVALS.SLOW : false,
    placeholderData: (previousData) => previousData,
  });
}

// Convenience selectors — each returns a slice of the unified data
export function useF5BNKHealth(
  clusterId: number,
  params?: { namespace?: string },
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  const query = useBnkData(clusterId, params, options);
  return {
    ...query,
    data: query.data?.health as BnkHealthResponse | undefined,
  };
}

export function useF5GatewayTopology(
  clusterId: number,
  params?: { namespace?: string },
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  const query = useBnkData(clusterId, params, options);
  return {
    ...query,
    data: query.data ? {
      topology: query.data.topology,
      dataPlane: query.data.dataPlane,
      referenceGrants: query.data.referenceGrants ?? [],
      counts: query.data.topologyCounts,
      cluster_id: clusterId,
      namespace: params?.namespace ?? null,
    } satisfies GatewayTopologyResponse : undefined,
  };
}

export function useF5PolicyGatewayAssociations(
  clusterId: number,
  params?: { namespace?: string },
  options?: { pollingEnabled?: boolean; enabled?: boolean }
) {
  const query = useBnkData(clusterId, params, options);
  return {
    ...query,
    data: query.data ? {
      associations: query.data.policyAssociations,
      count: query.data.policyCount,
      cluster_id: clusterId,
      namespace: params?.namespace,
    } as F5PolicyGatewayAssociationsResponse : undefined,
  };
}

// ========================================================================
// BNK Upgrade Workflow
// ========================================================================

