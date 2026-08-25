/**
 * Centralized Query Key Factory
 *
 * This file provides a type-safe, hierarchical structure for React Query keys.
 * Using this pattern enables:
 * - Easy invalidation of related queries
 * - Type safety for query keys
 * - Clear organization of data fetching
 * - Prevents typos and inconsistencies
 *
 * Example usage:
 * - Invalidate all projects: queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
 * - Invalidate specific project: queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(6) })
 * - Invalidate all modules for a project: queryClient.invalidateQueries({ queryKey: queryKeys.modules.byProject(6) })
 *
 * @see https://tkdodo.eu/blog/effective-react-query-keys
 */

export const queryKeys = {

  // Kubernetes hierarchy
  k8s: {
    all: ['k8s'] as const,
    resourceTypes: () => ['k8s', 'resource-types'] as const,
    discovery: ['k8s', 'discovery'] as const,
    clusters: {
      all: ['k8s', 'clusters'] as const,
      detail: (clusterId: number) => ['k8s', 'clusters', clusterId] as const,
      namespaces: (clusterId: number) => ['k8s', 'clusters', clusterId, 'namespaces'] as const,
      // Resources — use partial key for broad invalidation
      allResources: (clusterId: number) => ['k8s', 'clusters', clusterId, 'resources'] as const,
      resources: (clusterId: number, resourceType: string, params?: Record<string, string | undefined>) =>
        ['k8s', 'clusters', clusterId, 'resources', resourceType, params] as const,
      // BNK data
      bnkData: (clusterId: number, params?: Record<string, string | undefined>) =>
        ['k8s', 'clusters', clusterId, 'f5bnk', 'data', params] as const,
      // A2A agent discovery
      a2aAgents: (clusterId: number, params?: Record<string, string | boolean | undefined>) =>
        ['k8s', 'clusters', clusterId, 'f5bnk', 'a2a', 'agents', params] as const,
      // BNK upgrade (prefix key invalidates all sub-keys: versions, current, history, detail)
      bnkUpgrade: (clusterId: number) => ['k8s', 'clusters', clusterId, 'bnk', 'upgrade'] as const,
      bnkUpgradeVersions: (clusterId: number) => ['k8s', 'clusters', clusterId, 'bnk', 'upgrade', 'versions'] as const,
      bnkCurrentVersion: (clusterId: number) => ['k8s', 'clusters', clusterId, 'bnk', 'upgrade', 'current'] as const,
      bnkUpgradeHistory: (clusterId: number) => ['k8s', 'clusters', clusterId, 'bnk', 'upgrade', 'history'] as const,
      bnkUpgradeDetail: (clusterId: number, upgradeId: number) => ['k8s', 'clusters', clusterId, 'bnk', 'upgrade', upgradeId] as const,
      // Connectivity probes
      connectivity: (clusterId: number) => ['k8s', 'clusters', clusterId, 'connectivity'] as const,
      batchConnectivity: () => ['k8s', 'clusters', 'connectivity'] as const,
      // Scan
      scan: (clusterId: number) => ['k8s', 'clusters', clusterId, 'scan'] as const,
      // Tunnel
      tunnel: (clusterId: number) => ['k8s', 'clusters', clusterId, 'tunnel'] as const,
      // Pod operations
      podLogs: (clusterId: number, podName: string, namespace?: string) =>
        ['k8s', 'clusters', clusterId, 'pods', podName, 'logs', namespace] as const,
      podContainers: (clusterId: number, podName: string, namespace?: string) =>
        ['k8s', 'clusters', clusterId, 'pods', podName, 'containers', namespace] as const,
      // Resource describe
      describeResource: (clusterId: number, resourceType: string, resourceName: string, namespace?: string) =>
        ['k8s', 'clusters', clusterId, 'resources', resourceType, resourceName, 'describe', namespace] as const,
      // Deployment rollout
      rolloutHistory: (clusterId: number, deploymentName: string, namespace?: string) =>
        ['k8s', 'clusters', clusterId, 'deployments', deploymentName, 'rollout', 'history', namespace] as const,
      rolloutStatus: (clusterId: number, deploymentName: string, namespace?: string) =>
        ['k8s', 'clusters', clusterId, 'deployments', deploymentName, 'rollout', 'status', namespace] as const,
      // Node count (inline query in KubernetesV2.tsx)
      nodeCount: (clusterId: number) => ['k8s', 'clusters', clusterId, 'node-count'] as const,
      // Events
      events: (clusterId: number, params?: Record<string, string | undefined>) =>
        ['k8s', 'clusters', clusterId, 'events', params] as const,
      // Metrics
      podMetrics: (clusterId: number, params?: Record<string, string | undefined>) =>
        ['k8s', 'clusters', clusterId, 'metrics', 'pods', params] as const,
      nodeMetrics: (clusterId: number, params?: Record<string, string | undefined>) =>
        ['k8s', 'clusters', clusterId, 'metrics', 'nodes', params] as const,
      // Adaptive module plan
      adaptiveModules: (clusterId: number, templateSlug?: string) =>
        ['k8s', 'clusters', clusterId, 'adaptive-modules', templateSlug || 'default'] as const,
      // CNF: CRD discovery (D-018 P1)
      crds: (clusterId: number, params?: { group?: string[] }) =>
        ['k8s', 'clusters', clusterId, 'crds', params] as const,
      // CNF: Namespace topology graph (D-018 P4)
      topology: (clusterId: number, namespace: string) =>
        ['k8s', 'clusters', clusterId, 'topology', namespace] as const,
      // DPF (NVIDIA DPU infrastructure)
      dpf: (clusterId: number) => ['k8s', 'clusters', clusterId, 'dpf'] as const,
      dpfDetect: (clusterId: number) => ['k8s', 'clusters', clusterId, 'dpf', 'detect'] as const,
      dpfData: (clusterId: number) => ['k8s', 'clusters', clusterId, 'dpf', 'data'] as const,
      dpfHealth: (clusterId: number) => ['k8s', 'clusters', clusterId, 'dpf', 'health'] as const,
      nicoData: (clusterId: number) => ['k8s', 'clusters', clusterId, 'nico', 'data'] as const,
    },
    tunnels: () => ['k8s', 'tunnels'] as const,
  },

  // System / Settings hierarchy
  logs: {
    all: ['logs'] as const,
    filters: () => ['logs', 'filters'] as const,
    search: (params: Record<string, unknown>) => ['logs', 'search', params] as const,
  },
  tmmscope: {
    all: ['tmmscope'] as const,
    status: () => ['tmmscope', 'status'] as const,
    injection: (clusterId: number) => ['tmmscope', 'injection', clusterId] as const,
    cluster: (clusterId: number, theme: string) =>
      ['tmmscope', 'cluster', clusterId, theme] as const,
  },

  system: {
    all: ['system'] as const,
    health: () => ['system', 'health'] as const,
    processMetrics: () => ['system', 'process-metrics'] as const,
    performance: () => ['system', 'performance'] as const,
    errors: (limit?: number) => ['system', 'errors', limit] as const,
    databaseStats: () => ['system', 'database', 'stats'] as const,
    containerStatus: () => ['system', 'containers', 'status'] as const,
    version: () => ['system-version'] as const,
    upgradeStatus: () => ['system', 'upgrade', 'status'] as const,
    settings: () => ['settings'] as const,
    systemDefaults: () => ['system-defaults'] as const,
    defaultsStatus: () => ['defaults-status'] as const,
    backupStatus: () => [...queryKeys.system.all, 'backup', 'status'] as const,
    maintenanceStatus: () => [...queryKeys.system.all, 'maintenance'] as const,
  },

  // Notifications hierarchy
  notifications: {
    all: ['notifications'] as const,
    list: (unreadOnly?: boolean) => ['notifications', unreadOnly] as const,
    infinite: (filters: { unreadOnly?: boolean; category?: string; severity?: string }) =>
      ['notifications', 'infinite', filters] as const,
    unreadCount: () => ['notifications', 'unread-count'] as const,
  },

  // MCP server
  mcp: {
    status: () => ['mcp', 'status'] as const,
  },

  // AI Gateway Observability (Tier 1: request analytics — Loki-backed)
  llmObservability: {
    all: ['llm-observability'] as const,
    stats: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'stats', params] as const,
    histogram: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'histogram', params] as const,
    rankings: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'rankings', params] as const,
    providerUsage: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'provider-usage', params] as const,
    logs: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'logs', params] as const,
    filterData: (clusterId: number, params?: Record<string, string | undefined>) =>
      ['llm-observability', clusterId, 'filterdata', params] as const,
  },

} as const;

/**
 * Helper type to extract query key type from the factory
 * Usage: type ProjectsKey = QueryKey<typeof queryKeys.projects.all>
 */
export type QueryKey<T extends readonly unknown[]> = T;
