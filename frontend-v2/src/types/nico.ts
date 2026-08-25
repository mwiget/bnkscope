/**
 * NICo (NVIDIA Infra Controller) types
 *
 * Derived from the actual backend return shapes in:
 * - routes/k8s/nico.py (3 GET endpoints)
 * - services/nico/health.py (analyze_nico_health)
 * - services/nico/fetch.py (detect_nico, fetch_all_nico_data)
 *
 * Two halves, as the backend has: the *deployment* (Kubernetes objects — pods,
 * Service, Secret) and the *inventory* (tenants, VPCs, load balancers), which
 * exists only behind NICo's Forge gRPC API.
 */

// ── Deployment ────────────────────────────────────────────────────────────

export interface NicoPod {
  name: string;
  namespace: string;
  phase: string | null;
  ready: number;
  containers: number;
  restarts: number;
  node: string | null;
  image: string | null;
  createdAt: string | null;
}

export interface NicoCertInfo {
  secret: string;
  present: boolean;
  subject?: string;
  issuer?: string;
  notAfter?: string;
  daysLeft?: number;
  detail?: string;
}

export interface NicoControlPlane {
  namespace: string;
  pods: NicoPod[];
  /** Admin web UI auth mode. "none" is carbide's default — and the lab's. */
  webAuth: string;
  mtls: NicoCertInfo;
  /** Forge's own version banner, e.g. "Forge v2.0.0-pr-428-g7a8cdf3ce". */
  version: string | null;
}

export interface NicoEndpointCandidate {
  host: string;
  port: number;
  via: string;
}

export interface NicoEndpoint {
  /** Which candidate won: "nodeport" | "loadbalancer", or the Service type. */
  kind: string | null;
  host: string | null;
  port: number | null;
  reachable: boolean;
  candidates: NicoEndpointCandidate[];
  grpc: string | null;
  webUi: string | null;
  detail: string | null;
}

export interface NicoProvider {
  name: string;
  pod: NicoPod;
  /** GATEWAY_CLASS / VIP_CIDR / NICO_ENDPOINT / TENANT_SECRET_* */
  config: Record<string, string>;
  recentErrors: string[];
}

export interface NicoDependency {
  name: string;
  namespace: string;
  pods: NicoPod[];
}

// ── Inventory (Forge) ─────────────────────────────────────────────────────

export interface NicoVpcPrefix {
  id: string;
  prefix: string | null;
  total: number | null;
  available: number | null;
  state: string | null;
}

export interface NicoVpc {
  id: string;
  tenant: string;
  vni: number | null;
  virtualizationType: string | null;
  state: string | null;
  created: string | null;
  updated: string | null;
  prefixes: NicoVpcPrefix[];
}

export interface NicoTenant {
  id: string;
  vpcCount: number;
  vpcIds: string[];
  vnis: number[];
  vipPrefixes: string[];
  lbCount: number;
  vips: string[];
  lbsReady: number;
}

export interface NicoSegmentPrefix {
  prefix: string | null;
  gateway: string | null;
  reserveFirst: number | null;
}

export interface NicoNetworkSegment {
  id: string;
  name: string | null;
  type: string | null;
  mtu: number | null;
  flags: string[];
  state: string | null;
  prefixes: NicoSegmentPrefix[];
}

export interface NicoPoolMember {
  address: string | null;
  port: number | null;
}

export interface NicoMonitor {
  name: string | null;
  type: string | null;
  intervalSec: number | null;
  timeoutSec: number | null;
  send: string | null;
  recv: string | null;
}

export interface NicoPool {
  name: string | null;
  lbMethod: string | null;
  minActiveMembers: number | null;
  members: NicoPoolMember[];
  monitors: NicoMonitor[];
}

export interface NicoListener {
  name: string | null;
  port: number | null;
  protocol: string | null;
  poolName: string | null;
}

export interface NicoLoadBalancer {
  id: string;
  name: string;
  description: string | null;
  labels: Record<string, string>;
  tenant: string;
  vpcId: string | null;
  vipSegmentId: string | null;
  provider: string | null;
  vip: string | null;
  /** Enum prefix stripped by the backend: READY, PENDING, FAILED, … */
  status: string | null;
  /** How many TMM pods have this VIP programmed. */
  programmedPods: number | null;
  declTmmGeneration: string | null;
  created: string | null;
  updated: string | null;
  listeners: NicoListener[];
  pools: NicoPool[];
}

export interface NicoDomain {
  id: string;
  zone: string | null;
  kind: string | null;
  serial: number | null;
}

export interface NicoDpfServiceVersion {
  service?: string;
  configHelmVersion?: string;
  configDockerImageTag?: string;
}

export interface NicoFleetCounts {
  machines: number;
  switches: number;
  racks: number;
  instances: number;
}

export interface NicoInventory {
  tenants?: NicoTenant[];
  vpcs?: NicoVpc[];
  networkSegments?: NicoNetworkSegment[];
  loadBalancers?: NicoLoadBalancer[];
  domains?: NicoDomain[];
  dpfServiceVersions?: NicoDpfServiceVersion[];
  fleet?: NicoFleetCounts;
}

// ── Health ────────────────────────────────────────────────────────────────

export type NicoStatus = 'healthy' | 'degraded' | 'unreachable' | 'not_installed';

export interface NicoHealthResponse {
  status: NicoStatus;
  version: string | null;
  namespace: string | null;
  api: { total: number; ready: number };
  providers: { total: number; ready: number; withErrors: number };
  dependencies: { total: number; ready: number };
  tenants: { total: number };
  vpcs: { total: number };
  loadBalancers: {
    total: number;
    ready: number;
    programmedPods: number;
    pools: number;
    members: number;
  };
  networkSegments: { total: number };
  certExpiring: boolean;
  dpus: { total: number; ready: number };
  errors: string[];
}

// ── Endpoints ─────────────────────────────────────────────────────────────

export interface NicoDetectResponse {
  detected: boolean;
  namespace: string | null;
  apiPods: number;
  providerPods: number;
  cluster_id: number;
}

export interface NicoDataResponse {
  detected: boolean;
  cluster_id: number;
  health: NicoHealthResponse;
  controlPlane: NicoControlPlane;
  endpoint: NicoEndpoint;
  providers: NicoProvider[];
  dependencies: NicoDependency[];
  dpf: { total: number; ready: number };
  inventory: NicoInventory;
  /** Sections that could not be read, and why. Never fatal. */
  errors: string[];
}
