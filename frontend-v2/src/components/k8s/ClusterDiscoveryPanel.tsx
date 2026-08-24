/**
 * What bnkscope found in your kubeconfig.
 *
 * Contexts carrying an F5/BNK namespace register themselves; this panel is for
 * everything else — the ones that were only reported, and the ones that could
 * not be probed at all. Both need the same thing from the UI: say what was
 * found, say plainly why it is not a cluster yet, and offer the one action that
 * changes that.
 *
 * The refresh is a real sweep, not a cache read: it re-probes every context.
 * That is why it is a button and not a poll.
 */
import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, RefreshCw, Server, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingButton } from '@/components/ui/loading-button';
import { SectionCard } from '@/components/ui/section-card';
import { useAdoptContext, useDiscovery } from '@/hooks/useK8s';
import type { DiscoveryCandidate } from '@/types';

const STATE_BADGE: Record<
  DiscoveryCandidate['state'],
  { variant: 'success' | 'destructive' | 'warning'; label: string; icon: typeof CheckCircle2 }
> = {
  reachable: { variant: 'success', label: 'Reachable', icon: CheckCircle2 },
  unreachable: { variant: 'destructive', label: 'Unreachable', icon: XCircle },
  unusable: { variant: 'warning', label: 'Cannot use', icon: AlertTriangle },
};

function CandidateRow({ candidate }: { candidate: DiscoveryCandidate }) {
  const adopt = useAdoptContext();
  const badge = STATE_BADGE[candidate.state];
  const StateIcon = badge.icon;

  return (
    <div className="flex items-start justify-between gap-4 border-b border-border py-3 last:border-0">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">{candidate.context}</span>
          <Badge variant={badge.variant}>
            <StateIcon className="mr-1 h-3 w-3" />
            {badge.label}
          </Badge>
          {candidate.registered && <Badge variant="info">Added</Badge>}
          {candidate.has_bnk && <Badge variant="success">BNK</Badge>}
          {candidate.version && <Badge variant="muted">v{candidate.version}</Badge>}
        </div>

        <p className="mt-1 truncate text-xs text-muted-foreground">
          {candidate.api_server ?? 'no API server URL'} · {candidate.cloud_provider} ·{' '}
          {candidate.auth_method}
        </p>

        {candidate.detail && (
          <p className="mt-1 text-xs text-muted-foreground">{candidate.detail}</p>
        )}
      </div>

      {/* Adding is only possible for something we could actually reach. An
          unusable context needs a fix on the host first — the detail says
          which — and an unreachable one would register a cluster that cannot
          answer a single query. */}
      {!candidate.registered && candidate.state === 'reachable' && (
        <LoadingButton
          size="sm"
          variant="outline"
          loading={adopt.isPending}
          loadingText="Adding…"
          onClick={() => adopt.mutate(candidate.context)}
        >
          <Plus className="mr-1 h-4 w-4" />
          Add
        </LoadingButton>
      )}
    </div>
  );
}

export function ClusterDiscoveryPanel({ className }: { className?: string }) {
  // Not fetched on mount by default in the empty-state case: the caller decides
  // when a sweep is worth its seconds.
  const [enabled, setEnabled] = useState(true);
  const { data, isLoading, isFetching, refetch, error } = useDiscovery({ enabled });

  const candidates = data?.candidates ?? [];
  const unregistered = candidates.filter((c) => !c.registered);

  return (
    <SectionCard title="Discovered from your kubeconfig" className={className}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Contexts in <code className="text-xs">~/.kube/config</code>. Clusters running BNK are
          added automatically; anything else is listed here.
        </p>
        <Button
          size="sm"
          variant="outline"
          disabled={isFetching}
          onClick={() => {
            setEnabled(true);
            void refetch();
          }}
        >
          <RefreshCw className={`mr-1 h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          Rescan
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-destructive">Could not read the local kubeconfig.</p>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Probing contexts…</p>
      ) : candidates.length === 0 ? (
        <div className="py-6 text-center">
          <Server className="mx-auto mb-2 h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">No kube contexts found</p>
          <p className="mt-1 text-xs text-muted-foreground">
            bnkscope reads <code>~/.kube/config</code> from the host, mounted read-only. If you
            have contexts there, check that the mount is present in docker-compose.yml.
          </p>
        </div>
      ) : (
        <>
          <div>
            {candidates.map((candidate) => (
              <CandidateRow key={candidate.context} candidate={candidate} />
            ))}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {data?.found} context{data?.found === 1 ? '' : 's'} found ·{' '}
            {data?.registered} registered · {unregistered.length} not added
          </p>
        </>
      )}
    </SectionCard>
  );
}
