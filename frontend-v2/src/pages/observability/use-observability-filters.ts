/**
 * Filter state for the AI Gateway observability pages, synced to the URL
 * search params (range/model/status/tab) so views are linkable and survive
 * reloads.
 *
 * The cluster is NOT one of those — it is the app-wide selection
 * (`useSelectedCluster`), the same one every other page reads. This page used
 * to keep its own in `?cluster=`, which meant changing cluster in the sidebar
 * did nothing here and the tiles sat on whatever this page had picked. Worse,
 * what it picked was a hard-coded guess — the first cluster whose name
 * contained "hgx" or whose context contained "kubernetes-admin" — so on a
 * machine with a DPF infrastructure cluster it reliably landed on the one
 * cluster that runs no gateway at all.
 *
 * `?cluster=` is still honoured on arrival, so existing links keep working:
 * it seeds the shared selection once and the URL then mirrors it rather than
 * owning it.
 */
import { useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAllClusters } from '@/hooks/useK8sClusters';
import { useSelectedCluster } from '@/hooks/useSelectedCluster';
import type { LlmTimeRange } from '@/types/llm-observability';

const RANGES: LlmTimeRange[] = ['1h', '6h', '24h', '7d'];

export interface ObservabilityFilters {
  clusterId: number | undefined;
  range: LlmTimeRange;
  model: string;
  status: string;
  tab: string;
  setClusterId: (id: number) => void;
  setRange: (r: LlmTimeRange) => void;
  setModel: (m: string) => void;
  setStatus: (s: string) => void;
  setTab: (t: string) => void;
  /** Params object for hooks: undefined for "all" filters. */
  queryParams: { range: LlmTimeRange; model?: string; status?: string };
}

export function useObservabilityFilters(defaultTab: string): ObservabilityFilters {
  const [params, setParams] = useSearchParams();
  const [selectedCluster, setSelectedCluster] = useSelectedCluster();
  const { data: clustersData } = useAllClusters();
  const clusters = useMemo(() => clustersData?.clusters ?? [], [clustersData]);

  const rangeParam = params.get('range');
  const range: LlmTimeRange = RANGES.includes(rangeParam as LlmTimeRange)
    ? (rangeParam as LlmTimeRange)
    : '1h';
  const model = params.get('model') ?? '';
  const status = params.get('status') ?? '';
  const tab = params.get('tab') ?? defaultTab;
  const clusterParam = params.get('cluster');
  const clusterId = selectedCluster ?? undefined;

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '') next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // A `?cluster=` on arrival is a deep link: adopt it as the app-wide
  // selection, once, then let the shared state drive.
  useEffect(() => {
    if (!clusterParam) return;
    const linked = Number(clusterParam);
    if (Number.isFinite(linked) && linked !== selectedCluster) setSelectedCluster(linked);
    // Only when the link itself changes — otherwise this would fight the
    // mirroring effect below every time the sidebar moves the selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterParam]);

  // Nothing selected anywhere yet: fall back to the first cluster, and write
  // it to the shared selection so the rest of the app agrees.
  useEffect(() => {
    if (selectedCluster != null || clusters.length === 0) return;
    setSelectedCluster(clusters[0].id);
  }, [selectedCluster, clusters, setSelectedCluster]);

  // Keep the URL reflecting the selection so a link still carries it.
  useEffect(() => {
    if (selectedCluster == null) return;
    if (clusterParam === String(selectedCluster)) return;
    update({ cluster: String(selectedCluster) });
  }, [selectedCluster, clusterParam, update]);

  return {
    clusterId,
    range,
    model,
    status,
    tab,
    // Writes through to the shared selection: picking a cluster here moves
    // the sidebar and every other page with it.
    setClusterId: (id) => setSelectedCluster(id),
    setRange: (r) => update({ range: r }),
    setModel: (m) => update({ model: m || null }),
    setStatus: (s) => update({ status: s || null }),
    setTab: (t) => update({ tab: t }),
    queryParams: {
      range,
      ...(model ? { model } : {}),
      ...(status ? { status } : {}),
    },
  };
}
