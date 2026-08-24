/**
 * Unified cluster reachability badge — single source of truth.
 *
 * Reads from the SSE-driven reachability registry. There used to be two probe
 * types to choose between here; SSH tunnels went in Phase 3, so every cluster
 * is probed directly over its kubeconfig and the branch went with them.
 *
 * Visual: Network glyph + warning-pulse / success / destructive / muted, tooltip
 * carries the diagnostic so users see *why* not just *what*.
 */
import { Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTargetConnectivity } from '@/hooks/useConnectivity';

interface ClusterLike {
  id: number;
  name: string;
}

interface ClusterStatusBadgeProps {
  cluster: ClusterLike;
  /** Show the cluster name next to the icon. */
  showLabel?: boolean;
  /**
   * Show the state text (Reachable / Offline / Checking…) next to the icon.
   * Use everywhere the page would otherwise render its own derived offline /
   * fleet / bnk-severity label — keeps every page reading from the same source.
   */
  showStatusLabel?: boolean;
}

type State = 'checking' | 'reachable' | 'unreachable' | 'unknown';

export function ClusterStatusBadge({
  cluster,
  showLabel = false,
  showStatusLabel = false,
}: ClusterStatusBadgeProps) {
  const { state: registryState } = useTargetConnectivity('cluster', cluster.id);

  const method = 'cluster reachability probe';
  const value = registryState?.state ?? 'unknown';

  let state: State;
  let message: string;
  if (value === 'reachable') {
    state = 'reachable';
    message = registryState?.error_context?.target_name
      ? `${registryState.error_context.target_name} is reachable.`
      : 'Reachable.';
  } else if (value === 'unreachable') {
    state = 'unreachable';
    message =
      (registryState?.error_context?.suggested_action as string | undefined) ||
      'Unreachable.';
  } else {
    // Cold start — honest "checking" rather than fail-open.
    state = registryState ? 'unknown' : 'checking';
    message = registryState ? 'No probe data yet.' : 'Probing…';
  }

  const iconClass =
    state === 'checking' ? 'text-warning animate-pulse'
    : state === 'reachable' ? 'text-success'
    : state === 'unreachable' ? 'text-destructive'
    : 'text-muted-foreground';

  const stateLabel =
    state === 'checking' ? 'Checking'
    : state === 'reachable' ? 'Reachable'
    : state === 'unreachable' ? 'Offline'
    : 'Unknown';

  const stateLabelClass =
    state === 'checking' ? 'text-warning'
    : state === 'reachable' ? 'text-success'
    : state === 'unreachable' ? 'text-destructive'
    : 'text-muted-foreground';

  const tooltip = `${cluster.name} — ${stateLabel} via ${method}. ${message}`;

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={tooltip}
      aria-label={tooltip}
    >
      <Network className={cn('h-4 w-4', iconClass)} />
      {showLabel && (
        <span className="text-xs text-muted-foreground">
          {cluster.name}
        </span>
      )}
      {showStatusLabel && (
        <span className={cn('text-[11px] font-medium', stateLabelClass)}>
          {stateLabel}
        </span>
      )}
    </span>
  );
}
