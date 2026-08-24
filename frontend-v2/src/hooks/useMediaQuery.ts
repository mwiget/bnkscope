/**
 * Viewport queries, for the handful of places where responsive behaviour
 * cannot be expressed in CSS.
 *
 * Prefer Tailwind's `md:` / `lg:` variants wherever the difference is only
 * visual — they cost nothing at runtime and cannot desynchronise from the
 * breakpoints below. This hook is for the cases where the *component tree*
 * differs: a sidebar that is a column on a desktop and a drawer on a tablet is
 * not one element with different classes, it is two different components, and
 * rendering both and hiding one would mount two copies of everything inside.
 *
 * The breakpoints match `tailwind.config.js` exactly. They are duplicated here
 * because JS cannot read Tailwind's config at runtime; a change in one has to
 * be made in the other, which is what the test in
 * `__tests__/useMediaQuery.test.ts` checks.
 */
import { useEffect, useState } from 'react';

/** Tailwind's default scale, which this project has not overridden. */
export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const;

export type Breakpoint = keyof typeof BREAKPOINTS;

/**
 * True while the viewport matches `query`.
 *
 * Starts from the real value rather than `false`, so a desktop render does not
 * flash the mobile layout on mount. In an environment with no `matchMedia`
 * (jsdom without a polyfill, SSR) it reports false and never subscribes.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);

    // Re-read on subscribe: the query can have changed since the initial state
    // was computed, and Safari < 14 has no addEventListener on MediaQueryList.
    setMatches(list.matches);
    if (list.addEventListener) {
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    }
    list.addListener(onChange);
    return () => list.removeListener(onChange);
  }, [query]);

  return matches;
}

/**
 * Height below which a viewport is a phone lying on its side.
 *
 * Width alone gets this wrong. An iPhone in landscape is 852×393 — *wider*
 * than the `md` breakpoint, so a width-only test calls it a desktop and hands
 * it a full-height 240px navigation column on a screen 393px tall. The short
 * dimension is what actually ran out.
 *
 * 500px sits below every tablet in landscape (iPad is 768 tall) and above
 * every phone in landscape (the tallest are ~440).
 */
const SHORT_VIEWPORT = 500;

/** True at or above the named breakpoint — mirrors Tailwind's `md:` etc. */
export function useBreakpoint(breakpoint: Breakpoint): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS[breakpoint]}px)`);
}

/**
 * Below `lg` (1024px): the three-pane explorer does not fit.
 *
 * 1024 is where it stops being a judgement call and starts being arithmetic —
 * app sidebar 240 + explorer sidebar 224 + a usable 320 of content + detail
 * panel 384 is 1168px, so even a landscape iPad is 144px short.
 *
 * A short viewport counts too: a landscape phone is wide enough for the panes
 * and has no vertical room to show anything in them.
 */
export function useIsCompact(): boolean {
  const narrow = !useBreakpoint('lg');
  const short = useMediaQuery(`(max-height: ${SHORT_VIEWPORT}px)`);
  return narrow || short;
}

/**
 * Phone territory: **narrow or short**. The app sidebar becomes a drawer and
 * the dense views say what they need instead of rendering unusably.
 *
 * The `or` is the point — see SHORT_VIEWPORT. Rotating a phone to landscape
 * makes it wider without making it roomier, and a nav column that eats 28% of
 * an 852px width and all 393px of its height is worse in landscape, not better.
 */
export function useIsHandheld(): boolean {
  const narrow = !useBreakpoint('md');
  const short = useMediaQuery(`(max-height: ${SHORT_VIEWPORT}px)`);
  return narrow || short;
}

/**
 * A viewport with little vertical room — a phone in landscape, or a short
 * desktop window.
 *
 * Worth its own hook because the scarce resource is different. On a narrow
 * screen you rearrange columns; on a *short* one you have to give height back,
 * and every row of chrome is a row the content does not get. An iPhone in
 * landscape is 393px tall, and the page header alone was taking 240px of it.
 */
export function useIsShort(): boolean {
  return useMediaQuery(`(max-height: ${SHORT_VIEWPORT}px)`);
}

