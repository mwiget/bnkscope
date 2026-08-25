/**
 * Kubernetes & F5 BNK API methods
 */
import { apiClient } from './client';
import type {
  DiscoveryResponse,
  K8sCluster,
  K8sClusterCreateRequest,
  K8sClusterUpdateRequest,
  K8sResourceListResponse,
  K8sNamespaceListResponse,
  K8sResourceTypesResponse,
  K8sClusterTestResult,
  K8sResource,
  K8sResourceStatus,
  K8sEvent,
  K8sPodContainer,
  K8sPodMetric,
  K8sNodeMetric,
  K8sRolloutHistoryEntry,
  K8sRolloutStatus,
  K8sCondition,
  ClusterScanResponse,
  BnkDataResponse,
  DpfDataResponse,
  NicoDataResponse,
  NicoDeploymentResponse,
  NicoInventoryResponse,
  A2AAgentsResponse,
  HugePagesDeployRequest,
  HugePagesDeployResponse,
} from '@/types';
import type {
  ApiClusterCreateRequest,
  ApiClusterUpdateRequest,
  AssertKeysMatch,
} from '@/types/api-schemas';
import type { components } from '@/types/api-generated';

type CrdListEnvelope = components['schemas']['CrdListEnvelope'];
type TopologyGraphResponse = components['schemas']['TopologyGraphResponse'];

// ── Compile-time contract checks ────────────────────────────────────────────
const _checkClusterCreate: AssertKeysMatch<K8sClusterCreateRequest, ApiClusterCreateRequest> = true;
const _checkClusterUpdate: AssertKeysMatch<K8sClusterUpdateRequest, ApiClusterUpdateRequest> = true;
// eslint-disable-next-line @typescript-eslint/no-unused-expressions
void _checkClusterCreate, _checkClusterUpdate;

export const kubernetesApi = {
  // Local kubeconfig discovery
  getDiscovery: () =>
    apiClient.get<DiscoveryResponse>('/api/k8s/discovery').then((res) => res.data),

  // Only the context NAME travels — the kubeconfig is re-read from the host,
  // so this endpoint cannot be used to inject credentials.
  adoptContext: (context: string) =>
    apiClient.post<DiscoveryResponse>('/api/k8s/discovery/adopt', { context }).then((res) => res.data),

  // Kubernetes Monitoring
  getAllClusters: () =>
    apiClient.get<{ clusters: K8sCluster[]; count: number }>('/api/k8s/clusters').then((res) => res.data),

  getCluster: (clusterId: number) =>
    apiClient.get<K8sCluster>(`/api/k8s/clusters/${clusterId}`).then((res) => res.data),

  createCluster: (data: K8sClusterCreateRequest) =>
    apiClient.post<K8sCluster>('/api/k8s/clusters', data).then((res) => res.data),

  updateCluster: (clusterId: number, data: K8sClusterUpdateRequest) =>
    apiClient.put<K8sCluster>(`/api/k8s/clusters/${clusterId}`, data).then((res) => res.data),

  deleteCluster: (clusterId: number) =>
    apiClient.delete<{ message: string }>(`/api/k8s/clusters/${clusterId}`).then((res) => res.data),

  testClusterConnection: (clusterId: number) =>
    apiClient.post<K8sClusterTestResult>(`/api/k8s/clusters/${clusterId}/test`).then((res) => res.data),

  getClusterResources: (clusterId: number, resourceType: string, params?: { namespace?: string; label_selector?: string }) =>
    apiClient.get<K8sResourceListResponse>(`/api/k8s/clusters/${clusterId}/resources/${resourceType}`, { params }).then((res) => res.data),

  getClusterResourceSummary: (clusterId: number, namespace?: string) =>
    apiClient
      .get<{
        cluster_id: number;
        namespace: string | null;
        summary: Record<string, { count: number; unhealthy: number | null; available: boolean }>;
      }>(`/api/k8s/clusters/${clusterId}/resource-summary`, {
        params: namespace && namespace !== 'all' ? { namespace } : {},
      })
      .then((res) => res.data),

  getClusterNamespaces: (clusterId: number) =>
    apiClient.get<K8sNamespaceListResponse>(`/api/k8s/clusters/${clusterId}/namespaces`).then((res) => res.data),

  // CNF: CRD discovery (D-018 P1)
  // FastAPI's `group: list[str] = Query(...)` needs repeated `?group=a&group=b`, not
  // axios's default array serialization (`group[]=a&group[]=b`), so build the query
  // string manually — same pattern as api.getFleetMembers.
  getCrds: (clusterId: number, params?: { group?: string[] }) => {
    const searchParams = new URLSearchParams();
    if (params?.group) {
      params.group.forEach((g) => searchParams.append('group', g));
    }
    const qs = searchParams.toString();
    return apiClient
      .get<CrdListEnvelope>(`/api/k8s/clusters/${clusterId}/crds${qs ? `?${qs}` : ''}`)
      .then((res) => res.data);
  },

  // CNF: Namespace topology graph (D-018 P4)
  getTopology: (clusterId: number, namespace: string) =>
    apiClient
      .get<TopologyGraphResponse>(`/api/k8s/clusters/${clusterId}/topology`, { params: { namespace } })
      .then((res) => res.data),

  getClusterNodeCount: (clusterId: number) =>
    apiClient.get<{ cluster_id: number; node_count: number }>(`/api/k8s/clusters/${clusterId}/nodes/count`).then((res) => res.data.node_count),

  getK8sResourceTypes: () =>
    apiClient.get<K8sResourceTypesResponse>('/api/k8s/resource-types').then((res) => res.data.resource_types),

  // F5 BNK Monitoring — unified data endpoint (single fetch for all insight views)
   
  getBnkData: (clusterId: number, params?: { namespace?: string }) =>
    apiClient.get<BnkDataResponse>(`/api/k8s/clusters/${clusterId}/f5bnk/data`, { params }).then((res) => res.data),

  getA2AAgents: (clusterId: number, params?: { namespace?: string; probe?: boolean }) =>
    apiClient.get<A2AAgentsResponse>(`/api/k8s/clusters/${clusterId}/f5bnk/a2a/agents`, { params }).then((res) => res.data),

  // Cluster Scanner
  scanCluster: (clusterId: number, force = false) =>
    apiClient
      .post<ClusterScanResponse>(
        `/api/k8s/clusters/${clusterId}/scan${force ? '?force=true' : ''}`
      )
      .then((res) => res.data),

  deployHugePages: (clusterId: number, payload: HugePagesDeployRequest) =>
    apiClient
      .post<HugePagesDeployResponse>(
        `/api/k8s/clusters/${clusterId}/recommendations/hugepages/deploy`,
        payload,
      )
      .then((res) => res.data),

  createK8sResource: (clusterId: number, resourceType: string, data: { resource_yaml: string; namespace?: string; dry_run?: boolean }) =>
    apiClient.post<{ success: boolean; message: string; resource: K8sResource }>(`/api/k8s/clusters/${clusterId}/resources/${resourceType}`, data).then((res) => res.data),

  updateK8sResource: (clusterId: number, resourceType: string, resourceName: string, data: { resource_yaml: string; namespace?: string; dry_run?: boolean }) =>
    apiClient.put<{ success: boolean; message: string; resource: K8sResource }>(`/api/k8s/clusters/${clusterId}/resources/${resourceType}/${resourceName}`, data).then((res) => res.data),

  deleteK8sResource: (clusterId: number, resourceType: string, resourceName: string, params?: { namespace?: string; dry_run?: boolean }) =>
    apiClient.delete<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/resources/${resourceType}/${resourceName}`, { params }).then((res) => res.data),

  scaleDeployment: (clusterId: number, deploymentName: string, data: { replicas: number; namespace: string }) =>
    apiClient.post<{ success: boolean; message: string; replicas: number }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/scale`, data).then((res) => res.data),

  getPodLogs: (clusterId: number, podName: string, params: { namespace: string; container?: string; tail_lines?: number }) =>
    apiClient.get<{ logs: string; pod_name: string; namespace: string }>(`/api/k8s/clusters/${clusterId}/pods/${podName}/logs`, { params }).then((res) => res.data),

  restartPod: (clusterId: number, podName: string, params: { namespace: string }) =>
    apiClient.post<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/pods/${podName}/restart`, null, { params }).then((res) => res.data),

  // Kubernetes Advanced Operations
  describeResource: (clusterId: number, resourceType: string, resourceName: string, namespace?: string) =>
    apiClient.get<{ 
      metadata: K8sResource['metadata']; 
      conditions?: K8sCondition[]; 
      events?: K8sEvent[]; 
      status?: K8sResourceStatus;
      relationships?: { owned?: Array<{ kind: string; name: string }>; related?: Array<{ kind: string; name: string }> } 
    }>(`/api/k8s/clusters/${clusterId}/resources/${resourceType}/${resourceName}/describe`, { params: { namespace } }).then((res) => res.data),

  getClusterEvents: (clusterId: number, params?: { namespace?: string; resource_type?: string; resource_name?: string; event_type?: string }) =>
    apiClient.get<{ events: K8sEvent[]; count: number }>(`/api/k8s/clusters/${clusterId}/events`, { params }).then((res) => res.data),

  getPodContainers: (clusterId: number, podName: string, namespace: string) =>
    apiClient.get<{ pod_name: string; namespace: string; containers: K8sPodContainer[]; init_containers: K8sPodContainer[] }>(`/api/k8s/clusters/${clusterId}/pods/${podName}/containers`, { params: { namespace } }).then((res) => res.data),

  getPodMetrics: (clusterId: number, params?: { namespace?: string; sort_by?: string }) =>
    apiClient.get<{ available: boolean; metrics?: K8sPodMetric[]; error?: string }>(`/api/k8s/clusters/${clusterId}/top/pods`, { params }).then((res) => res.data),

  getNodeMetrics: (clusterId: number, params?: { sort_by?: string }) =>
    apiClient.get<{ available: boolean; metrics?: K8sNodeMetric[]; error?: string }>(`/api/k8s/clusters/${clusterId}/top/nodes`, { params }).then((res) => res.data),

  // Kubernetes Rollout Management (Phase 3)
  getRolloutHistory: (clusterId: number, deploymentName: string, namespace: string) =>
    apiClient.get<{ history: K8sRolloutHistoryEntry[]; deployment_name: string; namespace: string }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/history`, { params: { namespace } }).then((res) => res.data),

  getRolloutStatus: (clusterId: number, deploymentName: string, namespace: string) =>
    apiClient.get<K8sRolloutStatus>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/status`, { params: { namespace } }).then((res) => res.data),

  rolloutUndo: (clusterId: number, deploymentName: string, namespace: string, revision?: number) =>
    apiClient.post<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/undo`, null, { params: { namespace, revision } }).then((res) => res.data),

  rolloutRestart: (clusterId: number, deploymentName: string, namespace: string) =>
    apiClient.post<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/restart`, null, { params: { namespace } }).then((res) => res.data),

  rolloutPause: (clusterId: number, deploymentName: string, namespace: string) =>
    apiClient.post<{ success: boolean; message: string; paused: boolean }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/pause`, null, { params: { namespace } }).then((res) => res.data),

  rolloutResume: (clusterId: number, deploymentName: string, namespace: string) =>
    apiClient.post<{ success: boolean; message: string; paused: boolean }>(`/api/k8s/clusters/${clusterId}/deployments/${deploymentName}/rollout/resume`, null, { params: { namespace } }).then((res) => res.data),

  // Kubernetes Node Operations (Phase 3)
  cordonNode: (clusterId: number, nodeName: string) =>
    apiClient.post<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/nodes/${nodeName}/cordon`).then((res) => res.data),

  uncordonNode: (clusterId: number, nodeName: string) =>
    apiClient.post<{ success: boolean; message: string }>(`/api/k8s/clusters/${clusterId}/nodes/${nodeName}/uncordon`).then((res) => res.data),

  drainNode: (clusterId: number, nodeName: string, options?: { ignore_daemonsets?: boolean; delete_emptydir_data?: boolean; force?: boolean; grace_period?: number }) =>
    apiClient.post<{ success: boolean; message: string; evicted_pods: Array<{ name: string; namespace: string }>; failed_pods: Array<{ name: string; namespace: string; error: string }> }>(`/api/k8s/clusters/${clusterId}/nodes/${nodeName}/drain`, null, { params: options }).then((res) => res.data),

  getDpfData: (clusterId: number) =>
    apiClient.get<DpfDataResponse>(`/api/k8s/clusters/${clusterId}/dpf/data`).then((res) => res.data),

  getNicoData: (clusterId: number) =>
    apiClient.get<NicoDataResponse>(`/api/k8s/clusters/${clusterId}/nico/data`).then((res) => res.data),

  getNicoDeployment: (clusterId: number) =>
    apiClient.get<NicoDeploymentResponse>(`/api/k8s/clusters/${clusterId}/nico/deployment`).then((res) => res.data),

  getNicoInventory: (clusterId: number) =>
    apiClient.get<NicoInventoryResponse>(`/api/k8s/clusters/${clusterId}/nico/inventory`).then((res) => res.data),
};
