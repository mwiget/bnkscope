/**
 * The bnkscope mark, inlined so the beam can sweep.
 *
 * An SVG loaded through `<img>` is style-isolated — CSS in the page cannot
 * reach inside it — and the sweep is a CSS animation on the `.beam` path. So
 * the generated file is imported as raw text (`?raw`) and injected. It is a
 * build artifact from `scripts/bnkscope-icon/build.py`, not user content;
 * nothing untrusted goes through here.
 *
 * Two builds, picked by size: the full mark has code rain and blur filters
 * that turn to mud below 32px, so anything smaller gets `-small`, which drops
 * both and thickens the strokes.
 *
 * Never hand-edit the .svg files — change build.py and re-run.
 */
import { useMemo } from 'react';

import markFull from '@/assets/icons/bnkscope.svg?raw';
import markSmall from '@/assets/icons/bnkscope-small.svg?raw';
import { cn } from '@/lib/utils';

interface BnkscopeMarkProps {
  /** Rendered edge length in px. The app-bar slot is 34. */
  size?: number;
  /** Run the trace sweep once on mount. */
  animate?: boolean;
  className?: string;
  title?: string;
}

// Below this the rain and the blurs stop reading as anything.
const SMALL_BUILD_THRESHOLD = 32;

export function BnkscopeMark({
  size = 34,
  animate = false,
  className,
  title = 'bnkscope',
}: BnkscopeMarkProps) {
  const svg = useMemo(() => {
    const source = size < SMALL_BUILD_THRESHOLD ? markSmall : markFull;
    // Let the box be driven by the wrapper rather than the file's own
    // width/height, so one generated asset serves every call site.
    //
    // The asset already carries role="img", an aria-label and a <title>, so
    // the wrapper stays presentational — repeating them here nests one img
    // role inside another and doubles the accessible name.
    return source
      .replace(/<svg([^>]*?)\swidth="[^"]*"/, '<svg$1')
      .replace(/<svg([^>]*?)\sheight="[^"]*"/, '<svg$1')
      .replace('<svg', '<svg width="100%" height="100%" focusable="false"')
      .replace(/aria-label="[^"]*"/, `aria-label="${title}"`)
      .replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`);
  }, [size, title]);

  return (
    <span
      style={{ width: size, height: size }}
      className={cn('inline-block flex-none', animate && 'bnkscope-mark--sweep', className)}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
