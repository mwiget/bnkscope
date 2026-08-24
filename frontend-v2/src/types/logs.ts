/**
 * Collected pod logs, searchable.
 *
 * bnkscope owns the controls and Loki does the work — the same split as TMM
 * Live. The filters compose into LogQL, and `query` returns what was actually
 * run so the UI can show it: the filters should teach the query language, not
 * conceal it.
 */

export interface LogEntry {
  /** Nanoseconds since the epoch, as Loki stores them. */
  timestamp: number;
  line: string;
  cluster: string | null;
  namespace: string | null;
  pod: string | null;
  container: string | null;
  level: string;
}

export interface LogSearchResult {
  ok: boolean;
  entries: LogEntry[];
  /** The LogQL that was executed. */
  query: string;
  count: number;
  available: boolean;
  detail: string | null;
}

export interface LogFilters {
  ok: boolean;
  available: boolean;
  clusters: string[];
  namespaces: string[];
  containers: string[];
  levels: string[];
  detail: string | null;
}

export interface LogSearchParams {
  cluster?: string;
  namespace?: string;
  pod?: string;
  container?: string;
  level?: string;
  search?: string;
  logql?: string;
  minutes?: number;
  limit?: number;
}
