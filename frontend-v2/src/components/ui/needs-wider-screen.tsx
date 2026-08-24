/**
 * For the views that a phone cannot honestly render.
 *
 * A topology graph, a traffic-flow diagram or a terminal will technically
 * *draw* at 393px. What it will not do is let you read or use it, and a UI that
 * renders something unusable while claiming to work is worse than one that says
 * what it needs — you spend the time discovering it yourself, usually while
 * something is on fire.
 *
 * So this states the requirement, offers the thing you can actually do here
 * instead, and then gets out of the way: **"Show anyway" is always available.**
 * Being told what a tool cannot do is help; being prevented is not, and the
 * person holding the phone is the one who knows whether they need it.
 *
 * The choice sticks for the session, so an operator who has decided they want
 * the graph on their phone is not asked again on every navigation.
 */
import { useState } from 'react';
import { Monitor } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useIsCompact, useIsHandheld } from '@/hooks/useMediaQuery';

/** Session-scoped overrides, keyed by `id`. Deliberately not persisted: a
 *  decision made on a phone should not follow you to a desktop. */
const overridden = new Set<string>();

interface NeedsWiderScreenProps {
  /** Stable key for the "show anyway" override. */
  id: string;
  /** What this view is, in the operator's words: "The topology graph". */
  title: string;
  /** Why a narrow screen cannot do it justice. One sentence. */
  reason: string;
  /** What they can usefully do here instead. Optional but strongly preferred. */
  instead?: React.ReactNode;
  /**
   * `handheld` (< 768px) is the default. `compact` (< 1024px) is for the very
   * few views that genuinely need a desktop — a full traffic-flow diagram.
   */
  threshold?: 'handheld' | 'compact';
  children: React.ReactNode;
}

export function NeedsWiderScreen({
  id,
  title,
  reason,
  instead,
  threshold = 'handheld',
  children,
}: NeedsWiderScreenProps) {
  const handheld = useIsHandheld();
  const compact = useIsCompact();
  const tooNarrow = threshold === 'compact' ? compact : handheld;

  const [show, setShow] = useState(() => overridden.has(id));

  if (!tooNarrow || show) return <>{children}</>;

  return (
    <div className="flex min-h-[16rem] items-center justify-center p-6">
      <div className="max-w-sm text-center">
        <Monitor className="mx-auto mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <p className="font-medium text-foreground">{title} needs a wider screen</p>
        <p className="mt-1 text-sm text-muted-foreground">{reason}</p>

        {instead && <div className="mt-4 text-sm text-muted-foreground">{instead}</div>}

        <Button
          variant="outline"
          size="sm"
          className="mt-5"
          onClick={() => {
            overridden.add(id);
            setShow(true);
          }}
        >
          Show anyway
        </Button>
      </div>
    </div>
  );
}

