/**
 * One cluster selection, shared by every page.
 *
 * The bug: picking a cluster on BNK Health and switching to Clusters showed
 * the previous one, because each page persisted to its own key — three of
 * them, inherited from bnk-forge where a page was scoped to a project and the
 * cluster was a detail of it.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useSelectedCluster } from '@/hooks/useSelectedCluster';
import { STORAGE_KEYS } from '@/lib/storage-keys';

beforeEach(() => {
  localStorage.clear();
});

describe('useSelectedCluster', () => {
  it('starts with nothing selected', () => {
    const { result } = renderHook(() => useSelectedCluster());
    expect(result.current[0]).toBeNull();
  });

  it('survives a remount — this is the whole point', () => {
    const first = renderHook(() => useSelectedCluster());
    act(() => first.result.current[1](7));
    first.unmount();

    // A different page mounting its own copy of the hook.
    const second = renderHook(() => useSelectedCluster());
    expect(second.result.current[0]).toBe(7);
  });

  it('keeps two mounted pages in step', () => {
    const a = renderHook(() => useSelectedCluster());
    const b = renderHook(() => useSelectedCluster());

    act(() => a.result.current[1](42));

    // `storage` does not fire in the tab that wrote it, so without an explicit
    // notification b would sit on a stale value until it remounted.
    expect(b.result.current[0]).toBe(42);
  });

  it('clears', () => {
    const { result } = renderHook(() => useSelectedCluster());
    act(() => result.current[1](3));
    act(() => result.current[1](null));

    expect(result.current[0]).toBeNull();
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_CLUSTER)).toBeNull();
  });

  describe('migrating from the per-page keys', () => {
    it.each([
      ['Clusters', STORAGE_KEYS.K8S_CLUSTER],
      ['BNK Health', STORAGE_KEYS.BNK_CLUSTER],
      ['CNF', STORAGE_KEYS.CNF_CLUSTER],
    ])('adopts an existing %s selection', (_page, key) => {
      // Upgrading should not silently drop the cluster someone was looking at.
      localStorage.setItem(key, '11');

      const { result } = renderHook(() => useSelectedCluster());
      expect(result.current[0]).toBe(11);
    });

    it('prefers the shared key over a stale per-page one', () => {
      localStorage.setItem(STORAGE_KEYS.K8S_CLUSTER, '11');
      localStorage.setItem(STORAGE_KEYS.SELECTED_CLUSTER, '22');

      const { result } = renderHook(() => useSelectedCluster());
      expect(result.current[0]).toBe(22);
    });

    it('does not write back to the superseded keys', () => {
      localStorage.setItem(STORAGE_KEYS.K8S_CLUSTER, '11');

      const { result } = renderHook(() => useSelectedCluster());
      act(() => result.current[1](99));

      expect(localStorage.getItem(STORAGE_KEYS.SELECTED_CLUSTER)).toBe('99');
      // Left as it was: dead, not maintained in parallel.
      expect(localStorage.getItem(STORAGE_KEYS.K8S_CLUSTER)).toBe('11');
    });
  });

  it('ignores a corrupt stored value', () => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_CLUSTER, 'not-a-number');
    const { result } = renderHook(() => useSelectedCluster());
    expect(result.current[0]).toBeNull();
  });
});
