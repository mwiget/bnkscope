/**
 * Searching the collected logs.
 *
 * Two queries: the filter vocabulary, which changes slowly, and the search
 * itself, which is whatever the operator just typed. The search is deliberately
 * not polled — a result set that reshuffles under you while you are reading it
 * is worse than one you refresh yourself. Live tail is what Grafana Explore is
 * for, and it is a click away.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { queryKeys } from '@/lib/queryKeys';
import { QUERY_STALE_TIME } from '@/lib/constants';
import type { LogSearchParams } from '@/types/logs';

export function useLogFilters() {
  return useQuery({
    queryKey: queryKeys.logs.filters(),
    queryFn: api.getLogFilters,
    staleTime: QUERY_STALE_TIME.DEFAULT,
  });
}

export function useLogSearch(params: LogSearchParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.search(params as Record<string, unknown>),
    queryFn: () => api.searchLogs(params),
    enabled,
    staleTime: 0,
    // Keep the previous page of results on screen while the next one loads.
    // Without this every keystroke in the search box blanks the list, which
    // makes typing feel like the results are being destroyed and rebuilt.
    placeholderData: keepPreviousData,
  });
}
