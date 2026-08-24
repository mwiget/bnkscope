/**
 * The cluster you are looking at — one selection, shared by every page.
 *
 * bnk-forge kept a separate one per page, because a page was scoped to a
 * project and the cluster was a detail of it. bnkscope has a flat cluster list
 * and one question — *what is wrong with this cluster* — so picking it on BNK
 * Health and finding Clusters still on the previous one is just a lost click,
 * repeated on every navigation.
 *
 * The old per-page keys are read once as a fallback so an existing selection
 * survives the change rather than silently resetting to nothing.
 */
import { useCallback, useEffect, useState } from 'react';

import { STORAGE_KEYS } from '@/lib/storage-keys';

/** Superseded per-page keys, newest-relevant first. Read, never written. */
const LEGACY_KEYS = [
  STORAGE_KEYS.K8S_CLUSTER,
  STORAGE_KEYS.BNK_CLUSTER,
  STORAGE_KEYS.CNF_CLUSTER,
] as const;

function readStored(): number | null {
  for (const key of [STORAGE_KEYS.SELECTED_CLUSTER, ...LEGACY_KEYS]) {
    const raw = localStorage.getItem(key);
    if (!raw) continue;
    const id = Number.parseInt(raw, 10);
    if (Number.isFinite(id)) return id;
  }
  return null;
}

/**
 * Shared selected-cluster state, persisted and synchronised across pages.
 *
 * Changes propagate to other mounted components in this tab through a custom
 * event: `storage` only fires in *other* tabs, so it cannot be relied on for
 * the case that matters here — two components on the same page disagreeing.
 */
const CHANGED = 'bnkscope:selected-cluster';

export function useSelectedCluster(): [number | null, (id: number | null) => void] {
  const [selected, setSelected] = useState<number | null>(readStored);

  useEffect(() => {
    const sync = () => setSelected(readStored());
    window.addEventListener(CHANGED, sync);
    // Another tab. Same tool, same machine, same person — keep them in step.
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(CHANGED, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const select = useCallback((id: number | null) => {
    if (id === null) {
      localStorage.removeItem(STORAGE_KEYS.SELECTED_CLUSTER);
    } else {
      localStorage.setItem(STORAGE_KEYS.SELECTED_CLUSTER, String(id));
    }
    setSelected(id);
    window.dispatchEvent(new Event(CHANGED));
  }, []);

  return [selected, select];
}
