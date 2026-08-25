import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Collecting state
//
// For a read that takes long enough that a bare skeleton reads as "nothing is
// happening". The DPF and NICo tabs are both one unified request against a
// cluster that may be several hops away — 25s is normal over a VPN, and the
// grey boxes alone gave no reason to keep waiting.
//
// Deliberately NOT a progress bar. One request means there is no honest
// completion fraction to show, and a bar that fills on a timer claims
// knowledge we do not have. What is real is the elapsed clock and the list of
// what the request covers, so both are what we show.
// ---------------------------------------------------------------------------

export interface CollectingStateProps {
  /** What is being read, as a heading: "Collecting NICo inventory". */
  title: string;
  /** One line on why this is a single slow read rather than many fast ones. */
  detail?: string;
  /** What the request covers. Listed, not sequenced — see above. */
  steps?: string[];
  /**
   * Seconds after which `slowNote` appears. Past this the operator is
   * wondering whether it is stuck, which is the moment to explain.
   */
  slowAfterSeconds?: number;
  slowNote?: string;
  className?: string;
}

export function CollectingState({
  title,
  detail,
  steps,
  slowAfterSeconds = 10,
  slowNote,
  className,
}: CollectingStateProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const tick = setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, []);

  return (
    <div
      className={cn('rounded-lg border border-border bg-card p-5', className)}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex items-start gap-3">
        <Loader2 className="mt-0.5 h-5 w-5 shrink-0 motion-safe:animate-spin text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-4">
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            {/* tabular-nums so the width does not jitter as it counts */}
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {elapsed}s
            </span>
          </div>

          {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}

          {steps && steps.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {steps.map((step) => (
                <li key={step} className="flex items-start gap-2 text-xs text-muted-foreground">
                  <span
                    className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50 motion-safe:animate-pulse"
                    aria-hidden="true"
                  />
                  <span className="min-w-0">{step}</span>
                </li>
              ))}
            </ul>
          )}

          {slowNote && elapsed >= slowAfterSeconds && (
            <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground/80">
              {slowNote}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
