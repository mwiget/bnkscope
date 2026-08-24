/**
 * bnkscope's own CPU, memory and uptime.
 *
 * This used to be a live strip in the app header — a row of numbers ticking
 * every five seconds on every page, which is exactly the ambient clutter Phase
 * 6 set out to remove. The information is still worth having, though: bnkscope
 * runs on the operator's own machine, so "is the tool itself the problem?" is a
 * real question, and this is the page they would ask it on.
 *
 * So it moved rather than went, and it polls only while the System page is
 * open and the tab is visible.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Activity, Cpu, MemoryStick, Timer } from 'lucide-react';

import { systemApi } from '@/lib/api/system';
import { queryKeys } from '@/lib/queryKeys';
import type { ProcessMetrics } from '@/types/system';

/** Stops polling when the tab is hidden — same idiom as the other pollers. */
function useDocumentVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(() =>
    typeof document !== 'undefined' ? !document.hidden : true,
  );
  useEffect(() => {
    const handler = () => setIsVisible(!document.hidden);
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);
  return isVisible;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(0)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

export function BackendProcessCard() {
  const isVisible = useDocumentVisibility();

  const { data } = useQuery<ProcessMetrics>({
    queryKey: queryKeys.system.processMetrics(),
    queryFn: systemApi.getProcessMetrics,
    refetchInterval: isVisible ? 10_000 : false,
    staleTime: 5_000,
  });

  // A self-monitoring card must never be the reason the System page fails to
  // render, so a missing or partial payload renders nothing rather than
  // throwing on a field that is not there.
  if (!data || typeof data.cpu_percent !== 'number') return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-3">
        <Activity className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <div className="font-medium text-foreground">bnkscope backend</div>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          icon={Cpu}
          label={`CPU (of ${data.cpu_count} cores)`}
          value={`${data.cpu_percent.toFixed(1)}%`}
        />
        <Stat icon={MemoryStick} label="Resident memory" value={formatBytes(data.rss_bytes)} />
        <Stat icon={Activity} label="Threads" value={String(data.num_threads)} />
        <Stat icon={Timer} label="Uptime" value={formatUptime(data.uptime_seconds)} />
      </div>
    </div>
  );
}
