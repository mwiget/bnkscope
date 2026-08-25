/**
 * NICo Panel
 *
 * Read-only dashboard for a NVIDIA NICo (Infra Controller) deployment.
 *
 * NICo publishes no CRDs, so this is not a resource browser. The deployment —
 * nico-api, its LB provider operators, Postgres and Vault — comes from the
 * Kubernetes API; everything NICo *holds* (tenants, VPCs, VIP prefixes,
 * network segments, load balancer services) comes from its Forge gRPC API and
 * exists nowhere else.
 *
 * Backed by two fetches, because the halves cost very differently: the
 * Kubernetes deployment (GET /nico/deployment) is ~6s and stable, while the
 * Forge inventory (GET /nico/inventory) is ~2s warm and far worse on a cold
 * descriptor cache. Fetched together, every render waited on the slower one.
 *
 * The two are recombined here into the shape every sub-view already consumed,
 * so only this component knows the fetch is split. Sections the inventory
 * feeds show their own collecting state until it lands.
 *
 * Both poll every 30s.
 */

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { useNicoDeployment, useNicoInventory } from '@/hooks/k8s/useNico';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { CodeBlock } from '@/components/ui/CodeBlock';
import { ErrorState } from '@/components/ui/error-state';
import { EmptyState } from '@/components/ui/empty-state';
import { CollectingState } from '@/components/ui/collecting-state';
import type {
  NicoCapability,
  NicoDataResponse,
  NicoEstateComponent,
  NicoHealthResponse,
  NicoInventoryCountKey,
  NicoLoadBalancer,
  NicoPod,
  NicoStatus,
  NicoTenant,
} from '@/types';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Cpu,
  ExternalLink,
  Globe,
  HelpCircle,
  Layers,
  Network,
  RefreshCw,
  Route,
  Server,
  ShieldCheck,
  Users,
  XCircle,
} from 'lucide-react';

interface NICoPanelProps {
  clusterId: number;
}

// ── Status helpers ────────────────────────────────────────────────────────

type BadgeVariant = 'success' | 'warning' | 'destructive' | 'muted' | 'outline';

const STATUS_CONFIG: Record<NicoStatus, { label: string; variant: BadgeVariant; icon: typeof CheckCircle2 }> = {
  healthy:       { label: 'Healthy',       variant: 'success',     icon: CheckCircle2 },
  degraded:      { label: 'Degraded',      variant: 'warning',     icon: AlertTriangle },
  // Not "down": nico-api is running, we just cannot dial its API from here.
  // The deployment half of the page is still true.
  unreachable:   { label: 'Unreachable',   variant: 'destructive', icon: XCircle },
  not_installed: { label: 'Not Installed', variant: 'muted',       icon: HelpCircle },
};

function StatusBadge({ status }: { status: NicoStatus }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.not_installed;
  const Icon = cfg.icon;
  return (
    <Badge variant={cfg.variant} className="gap-1.5">
      <Icon className="h-3.5 w-3.5" />
      {cfg.label}
    </Badge>
  );
}

/** How each transport reads in the "reachable" row. */
const TRANSPORT: Record<string, string> = {
  override:    'yes (pinned endpoint)',
  loadbalancer:'yes (LoadBalancer)',
  nodeport:    'yes (NodePort)',
  portforward: 'yes (apiserver tunnel)',
};

function podOk(pod: NicoPod) {
  return pod.phase === 'Running' && pod.containers > 0 && pod.ready === pod.containers;
}

// ── Small building blocks ─────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Server;
  label: string;
  value: number | string;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted/50">
          <Icon className="h-5 w-5 text-foreground/80" />
        </div>
        <div>
          <p className="text-2xl font-semibold text-foreground">{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </div>
      {detail && <p className="mt-2 text-xs text-muted-foreground">{detail}</p>}
    </div>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className={cn('text-right text-foreground/80 break-all', mono && 'font-mono')}>
        {value ?? '—'}
      </span>
    </div>
  );
}

function PodRow({ pod }: { pod: NicoPod }) {
  const ok = podOk(pod);
  return (
    <div className="flex items-center justify-between rounded bg-muted/50 px-3 py-2 text-xs">
      <div className="min-w-0">
        <p className="truncate font-medium text-foreground/80">{pod.name}</p>
        <p className="truncate text-muted-foreground">
          {pod.namespace}
          {pod.node ? ` · ${pod.node}` : ''}
          {pod.image ? ` · ${pod.image}` : ''}
        </p>
      </div>
      <div className="ml-3 flex shrink-0 items-center gap-2">
        {/* Restarts are the interesting number on a lab that has been up for
            weeks — a Running pod with 35 restarts is not the same as a
            Running pod with none. */}
        {pod.restarts > 0 && (
          <Badge variant="muted" className="px-1.5 py-0 text-[10px]">
            {pod.restarts} restarts
          </Badge>
        )}
        <span className="text-muted-foreground">
          {pod.ready}/{pod.containers}
        </span>
        {ok ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-success" />
        ) : (
          <AlertTriangle className="h-3.5 w-3.5 text-warning" />
        )}
      </div>
    </div>
  );
}

/**
 * Placeholders that keep `health` type-complete while the Forge half is still
 * in flight. Never rendered — every site that would show one is gated on
 * `health.inventoryPending`, because a real zero and a not-yet-read are
 * different answers and must not look alike.
 */
const PENDING_COUNTS: Pick<NicoHealthResponse, NicoInventoryCountKey> = {
  tenants: { total: 0 },
  vpcs: { total: 0 },
  loadBalancers: { total: 0, ready: 0, programmedPods: 0, pools: 0, members: 0 },
  networkSegments: { total: 0 },
};

/** What a tab that only the Forge half can fill shows while it is in flight. */
function InventoryPending() {
  return (
    <CollectingState
      title="Reading NICo inventory"
      detail="The deployment above is already current. Tenants, VPCs, network segments and load balancers come from NICo's Forge gRPC API, which is a separate read."
      slowAfterSeconds={12}
      slowNote="Forge ships no proto, so its schema is read off the server — cached per nico-api build, so the first read after a restart or an upgrade is the slow one."
    />
  );
}

/** Why a section is blank when the blankness is not a measurement. */
const CAPABILITY_NOTE: Record<Exclude<NicoCapability, 'available'>, string> = {
  absent:
    'This NICo build does not have the API for it. The load balancer RPCs are ' +
    'an F5 extension to Forge; a vanilla install has none, so there is nothing ' +
    'to be zero.',
  forbidden:
    "Forge authorizes per method against the client certificate, and this one " +
    'was refused. The data may well exist — we were not allowed to look.',
};

function CapabilityNote({ what, state }: { what: string; state: NicoCapability }) {
  if (state === 'available') return null;
  return (
    <EmptyState
      icon={state === 'absent' ? HelpCircle : ShieldCheck}
      title={state === 'absent' ? `No ${what} API on this build` : `Not authorized for ${what}`}
      description={CAPABILITY_NOTE[state]}
      size="sm"
      illustration={false}
    />
  );
}

/** A stat whose value the Forge half has not delivered yet. */
function PendingStat({ icon: Icon, label }: { icon: typeof Server; label: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted/50">
          <Icon className="h-5 w-5 text-foreground/40" />
        </div>
        <div>
          <Skeleton className="h-7 w-10" />
          <p className="mt-1 text-xs text-muted-foreground">{label}</p>
        </div>
      </div>
    </div>
  );
}

// ── Overview ──────────────────────────────────────────────────────────────

function OverviewTab({ data }: { data: NicoDataResponse }) {
  const { health, controlPlane, endpoint, dependencies, dpf, inventory } = data;
  const cert = controlPlane.mtls;
  const fleet = inventory.fleet;
  const pending = health.inventoryPending === true;
  const lbCapAvailable = (health.capabilities?.loadBalancers ?? 'available') === 'available';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {/* The first five come from Forge; the DPU count does not, so it
            stands while the others are still loading. */}
        {pending ? (
          <>
            <PendingStat icon={Users} label="Tenants" />
            <PendingStat icon={Route} label="LB services" />
            <PendingStat icon={Boxes} label="VPCs" />
            <PendingStat icon={Network} label="Segments" />
            <PendingStat icon={Layers} label="Pool members" />
          </>
        ) : (
          <>
            <StatCard icon={Users} label="Tenants" value={health.tenants.total} />
            {/* An em dash, not 0: this build has no load balancer API, so
                there is no quantity to report. */}
            {lbCapAvailable ? (
              <>
                <StatCard
                  icon={Route}
                  label="LB services"
                  value={health.loadBalancers.total}
                  detail={
                    health.loadBalancers.total > 0
                      ? `${health.loadBalancers.ready} ready · ${health.loadBalancers.programmedPods} pods programmed`
                      : undefined
                  }
                />
                <StatCard icon={Boxes} label="VPCs" value={health.vpcs.total} />
                <StatCard icon={Network} label="Segments" value={health.networkSegments.total} />
                <StatCard
                  icon={Layers}
                  label="Pool members"
                  value={health.loadBalancers.members}
                  detail={
                    health.loadBalancers.pools > 0 ? `${health.loadBalancers.pools} pools` : undefined
                  }
                />
              </>
            ) : (
              <>
                <StatCard icon={Boxes} label="VPCs" value={health.vpcs.total} />
                <StatCard icon={Network} label="Segments" value={health.networkSegments.total} />
                <StatCard
                  icon={Route}
                  label="LB services"
                  value="—"
                  detail="no load balancer API on this build"
                />
                <StatCard
                  icon={Server}
                  label="Site components"
                  value={health.estate.components}
                  detail={`${health.estate.ready}/${health.estate.total} pods ready`}
                />
              </>
            )}
          </>
        )}
        <StatCard
          icon={Cpu}
          label="DPUs (DPF)"
          value={dpf.total}
          detail={dpf.total > 0 ? `${dpf.ready} Ready` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section title="Forge API" subtitle="The only way in — NICo publishes no CRDs.">
          <div className="space-y-0.5">
            <Field label="gRPC" value={endpoint.grpc} mono />
            <Field
              label="reachable"
              value={
                endpoint.reachable ? (
                  <span className="text-success">
                    {TRANSPORT[endpoint.kind ?? ''] ?? `yes (${endpoint.kind})`}
                  </span>
                ) : (
                  <span className="text-destructive">{endpoint.detail || 'no'}</span>
                )
              }
            />
            {/* Why we are tunnelling — otherwise a healthy tab on a
                ClusterIP-only Service looks like it should not work. */}
            {endpoint.reachable && endpoint.kind === 'portforward' && endpoint.detail && (
              <Field label="transport" value={endpoint.detail} />
            )}
            <Field
              label="web UI"
              value={
                endpoint.webUi && endpoint.webUiReachable ? (
                  <a
                    className="inline-flex items-center gap-1 text-info hover:underline"
                    href={endpoint.webUi}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {endpoint.webUi} <ExternalLink className="h-3 w-3" />
                  </a>
                ) : endpoint.webUi ? (
                  <span className="font-mono text-muted-foreground line-through">
                    {endpoint.webUi}
                  </span>
                ) : null
              }
            />
            <Field
              label="web auth"
              value={
                controlPlane.webAuth === 'none' ? (
                  <span className="text-warning">none (open on the lab network)</span>
                ) : (
                  controlPlane.webAuth
                )
              }
            />
          </div>

          {/* The advertised address is on the cluster's own subnet, which this
              host has no route to. The UI shares the gRPC listener, so the
              same forward that reaches Forge reaches the UI. */}
          {!endpoint.webUiReachable && endpoint.portForward && (
            <div className="mt-3 border-t border-border pt-3">
              <p className="mb-2 text-xs text-muted-foreground">
                That address is not routable from here. To open the admin UI, forward
                the port and browse to{' '}
                <span className="font-mono text-foreground/80">
                  {endpoint.portForward.webUi}
                </span>
                :
              </p>
              <CodeBlock
                code={endpoint.portForward.command}
                language="plain"
                showLineNumbers={false}
                aria-label="port-forward command for the NICo admin UI"
              />
              <p className="mt-2 text-xs text-muted-foreground">
                Self-signed TLS, so your browser will warn.
                {controlPlane.webAuth !== 'none' && (
                  <>
                    {' '}
                    Auth is <span className="font-mono">{controlPlane.webAuth}</span> —
                    the credential is on the nico-api Deployment, not shown here.
                  </>
                )}{' '}
                The same address works as an endpoint override
                (<span className="font-mono">{endpoint.portForward.endpoint}</span>).
              </p>
            </div>
          )}
        </Section>

        <Section title="Client certificate" subtitle={`mTLS · Secret ${cert.secret}`}>
          {cert.present ? (
            <div className="space-y-0.5">
              <Field label="subject" value={cert.subject} mono />
              <Field label="issuer" value={cert.issuer} mono />
              <Field
                label="expires"
                value={
                  <span className={health.certExpiring ? 'text-warning' : undefined}>
                    {cert.notAfter?.slice(0, 10)}
                    {typeof cert.daysLeft === 'number' ? ` (${cert.daysLeft}d)` : ''}
                  </span>
                }
              />
              {cert.detail && <Field label="note" value={cert.detail} />}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {cert.detail || 'Not present — the Forge inventory cannot be read without it.'}
            </p>
          )}
        </Section>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section
          title="Datastore"
          subtitle="Postgres holds NICo's model, Vault its secrets, Temporal its workflows. None is part of NICo."
        >
          <div className="space-y-3">
            {dependencies.map((dep) => (
              <div key={dep.name}>
                <div className="mb-1 flex items-baseline justify-between gap-3">
                  <span className="text-xs font-medium text-foreground/80">{dep.name}</span>
                  {/* Which selector matched: a dependency found by its fallback
                      is worth distinguishing from one found as expected. */}
                  <span className="truncate font-mono text-[10px] text-muted-foreground">
                    {dep.selector ?? `nothing matched in ${dep.namespace}`}
                  </span>
                </div>
                {dep.pods.length > 0 ? (
                  <div className="space-y-1.5">
                    {dep.pods.map((pod) => (
                      <div key={pod.name}>
                        <PodRow pod={pod} />
                        {pod.labels && Object.keys(pod.labels).length > 0 && (
                          <div className="mt-0.5 flex flex-wrap gap-1 pl-1">
                            {Object.entries(pod.labels).map(([k, v]) => (
                              <span
                                key={k}
                                className={cn(
                                  'rounded px-1 py-0.5 font-mono text-[10px]',
                                  // A sealed Vault is the one label here that
                                  // means "this store cannot serve NICo".
                                  k === 'vault-sealed' && v === 'true'
                                    ? 'bg-warning/15 text-warning'
                                    : 'bg-muted text-muted-foreground',
                                )}
                              >
                                {k.replace('app.kubernetes.io/', '')}={v}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    no pod found in {dep.namespace}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Section>

        <Section
          title="Fleet inventory"
          subtitle="NICo's own machine/switch/rack tables."
        >
          {fleet ? (
            <div className="space-y-0.5">
              <Field label="machines" value={fleet.machines} />
              <Field label="switches" value={fleet.switches} />
              <Field label="racks" value={fleet.racks} />
              <Field label="instances" value={fleet.instances} />
              {fleet.machines === 0 && dpf.total > 0 && (
                /* An empty /admin/machine page is the expected state here, not
                   a fault: DPU lifecycle in this lab is DPF Zero-Touch, which
                   never registers anything with NICo's provisioning pipeline. */
                <p className="mt-2 text-xs text-muted-foreground">
                  Empty by design — DPU lifecycle is DPF-owned here ({dpf.ready}/{dpf.total} DPUs
                  Ready via DPF Zero-Touch, not NICo fleet provisioning).
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Not read.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

// ── Tenants ───────────────────────────────────────────────────────────────

function TenantsTab({ tenants, pending }: { tenants: NicoTenant[]; pending: boolean }) {
  if (pending) return <InventoryPending />;
  if (tenants.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="No tenants"
        description="No VPC or load balancer in NICo carries a tenant organization."
      />
    );
  }
  return (
    <Section
      title="Tenants"
      subtitle="Derived from what owns a VPC or a load balancer — NICo's Tenant table is unused in this deployment."
    >
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Tenant</th>
              <th className="py-2 pr-4 font-medium">VPCs</th>
              <th className="py-2 pr-4 font-medium">VNI</th>
              <th className="py-2 pr-4 font-medium">VIP prefix</th>
              <th className="py-2 pr-4 font-medium">LB services</th>
              <th className="py-2 font-medium">VIPs</th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id} className="border-b border-border/50 last:border-0">
                <td className="py-2 pr-4 font-medium text-foreground/90">{t.id}</td>
                <td className="py-2 pr-4 text-muted-foreground">{t.vpcCount}</td>
                <td className="py-2 pr-4 font-mono text-muted-foreground">
                  {t.vnis.join(', ') || '—'}
                </td>
                <td className="py-2 pr-4 font-mono text-muted-foreground">
                  {t.vipPrefixes.join(', ') || '—'}
                </td>
                <td className="py-2 pr-4">
                  <span
                    className={
                      t.lbsReady === t.lbCount ? 'text-success' : 'text-warning'
                    }
                  >
                    {t.lbsReady}/{t.lbCount} ready
                  </span>
                </td>
                <td className="py-2 font-mono text-muted-foreground">
                  {t.vips.join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ── Load balancers ────────────────────────────────────────────────────────

function LbCard({ lb }: { lb: NicoLoadBalancer }) {
  const ready = lb.status === 'READY';
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-foreground">{lb.name}</h3>
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {lb.tenant}
            </Badge>
            {Object.entries(lb.labels).map(([k, v]) => (
              <Badge key={k} variant="muted" className="px-1.5 py-0 text-[10px]">
                {k}={v}
              </Badge>
            ))}
          </div>
          {lb.description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{lb.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm text-foreground/90">{lb.vip || '—'}</span>
          <Badge variant={ready ? 'success' : 'warning'} className="gap-1">
            {ready ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <AlertTriangle className="h-3 w-3" />
            )}
            {lb.status || 'UNKNOWN'}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-0.5">
          <Field label="provider" value={lb.provider} />
          {/* How many TMM pods actually took the config — the difference
              between "NICo accepted it" and "the dataplane is serving it". */}
          <Field label="programmed pods" value={lb.programmedPods ?? '—'} />
          <Field label="declTmm generation" value={lb.declTmmGeneration ?? '—'} />
          <Field label="updated" value={lb.updated?.slice(0, 19).replace('T', ' ')} />
          <Field label="vpc" value={lb.vpcId} mono />
        </div>

        <div className="space-y-2">
          {lb.listeners.map((ln) => (
            <div
              key={`${ln.name}-${ln.port}`}
              className="rounded bg-muted/50 px-3 py-2 text-xs"
            >
              <span className="font-medium text-foreground/80">
                {ln.name} · {ln.protocol}/{ln.port}
              </span>
              <span className="ml-2 text-muted-foreground">→ pool {ln.poolName}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {lb.pools.map((pool) => (
          <div key={pool.name} className="rounded border border-border/60 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-medium text-foreground/80">pool {pool.name}</span>
              <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                {pool.lbMethod}
              </Badge>
              <span className="text-muted-foreground">
                {pool.members.length} member{pool.members.length === 1 ? '' : 's'}
                {pool.minActiveMembers ? ` · min active ${pool.minActiveMembers}` : ''}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {pool.members.map((m) => (
                <span
                  key={`${m.address}:${m.port}`}
                  className="rounded bg-muted/50 px-2 py-0.5 font-mono text-[11px] text-foreground/80"
                >
                  {m.address}:{m.port}
                </span>
              ))}
            </div>
            {pool.monitors.length > 0 && (
              <div className="mt-2 space-y-1">
                {pool.monitors.map((mon) => (
                  <p key={mon.name} className="text-[11px] text-muted-foreground">
                    monitor {mon.name} · {mon.type} · every {mon.intervalSec}s, timeout{' '}
                    {mon.timeoutSec}s
                    {mon.recv ? ` · expects ${JSON.stringify(mon.recv)}` : ''}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadBalancersTab({
  lbs,
  pending,
  capability,
}: {
  lbs: NicoLoadBalancer[];
  pending: boolean;
  capability: NicoCapability;
}) {
  if (pending) return <InventoryPending />;
  // Not "no load balancers configured" — there is no such thing here to configure.
  if (capability !== 'available') return <CapabilityNote what="load balancer" state={capability} />;
  if (lbs.length === 0) {
    return (
      <EmptyState
        icon={Route}
        title="No load balancer services"
        description="No tenant has declared one in NICo."
      />
    );
  }
  return (
    <div className="space-y-4">
      {lbs.map((lb) => (
        <LbCard key={lb.id} lb={lb} />
      ))}
    </div>
  );
}

// ── Network ───────────────────────────────────────────────────────────────

function NetworkTab({ data }: { data: NicoDataResponse }) {
  if (data.health.inventoryPending === true) return <InventoryPending />;
  const domainsCap: NicoCapability = data.health.capabilities?.domains ?? 'available';
  const { vpcs = [], networkSegments = [], domains = [] } = data.inventory;

  return (
    <div className="space-y-4">
      <Section title="VPCs" subtitle="One per tenant, each with its own VNI and VIP prefix.">
        {vpcs.length === 0 ? (
          <p className="text-xs text-muted-foreground">None.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Tenant</th>
                  <th className="py-2 pr-4 font-medium">VNI</th>
                  <th className="py-2 pr-4 font-medium">Type</th>
                  <th className="py-2 pr-4 font-medium">VIP prefixes</th>
                  <th className="py-2 font-medium">Id</th>
                </tr>
              </thead>
              <tbody>
                {vpcs.map((v) => (
                  <tr key={v.id} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4 font-medium text-foreground/90">{v.tenant}</td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">{v.vni ?? '—'}</td>
                    <td className="py-2 pr-4 text-muted-foreground">
                      {v.virtualizationType?.replace(/_/g, ' ').toLowerCase()}
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">
                      {v.prefixes
                        .map((p) => `${p.prefix} (${p.available}/${p.total} free)`)
                        .join(', ') || '—'}
                    </td>
                    <td className="py-2 font-mono text-[10px] text-muted-foreground">{v.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section
        title="Network segments"
        subtitle="The underlay and admin networks NICo owns IPAM for."
      >
        {networkSegments.length === 0 ? (
          <p className="text-xs text-muted-foreground">None.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Type</th>
                  <th className="py-2 pr-4 font-medium">MTU</th>
                  <th className="py-2 pr-4 font-medium">Prefix</th>
                  <th className="py-2 pr-4 font-medium">Gateway</th>
                  <th className="py-2 font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {networkSegments.map((s) => (
                  <tr key={s.id} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4 font-medium text-foreground/90">{s.name}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{s.type}</td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">{s.mtu}</td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">
                      {s.prefixes.map((p) => p.prefix).join(', ')}
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">
                      {s.prefixes.map((p) => p.gateway).join(', ')}
                    </td>
                    <td className="py-2">
                      <Badge
                        variant={s.state === 'READY' ? 'success' : 'muted'}
                        className="px-1.5 py-0 text-[10px]"
                      >
                        {s.state || 'unknown'}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="DNS zones" subtitle="Served by NICo's own authoritative DNS.">
        {/* `GetAllDomains` answers 403 for a cert that reads VPCs happily —
            Forge authorizes per method. "None." would be a claim we cannot
            make from a refusal. */}
        {domainsCap !== 'available' ? (
          <CapabilityNote what="DNS zone" state={domainsCap} />
        ) : domains.length === 0 ? (
          <p className="text-xs text-muted-foreground">None.</p>
        ) : (
          <div className="space-y-1.5">
            {domains.map((d) => (
              <div
                key={d.id}
                className="flex items-center justify-between rounded bg-muted/50 px-3 py-1.5 text-xs"
              >
                <span className="font-mono text-foreground/80">{d.zone}</span>
                <span className="text-muted-foreground">
                  {d.kind} · serial {d.serial}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

// ── Deployment ────────────────────────────────────────────────────────────

/** The site beyond nico-api, grouped by component and namespace. */
function EstateSection({ estate }: { estate: NicoEstateComponent[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (estate.length === 0) return null;

  // Namespaces in the order the backend sorted them, so a stack stays together.
  const namespaces = [...new Set(estate.map((c) => c.namespace))];
  const down = estate.filter((c) => c.ready < c.total).length;

  return (
    <Section
      title="Site components"
      subtitle={
        `The rest of the NICo site — none of it reachable through Forge` +
        (down > 0 ? ` · ${down} not fully ready` : '')
      }
    >
      <div className="space-y-3">
        {namespaces.map((ns) => (
          <div key={ns}>
            <p className="mb-1 font-mono text-[10px] text-muted-foreground">{ns}</p>
            <div className="flex flex-wrap gap-1.5">
              {estate
                .filter((c) => c.namespace === ns)
                .map((c) => {
                  const key = `${c.namespace}/${c.name}`;
                  const ok = c.ready === c.total;
                  return (
                    <button
                      key={key}
                      onClick={() => setExpanded(expanded === key ? null : key)}
                      className={cn(
                        'rounded border px-2 py-1 text-xs transition-colors',
                        expanded === key && 'ring-1 ring-ring',
                        ok
                          ? 'border-border bg-card text-foreground/80 hover:bg-muted/50'
                          : 'border-warning/40 bg-warning/10 text-warning',
                      )}
                    >
                      {c.name}{' '}
                      <span className="font-mono text-[10px]">
                        {c.ready}/{c.total}
                      </span>
                    </button>
                  );
                })}
            </div>
          </div>
        ))}
        {/* Pods only for the component you asked about — thirty-odd pod rows
            at once is a wall, not a view. */}
        {expanded && (
          <div className="space-y-1.5 border-t border-border pt-3">
            {estate
              .find((c) => `${c.namespace}/${c.name}` === expanded)
              ?.pods.map((pod) => <PodRow key={pod.name} pod={pod} />)}
          </div>
        )}
      </div>
    </Section>
  );
}

function DeploymentTab({ data }: { data: NicoDataResponse }) {
  const { controlPlane, providers, inventory, estate } = data;
  const versions = inventory.dpfServiceVersions ?? [];

  return (
    <div className="space-y-4">
      <Section title="nico-api" subtitle={`Namespace ${controlPlane.namespace}`}>
        <div className="space-y-1.5">
          {controlPlane.pods.length === 0 ? (
            <p className="text-xs text-muted-foreground">No nico-api pod is running.</p>
          ) : (
            controlPlane.pods.map((pod) => <PodRow key={pod.name} pod={pod} />)
          )}
        </div>
      </Section>

      <EstateSection estate={estate} />

      <Section
        title="LB providers"
        subtitle="Operators that poll NICo and realize what it holds on a dataplane."
      >
        {providers.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            None running. NICo will accept load balancer services and nothing will program them.
          </p>
        ) : (
          <div className="space-y-3">
            {providers.map((p) => (
              <div key={p.name} className="rounded border border-border/60 p-3">
                <PodRow pod={p.pod} />
                <div className="mt-2 space-y-0.5">
                  {Object.entries(p.config).map(([k, v]) => (
                    <Field key={k} label={k} value={v} mono />
                  ))}
                </div>
                {p.recentErrors.length > 0 && (
                  /* A provider that cannot reach NICo stays Running and Ready
                     forever; its log is the only place that shows up. Scoped
                     to the last hour by the backend — the reconciler logs a
                     failed poll and nothing on recovery, so an unbounded read
                     shows a long-recovered cold start as a live outage. */
                  <div className="mt-2 space-y-1">
                    <p className="text-xs font-medium text-warning">Log errors (last hour)</p>
                    {p.recentErrors.map((line, i) => (
                      <p
                        key={i}
                        className="break-all rounded bg-muted/50 px-2 py-1 font-mono text-[10px] text-muted-foreground"
                      >
                        {line}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {versions.length > 0 && (
        <Section
          title="DPU service catalogue"
          subtitle="Versions NICo would deploy to a DPU it provisioned itself."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Service</th>
                  <th className="py-2 pr-4 font-medium">Helm</th>
                  <th className="py-2 font-medium">Image tag</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.service} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4 font-medium text-foreground/90">{v.service}</td>
                    <td className="py-2 pr-4 font-mono text-muted-foreground">
                      {v.configHelmVersion || '—'}
                    </td>
                    <td className="py-2 font-mono text-muted-foreground">
                      {v.configDockerImageTag || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}

// ── Skeleton / empty ──────────────────────────────────────────────────────

function NicoSkeleton() {
  return (
    <div className="space-y-6">
      {/* Measured on the reference lab over a VPN: ~32s cold, ~12s once the
          Forge descriptor pool is cached. The skeleton alone gave no reason to
          believe any of that was happening. */}
      <CollectingState
        title="Collecting NICo inventory"
        detail="One read covers both halves: the Kubernetes deployment, and everything NICo holds behind its Forge gRPC API."
        steps={[
          'nico-api pods, Services and mTLS client certificate',
          'Postgres / Vault / Temporal dependencies, LB providers, DPU counts',
          'Forge session — tenants, VPCs, network segments, load balancers',
        ]}
        slowAfterSeconds={12}
        slowNote="Forge publishes no CRDs and ships no proto, so its schema is read off the server — ~475 method descriptors across 13 files. That walk is cached per nico-api build, so the first read after a restart or an upgrade is the slow one."
      />
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-48" />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────

type NicoTab = 'overview' | 'tenants' | 'loadbalancers' | 'network' | 'deployment';

const TABS: { key: NicoTab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'tenants', label: 'Tenants' },
  { key: 'loadbalancers', label: 'Load Balancers' },
  { key: 'network', label: 'Network' },
  { key: 'deployment', label: 'Deployment' },
];

export function NICoPanel({ clusterId }: NICoPanelProps) {
  const [activeTab, setActiveTab] = useState<NicoTab>('overview');
  const deployment = useNicoDeployment(clusterId);
  // Gated on the deployment half rather than fired alongside it: that request
  // memoizes the endpoint resolution, so running them concurrently would make
  // each pay the ~2.9s TCP screen separately.
  const inventory = useNicoInventory(clusterId, {
    enabled: deployment.data?.detected === true,
  });

  const dep = deployment.data;
  const inv = inventory.data;

  // Recombined into the shape every sub-view below already consumed, so the
  // split stops at this line.
  const data: NicoDataResponse | undefined = dep && {
    ...dep,
    inventory: inv?.inventory ?? {},
    errors: [...dep.errors, ...(inv?.errors ?? [])],
    health: {
      ...dep.health,
      ...(inv?.counts ?? PENDING_COUNTS),
      inventoryPending: !inv,
    },
  };

  if (deployment.isLoading) return <NicoSkeleton />;
  if (deployment.error) return <ErrorState error={deployment.error} size="sm" />;

  if (!data || !data.detected) {
    return (
      <EmptyState
        icon={Globe}
        title="NICo not installed"
        description="No nico-api pod is running on this cluster."
      />
    );
  }

  const health = data.health;
  const pending = health.inventoryPending === true;
  const caps = health.capabilities ?? {};
  // Until the Forge half lands we do not know what this build supports, so
  // assume it does — the tab shows its own pending state either way.
  const lbCap: NicoCapability = pending ? 'available' : (caps.loadBalancers ?? 'available');
  const tenants = data.inventory.tenants ?? [];
  const lbs = data.inventory.loadBalancers ?? [];
  // No badge on a tab whose count is not known yet — "(0)" would read as an
  // answer. The deployment tab is fed by the half that has already landed.
  const counts: Partial<Record<NicoTab, number>> = {
    ...(pending
      ? {}
      : {
          tenants: tenants.length,
          loadbalancers: lbs.length,
          network:
            (data.inventory.vpcs?.length ?? 0) + (data.inventory.networkSegments?.length ?? 0),
        }),
    deployment:
      data.controlPlane.pods.length + data.providers.length + data.estate.length,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-lg font-semibold text-foreground">NICo</h3>
          <StatusBadge status={health.status} />
          {health.version && (
            <Badge variant="outline" className="text-xs">
              {health.version}
            </Badge>
          )}
          {data.controlPlane.webAuth === 'none' && (
            <Badge variant="warning" className="gap-1 text-xs">
              <ShieldCheck className="h-3 w-3" /> web UI unauthenticated
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Linked only when the address answered our own TCP screen. It
              used to link the advertised address unconditionally, which on a
              lab subnet meant a click straight into a browser timeout. */}
          {data.endpoint.webUi && data.endpoint.webUiReachable && (
            <a
              className="inline-flex items-center gap-1 text-xs text-info hover:underline"
              href={data.endpoint.webUi}
              target="_blank"
              rel="noreferrer"
            >
              admin UI <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {(deployment.isFetching || inventory.isFetching) && (
            <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
          )}
        </div>
      </div>

      {/* Soft failures. The page below is still true for whatever it could
          read — say what is missing rather than blanking the tab. */}
      {data.errors.length > 0 && (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-3">
          {data.errors.map((e, i) => (
            <p key={i} className="flex items-start gap-2 text-xs text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {e}
            </p>
          ))}
        </div>
      )}

      <div className="flex gap-1 rounded-lg border border-border bg-muted/50 p-1">
        {TABS.filter((tab) => tab.key !== 'loadbalancers' || lbCap === 'available').map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              'flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors',
              activeTab === tab.key
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
            {counts[tab.key] ? (
              <span className="ml-1.5 text-xs text-muted-foreground">({counts[tab.key]})</span>
            ) : null}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && <OverviewTab data={data} />}
      {activeTab === 'tenants' && <TenantsTab tenants={tenants} pending={pending} />}
      {activeTab === 'loadbalancers' && (
        <LoadBalancersTab lbs={lbs} pending={pending} capability={lbCap} />
      )}
      {activeTab === 'network' && <NetworkTab data={data} />}
      {activeTab === 'deployment' && <DeploymentTab data={data} />}
    </div>
  );
}
