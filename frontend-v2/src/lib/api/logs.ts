/**
 * Log search API.
 */
import { apiClient } from './client';
import type { LogFilters, LogSearchParams, LogSearchResult } from '@/types/logs';

export const logsApi = {
  getLogFilters: () =>
    apiClient.get<LogFilters>('/api/logs/filters').then((res) => res.data),

  searchLogs: (params: LogSearchParams) =>
    apiClient
      // Drop empty values rather than sending `cluster=`: the backend treats
      // an empty string as "no filter" too, but the executed query it echoes
      // back is cleaner without them.
      .get<LogSearchResult>('/api/logs/search', {
        params: Object.fromEntries(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== ''),
        ),
      })
      .then((res) => res.data),
};
