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
  /** null for a "portforward" candidate — it carries a pod, not an address. */
  host: string | null;
  port: number;
  via: NicoEndpointKind;
  /** Which Service advertised this address. Absent for override/portforward. */
  service?: string;
  /** The nico-api pod the tunnel targets. Only on "portforward". */
  pod?: string;
}

/** Ranked best-first; see ENDPOINT_PREFERENCE in services/nico/constants.py. */
export type NicoEndpointKind = 'override' | 'loadbalancer' | 'nodeport' | 'portforward';

export interface NicoEndpoint {
  /** Which candidate won, or null if none did. */
  kind: NicoEndpointKind | null;
  /** null when dialling through the apiserver tunnel — it has no fixed host. */
  host: string | null;
  port: number | null;
  reachable: boolean;
  candidates: NicoEndpointCandidate[];
  grpc: string | null;
  /** The admin UI's advertised URL — NICo serves it on the gRPC listener. */
  webUi: string | null;
  /**
   * Whether `webUi` answered a TCP connect from the backend. bnkscope binds
   * loopback, so the browser is on the same host: an address that failed our
   * screen is dead for the browser too and must not be offered as a link.
   */
  webUiReachable: boolean;
  /** How to reach the admin UI by hand when no advertised address answers. */
  portForward: { command: string; webUi: string; endpoint: string } | null;
  detail: string | null;
  /** Set when the winning candidate is the apiserver tunnel. */
  tunnel: { pod: string; port: number } | null;
}

/**
 * One component of the NICo site beyond nico-api — dhcp, dns, ntp, pxe,
 * bmc-proxy, hardware-health, ssh-console, the flow orchestrator, and the
 * nico-rest stack. None of it is reachable through Forge.
 */
export interface NicoEstateComponent {
  /** From `app.kubernetes.io/component`, else `name`, else `app`. */
  name: string;
  namespace: string;
  pods: NicoPod[];
  total: number;
  ready: number;
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
  /**
   * The label selector that actually matched, or null if nothing did. Charts
   * label these differently per install, so a dependency found by its fallback
   * — or not found at all — should say so rather than look like a clean read.
   */
  selector: string | null;
  pods: (NicoPod & {
    /**
     * The few labels worth showing: Vault's `vault-sealed` / `vault-initialized`
     * / `vault-active` / `vault-version`, spilo's `spilo-role` / `cluster-name`.
     * Readiness does not cover these — a sealed Vault is Running and Ready and
     * still hands NICo nothing.
     */
    labels?: Record<string, string>;
  })[];
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
  capabilities?: NicoCapabilities;
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

/**
 * Whether an inventory section can be answered at all.
 *   absent    — this NICo build does not declare the RPCs (vanilla has no
 *               load balancer API; that family is an F5 extension)
 *   forbidden — declared, but this client certificate was refused
 *   available — we got to ask, so a zero here is a real zero
 */
export type NicoCapability = 'available' | 'absent' | 'forbidden';

export type NicoCapabilities = Partial<Record<
  'loadBalancers' | 'domains' | 'vpcs' | 'networkSegments' | 'dpfServiceVersions' | 'fleet',
  NicoCapability
>>;

export interface NicoHealthResponse {
  status: NicoStatus;
  version: string | null;
  namespace: string | null;
  api: { total: number; ready: number };
  providers: { total: number; ready: number; withErrors: number };
  dependencies: { total: number; ready: number };
  /** The site beyond nico-api: pods, ready pods, and distinct components. */
  estate: { total: number; ready: number; components: number };
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
  /** Which zeros above are measurements and which are "never asked". */
  capabilities?: NicoCapabilities;
  dpus: { total: number; ready: number };
  errors: string[];
  /**
   * True on the deployment half of the split fetch: the Forge inventory has
   * not been read yet, so the counts above are placeholders and must not be
   * rendered. A real zero and a not-yet-read are different answers.
   */
  inventoryPending?: boolean;
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
  estate: NicoEstateComponent[];
  dpf: { total: number; ready: number };
  inventory: NicoInventory;
  /** Sections that could not be read, and why. Never fatal. */
  errors: string[];
}

/**
 * GET /nico/deployment — the Kubernetes half. Everything in the unified
 * response except `inventory`, and a `health` scoped to what was read: the
 * inventory-derived counts are absent, not zero (`inventoryPending: true`).
 */
export type NicoDeploymentResponse = Omit<NicoDataResponse, 'inventory' | 'health'> & {
  health: Omit<NicoHealthResponse, NicoInventoryCountKey> & { inventoryPending: true };
};

/** The health blocks only the Forge half can fill. */
export type NicoInventoryCountKey =
  | 'tenants'
  | 'vpcs'
  | 'loadBalancers'
  | 'networkSegments';

/** GET /nico/inventory — the Forge half, with the counts to merge into health. */
export interface NicoInventoryResponse {
  cluster_id: number;
  inventory: NicoInventory;
  errors: string[];
  counts: Pick<NicoHealthResponse, NicoInventoryCountKey>;
}
