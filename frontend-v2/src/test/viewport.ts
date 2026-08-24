/**
 * Viewport control for tests.
 *
 * The `matchMedia` stub in `setup.ts` answers width queries against the value
 * here, so a test can put the app on an iPhone and get the handheld tree — the
 * same one a real browser would build.
 *
 *     setViewportWidth(VIEWPORTS.iphone);
 *     render(<KubernetesV2 />);
 *
 * The default is a desktop width, so tests that say nothing get the layout
 * they were written against. `resetViewport()` runs automatically after each
 * test (see setup.ts).
 */

/**
 * Real device sizes, so a failure names something you can picture.
 *
 * Height matters as much as width: an iPhone in landscape is 852×393 — wider
 * than `md`, and 393px tall. A width-only fixture would call that a desktop,
 * which is exactly the bug this pair of numbers exists to catch.
 */
export const VIEWPORTS = {
  iphone: { width: 393, height: 852 }, // iPhone 15
  iphoneLandscape: { width: 852, height: 393 },
  ipad: { width: 768, height: 1024 },
  ipadLandscape: { width: 1024, height: 768 },
  laptop: { width: 1440, height: 900 },
  desktop: { width: 1920, height: 1080 },
} as const;

export type Viewport = { width: number; height: number };

const DEFAULT: Viewport = VIEWPORTS.laptop;

let current: Viewport = DEFAULT;
const subscribers = new Set<() => void>();

export function getViewportWidth(): number {
  return current.width;
}

export function getViewportHeight(): number {
  return current.height;
}

/**
 * Point the matchMedia stub at a new size and notify subscribers.
 *
 * Accepts a `VIEWPORTS` entry or a bare width (which keeps a desktop height),
 * so a test that only cares about width stays short.
 */
export function setViewportWidth(next: Viewport | number): void {
  current = typeof next === 'number' ? { width: next, height: DEFAULT.height } : next;
  // Keep window.innerWidth/innerHeight honest — some code reads them directly.
  Object.defineProperty(window, 'innerWidth', {
    writable: true, configurable: true, value: current.width,
  });
  Object.defineProperty(window, 'innerHeight', {
    writable: true, configurable: true, value: current.height,
  });
  subscribers.forEach((fn) => fn());
}

/** Reads better than `setViewportWidth` when passing a device. */
export const setViewport = setViewportWidth;

export function resetViewport(): void {
  setViewportWidth(DEFAULT);
}

/** Used by the matchMedia stub; not part of the test-facing API. */
export function subscribeToViewport(fn: () => void): () => void {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}
