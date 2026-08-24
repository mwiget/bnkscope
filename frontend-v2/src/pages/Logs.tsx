/**
 * Logs — search everything the collector has, across every cluster.
 *
 * The question this answers is "what did something say, and when": narrow with
 * the filters, or type LogQL when the filters cannot ask it. The executed query
 * is always on screen, because the fastest way to learn LogQL is to watch the
 * filters write it.
 *
 * Retention is 24h, the same window as the TMM metrics, so a log line and a
 * counter spike can always be put side by side.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ExternalLink, Layers, Search, Terminal, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { PageHeader } from '@/components/layout/PageHeader';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDebounce } from '@/hooks/useDebounce';
import { groupEntries, stripSyslogHeader } from '@/lib/log-grouping';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useLogFilters, useLogSearch } from '@/hooks/useLogs';
import { useSelectedCluster } from '@/hooks/useSelectedCluster';
import { useTmmscopeStatus } from '@/hooks/useTmmscope';
import { useAllClusters } from '@/hooks/useK8s';
import { DEBOUNCE_MS } from '@/lib/constants';

/** Any value means "no filter". Select cannot hold an empty string as a value. */
const ANY = '__any__';

const RANGES = [
  { value: '15', label: 'Last 15 minutes' },
  { value: '60', label: 'Last hour' },
  { value: '360', label: 'Last 6 hours' },
  { value: '1440', label: 'Last 24 hours' },
] as const;

/** Severity colouring. F5's numeric syslog levels are mapped to these names by
 *  the collector, so this is the whole vocabulary. */
function levelVariant(level: string): 'destructive' | 'warning' | 'secondary' | 'outline' {
  switch (level) {
    case 'emergency':
    case 'alert':
    case 'critical':
    case 'error':
      return 'destructive';
    case 'warning':
      return 'warning';
    case 'notice':
    case 'info':
      return 'secondary';
    default:
      return 'outline';
  }
}

function formatTime(ns: number): string {
  const d = new Date(ns / 1e6);
  return d.toLocaleTimeString(undefined, { hour12: false }) + '.' +
    String(d.getMilliseconds()).padStart(3, '0');
}

export default function Logs() {
  const { data: filters, isLoading: filtersLoading } = useLogFilters();
  const { data: status } = useTmmscopeStatus();
  const { data: clustersResponse } = useAllClusters();
  const [selectedClusterId] = useSelectedCluster();

  const [cluster, setCluster] = useState<string>(ANY);
  const [namespace, setNamespace] = useState<string>(ANY);
  const [container, setContainer] = useState<string>(ANY);
  const [level, setLevel] = useState<string>(ANY);
  const [minutes, setMinutes] = useState<string>('60');
  const [search, setSearch] = useState('');
  const [logql, setLogql] = useState('');
  const [showLogql, setShowLogql] = useState(false);
  // Collapsing is the default: a 500-line page is typically ~100 distinct
  // events, and the repeats are what you scroll past to find anything. The
  // choice is remembered because it is a reading preference, not a filter.
  const [collapse, setCollapse] = useState<boolean>(
    () => localStorage.getItem(STORAGE_KEYS.LOGS_COLLAPSE) !== 'off',
  );
  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS.LOGS_COLLAPSE, collapse ? 'on' : 'off');
  }, [collapse]);

  const debouncedSearch = useDebounce(search, DEBOUNCE_MS.SEARCH);

  const debouncedLogql = useDebounce(logql, DEBOUNCE_MS.SEARCH);

  // Arrive on this page already scoped to the cluster you were looking at.
  // The label Loki knows is the cluster's name, which is what the collector
  // stamps on every line.
  const clusters = useMemo(
    () => clustersResponse?.clusters ?? [],
    [clustersResponse?.clusters],
  );
  useEffect(() => {
    if (cluster !== ANY || !selectedClusterId || !filters?.clusters?.length) return;
    const name = clusters.find((c) => c.id === selectedClusterId)?.name;
    if (name && filters.clusters.includes(name)) setCluster(name);
  }, [selectedClusterId, clusters, filters?.clusters, cluster]);

  const params = useMemo(
    () => ({
      cluster: cluster === ANY ? undefined : cluster,
      namespace: namespace === ANY ? undefined : namespace,
      container: container === ANY ? undefined : container,
      level: level === ANY ? undefined : level,
      search: debouncedSearch || undefined,
      logql: showLogql && debouncedLogql ? debouncedLogql : undefined,
      minutes: Number(minutes),
      limit: 500,
    }),
    [cluster, namespace, container, level, debouncedSearch, debouncedLogql, showLogql, minutes],
  );

  const { data, isFetching, refetch } = useLogSearch(params, !!filters?.available);
  // One row per distinct event when collapsing, one per line otherwise. The
  // grouping runs over the page that was fetched, so the count is honestly
  // "in this window" rather than a claim about all of history — and it must
  // sit above the early return below, or the hook order changes with the
  // filter response.
  const rows = useMemo(() => {
    const entries = data?.entries ?? [];
    if (!collapse) {
      return entries.map((e) => ({
        latest: e,
        count: 1,
        firstTimestamp: e.timestamp,
        podCount: 1,
      }));
    }
    return groupEntries(entries);
  }, [data?.entries, collapse]);

  const activeFilters =
    [cluster, namespace, container, level].filter((v) => v !== ANY).length +
    (search ? 1 : 0);

  const clearAll = () => {
    setCluster(ANY);
    setNamespace(ANY);
    setContainer(ANY);
    setLevel(ANY);
    setSearch('');
    setLogql('');
  };

  const grafanaExplore = status?.grafana_url
    ? `${status.grafana_url.replace(/\/$/, '')}/explore?left=${encodeURIComponent(
        JSON.stringify({
          datasource: 'tmm-logs',
          queries: [{ refId: 'A', expr: data?.query || '{cluster=~".+"}' }],
          range: { from: `now-${minutes}m`, to: 'now' },
        }),
      )}`
    : null;

  if (!filtersLoading && filters && !filters.available) {
    return (
      <div className="space-y-4">
        <PageHeader title="Logs" subtitle="Everything your clusters have said, for the last 24 hours" />
        <SectionCard title="The log store is not running">
          <p className="text-sm text-muted-foreground">
            {filters.detail ??
              'Logs are collected by the telemetry stack, which starts with bnkscope.'}
          </p>
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Logs"
        subtitle="Everything your clusters have said, for the last 24 hours"
        onRefresh={() => void refetch()}
        isRefreshing={isFetching}
        actions={
          grafanaExplore ? (
            <Button size="sm" variant="outline" asChild>
              {/* Carries the current query across, so Explore opens on what
                  you are already looking at rather than an empty page. */}
              <a href={grafanaExplore} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-2 h-4 w-4" />
                Open in Grafana
              </a>
            </Button>
          ) : undefined
        }
      />

      <SectionCard title="Filter">
        <div className="flex flex-wrap items-center gap-2 md:gap-3">
          <Select value={cluster} onValueChange={setCluster}>
            <SelectTrigger className="h-9 w-[46vw] max-w-[220px] sm:w-[220px]">
              <SelectValue placeholder="Cluster" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>All clusters</SelectItem>
              {(filters?.clusters ?? []).map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={namespace} onValueChange={setNamespace}>
            <SelectTrigger className="h-9 w-[46vw] max-w-[200px] sm:w-[200px]">
              <SelectValue placeholder="Namespace" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>All namespaces</SelectItem>
              {(filters?.namespaces ?? []).map((n) => (
                <SelectItem key={n} value={n}>{n}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={container} onValueChange={setContainer}>
            <SelectTrigger className="h-9 w-[46vw] max-w-[200px] sm:w-[200px]">
              <SelectValue placeholder="Container" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>All containers</SelectItem>
              {(filters?.containers ?? []).map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={level} onValueChange={setLevel}>
            <SelectTrigger className="h-9 w-[36vw] max-w-[150px] sm:w-[150px]">
              <SelectValue placeholder="Level" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>Any level</SelectItem>
              {(filters?.levels ?? []).map((l) => (
                <SelectItem key={l} value={l}>{l}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={minutes} onValueChange={setMinutes}>
            <SelectTrigger className="h-9 w-[40vw] max-w-[170px] sm:w-[170px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGES.map((r) => (
                <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="relative w-full min-w-0 flex-1 sm:w-auto sm:min-w-[220px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 pl-9"
              placeholder="Contains…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {activeFilters > 0 && (
            <Button variant="ghost" size="sm" onClick={clearAll}>
              <X className="mr-1 h-4 w-4" />
              Clear
            </Button>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={() => setShowLogql((v) => !v)}
          >
            <Terminal className="mr-1.5 h-3 w-3" />
            {showLogql ? 'Use the filters' : 'Write LogQL'}
          </Button>

          {/* Collapsing is a reading preference, not a filter — it never
              changes what was fetched, only how many rows it becomes. Said
              with the numbers so the compression is visible rather than
              something you have to trust. */}
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={() => setCollapse((v) => !v)}
            aria-pressed={collapse}
            title={
              collapse
                ? 'Showing one row per distinct event. Click to show every line.'
                : 'Showing every line. Click to collapse repeats.'
            }
          >
            <Layers className="mr-1.5 h-3 w-3" />
            {collapse ? 'Repeats collapsed' : 'Every line'}
          </Button>

          {collapse && data?.entries?.length ? (
            <span className="text-xs text-muted-foreground">
              {rows.length} of {data.entries.length}
            </span>
          ) : null}

          {!showLogql && data?.query && (
            // The filters write this. Showing it is how the query language
            // gets learned without anyone setting out to learn it.
            <code className="truncate rounded bg-muted/40 px-2 py-1 font-mono text-xs text-muted-foreground">
              {data.query}
            </code>
          )}
        </div>

        {showLogql && (
          <div className="mt-3">
            <Input
              className="h-9 font-mono text-sm"
              placeholder={data?.query || '{cluster="scope", container="f5-tmm"} |= "error"'}
              value={logql}
              onChange={(e) => setLogql(e.target.value)}
            />
            <p className="mt-1.5 text-xs text-muted-foreground">
              Overrides the filters entirely. Labels available:{' '}
              <code>cluster</code>, <code>namespace</code>, <code>pod</code>,{' '}
              <code>container</code>, <code>level</code>.
            </p>
          </div>
        )}
      </SectionCard>

      {data && !data.ok && data.detail && (
        <SectionCard title="That query did not parse">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-destructive" />
            <code className="font-mono text-xs text-muted-foreground">{data.detail}</code>
          </div>
        </SectionCard>
      )}

      <SectionCard
        title={
          data?.count
            ? `${data.count} line${data.count === 1 ? '' : 's'}`
            : 'Lines'
        }
      >
        {rows.length ? (
          <div className="space-y-px font-mono text-xs">
            {rows.map((row, i) => {
              const e = row.latest;
              const prev = i > 0 ? rows[i - 1].latest : null;
              // Print the source once per run rather than on every line.
              // Consecutive lines almost always come from the same container,
              // and repeating "scope / default / f5-tmm-2lsvg / f5-tmm" down
              // the left edge is what was eating the width.
              const newSource =
                !prev ||
                prev.pod !== e.pod ||
                prev.container !== e.container ||
                prev.cluster !== e.cluster;

              return (
                <div key={`${e.timestamp}-${i}`}>
                  {newSource && (
                    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/50 pb-1 text-[11px] text-muted-foreground first:mt-0">
                      {/* Cluster and namespace only when they are not already
                          fixed by a filter — repeating what you just selected
                          is noise, not context. */}
                      {cluster === ANY && e.cluster && (
                        <span className="font-semibold text-foreground/70">{e.cluster}</span>
                      )}
                      {namespace === ANY && e.namespace && <span>{e.namespace}</span>}
                      <span className="text-foreground/70">{e.container}</span>
                      <span className="truncate opacity-70">{e.pod}</span>
                    </div>
                  )}
                  <div className="flex items-baseline gap-2 rounded px-1 py-0.5 hover:bg-muted/40">
                    {/* The newest occurrence's time. For a collapsed group
                        that is what you want first: not when it started, but
                        whether it is still happening. */}
                    <span className="flex-none tabular-nums text-muted-foreground">
                      {formatTime(e.timestamp)}
                    </span>
                    <Badge
                      variant={levelVariant(e.level)}
                      className="h-4 flex-none px-1 text-[10px] leading-none"
                    >
                      {e.level}
                    </Badge>
                    {row.count > 1 && (
                      <Badge
                        variant="outline"
                        className="h-4 flex-none px-1 text-[10px] leading-none tabular-nums"
                        title={
                          `${row.count} occurrences, first at ${formatTime(row.firstTimestamp)}` +
                          (row.podCount > 1 ? `, across ${row.podCount} pods` : '')
                        }
                      >
                        ×{row.count}
                      </Badge>
                    )}
                    {/* The message, and all the width that is left. The line
                        shown is the newest real one — the normalised shape is
                        a grouping key, never something to read. */}
                    <span
                      className="min-w-0 flex-1 whitespace-pre-wrap break-words text-foreground"
                      title={e.line}
                    >
                      {stripSyslogHeader(e.line)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={Search}
            title={isFetching ? 'Searching…' : 'Nothing matched'}
            description={
              isFetching
                ? 'Querying the log store.'
                : 'Widen the time range, or clear a filter. Only the last 24 hours are kept.'
            }
          />
        )}
      </SectionCard>
    </div>
  );
}
