/**
 * Query-key factory.
 *
 * The keys themselves are trivial; what this pins is the *set*. The factory
 * carried 35 namespaces long after the features behind them were deleted —
 * projects, modules, tasks, drift, helm, operators, fleet, stacks, snapshots,
 * benchmarks and fifteen more — and nothing failed, because an unused key is
 * silent. Four `invalidateQueries({ queryKey: queryKeys.projects.all })` calls
 * survived in live cluster hooks as pure no-ops, which is the failure mode
 * that matters: an invalidation that looks like cache management and does
 * nothing.
 */
import { describe, it, expect } from 'vitest';
import { queryKeys } from '@/lib/queryKeys';

/** Every namespace, and only these. Adding one here means adding a consumer. */
const DOMAINS = [
  'k8s',
  'logs',
  'tmmscope',
  'system',
  'notifications',
  'mcp',
  'llmObservability',
] as const;

describe('queryKeys', () => {
  it('carries exactly the namespaces the app consumes', () => {
    expect(Object.keys(queryKeys).sort()).toEqual([...DOMAINS].sort());
  });

  describe('keys are readonly arrays', () => {
    it('k8s.all is an array', () => {
      expect(Array.isArray(queryKeys.k8s.all)).toBe(true);
      expect(queryKeys.k8s.all).toEqual(['k8s']);
    });

    it('system.all is an array', () => {
      expect(Array.isArray(queryKeys.system.all)).toBe(true);
      expect(queryKeys.system.all).toEqual(['system']);
    });
  });

  describe('parameterized keys include params', () => {
    it('k8s.clusters.resources includes all params', () => {
      const key = queryKeys.k8s.clusters.resources(1, 'pods', { namespace: 'default' });
      expect(key).toEqual(['k8s', 'clusters', 1, 'resources', 'pods', { namespace: 'default' }]);
    });

    it('logs.search includes params', () => {
      const params = { cluster: 'scope', minutes: 60 };
      expect(queryKeys.logs.search(params)).toEqual(['logs', 'search', params]);
    });
  });

  it('top-level keys are distinct', () => {
    // Two domains sharing a root would invalidate each other's caches.
    // `mcp` has no `all` — it is a single key, not a tree — so it is read
    // through its own entry rather than assumed into the same shape.
    const roots = DOMAINS.filter((d) => d !== 'mcp').map(
      (d) => (queryKeys[d] as { all: readonly string[] }).all[0],
    );
    expect(new Set(roots).size).toBe(roots.length);
  });
});
