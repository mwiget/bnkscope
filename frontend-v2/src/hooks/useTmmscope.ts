/**
 * tmmscope status and per-cluster telemetry.
 *
 * Polled, not pushed: the answer changes when someone runs `tmmscope up` or
 * `tmmscope inject` in a terminal, and there is no event to subscribe to. The
 * interval is slow because both queries hit the host's Prometheus and Grafana,
 * and "the stack came up" is not urgent news.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { queryKeys } from '@/lib/queryKeys';
import { QUERY_STALE_TIME, POLL_INTERVALS } from '@/lib/constants';
import { useAppMutation } from '@/hooks/lib/useAppMutation';
import { notify } from '@/lib/notify';

export function useTmmscopeStatus() {
  return useQuery({
    queryKey: queryKeys.tmmscope.status(),
    queryFn: api.getStatus,
    staleTime: QUERY_STALE_TIME.DEFAULT,
    refetchInterval: POLL_INTERVALS.SLOW,
  });
}

/**
 * @param settling poll fast while waiting for something to change — the gap
 *   between injecting an exporter and its first metrics arriving. At the SLOW
 *   interval that gap is up to 30 seconds of a page that looks like nothing
 *   happened, which is how you get someone clicking inject twice.
 */
export function useClusterTelemetry(
  clusterId: number | null,
  theme: 'dark' | 'light',
  settling = false,
) {
  return useQuery({
    queryKey: queryKeys.tmmscope.cluster(clusterId ?? 0, theme),
    queryFn: () => api.getClusterTelemetry(clusterId as number, theme),
    enabled: !!clusterId,
    staleTime: settling ? 0 : QUERY_STALE_TIME.DEFAULT,
    refetchInterval: settling ? POLL_INTERVALS.FAST : POLL_INTERVALS.SLOW,
  });
}

/**
 * Bind this cluster to a tmmscope `cluster=` label, or clear the binding.
 *
 * Needed because the two tools share no identifier: `tmmscope inject
 * --cluster` names the label freely. bnkscope matches on the conventions it
 * can (context, its `user@cluster` half, the namespace) and this covers the
 * rest.
 */
export function useBindTmmscopeLabel(theme: 'dark' | 'light') {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({ clusterId, label }: { clusterId: number; label: string | null }) =>
      api.bindClusterLabel(clusterId, label, theme),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tmmscope.all });
      notify.success(
        data.streaming ? `Watching ${data.streaming_as}` : 'Binding cleared',
        data.streaming
          ? `${data.cluster_name} is bound to the tmmscope cluster label "${data.streaming_as}".`
          : 'Back to matching by name.',
        { category: 'cluster' },
      );
    },
  });
}

/**
 * Which of this cluster's f5-tmm pods carry the exporter.
 *
 * Polled like the rest: an ephemeral container is gone the moment its pod is
 * recreated, and nothing re-adds it, so "injected" is a fact with a short shelf
 * life rather than a setting.
 */
export function useInjectionState(clusterId: number | null, settling = false) {
  return useQuery({
    queryKey: queryKeys.tmmscope.injection(clusterId ?? 0),
    queryFn: () => api.getInjection(clusterId as number),
    enabled: !!clusterId,
    staleTime: settling ? 0 : QUERY_STALE_TIME.DEFAULT,
    refetchInterval: settling ? POLL_INTERVALS.FAST : POLL_INTERVALS.SLOW,
  });
}

/** Add the exporter to every running f5-tmm pod. Does not restart TMM. */
export function useInjectExporter() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({ clusterId }: { clusterId: number }) => api.inject(clusterId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tmmscope.all });
      if (data.failed.length) {
        notify.warning(
          `Injected into ${data.added.length} of ${data.tmm_pods} pod(s)`,
          data.failed.map((f) => `${f.pod}: ${f.error}`).join('; '),
          { category: 'cluster' },
        );
        return;
      }
      notify.success(
        data.added.length ? 'Exporter injected' : 'Already injected',
        data.added.length
          ? 'Waiting for the first metrics to arrive.'
          : (data.detail ?? undefined),
        { category: 'cluster' },
      );
    },
  });
}

/**
 * Clear the exporter — by recreating the f5-tmm pods, which drops traffic.
 *
 * There is no gentler option: an ephemeral container cannot be removed from a
 * running pod. The caller must confirm first; see D-036 on why this direction
 * is deliberately harder than injecting.
 */
export function useRemoveInjection() {
  const queryClient = useQueryClient();

  return useAppMutation({
    mutationFn: ({ clusterId }: { clusterId: number }) => api.removeInjection(clusterId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tmmscope.all });
      notify.success('Exporter removed', data.detail ?? undefined, { category: 'cluster' });
    },
  });
}
