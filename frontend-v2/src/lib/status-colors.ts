/**
 * Centralized status color definitions — token-pure (D-020).
 *
 * All classes reference semantic design tokens (success / warning / destructive /
 * info / muted) instead of raw palette classes.  Callers keep their existing
 * function signatures; only the emitted class strings change.
 */

/**
 * Kubernetes/Helm resource status colors (pattern-based)
 * Used for K8s pods, deployments, services, and Helm releases
 *
 * @param status - Status string from K8s/Helm resource
 * @returns Tailwind CSS classes for badge styling
 */
export function getResourceStatusColor(status: string): string {
  if (!status) return 'bg-muted text-muted-foreground border-border';

  const statusLower = status.toLowerCase();

  // Error/Failed states (CHECK FIRST - before "ready" substring match)
  if (
    statusLower.includes('failed') ||
    statusLower.includes('error') ||
    statusLower.includes('crashloopbackoff') ||
    statusLower.includes('imagepullbackoff') ||
    statusLower.includes('uninstalled') ||
    statusLower.includes('notready')  // Must check before "ready"
  ) {
    return 'bg-destructive/10 text-destructive border-destructive/20';
  }

  // Success states (after error checks)
  if (
    statusLower.includes('running') ||
    statusLower.includes('ready') ||
    statusLower.includes('deployed') ||
    statusLower.includes('active') ||
    statusLower.includes('bound')
  ) {
    return 'bg-success/10 text-success border-success/20';
  }

  // Warning/Pending states
  if (
    statusLower.includes('pending') ||
    statusLower.includes('waiting') ||
    statusLower.includes('superseded') ||
    statusLower.includes('unknown') ||
    statusLower.includes('partial')
  ) {
    return 'bg-warning/10 text-warning border-warning/20';
  }

  // Terminating/Removing states
  if (
    statusLower.includes('terminating') ||
    statusLower.includes('deleting') ||
    statusLower.includes('uninstalling')
  ) {
    return 'bg-muted text-muted-foreground border-border';
  }

  // Default neutral state
  return 'bg-muted text-muted-foreground border-border';
}

