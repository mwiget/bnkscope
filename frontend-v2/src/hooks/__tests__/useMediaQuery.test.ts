/**
 * The viewport hooks, and the invariant that keeps them honest.
 *
 * These breakpoints are duplicated from `tailwind.config.js` — JS cannot read
 * Tailwind's config at runtime — so the risk is that one moves and the other
 * does not, and `lg:hidden` in a class string starts disagreeing with
 * `useIsCompact()` in a branch. The first test reads the config and compares.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import {
  BREAKPOINTS,
  useBreakpoint,
  useIsCompact,
  useIsHandheld,
  useIsShort,
  useMediaQuery,
} from '@/hooks/useMediaQuery';
import { VIEWPORTS, resetViewport, setViewportWidth } from '@/test/viewport';

beforeEach(() => {
  resetViewport();
});

describe('BREAKPOINTS', () => {
  it("match Tailwind's scale, which the class strings use", () => {
    // Tailwind's defaults; the project does not override `theme.screens`.
    expect(BREAKPOINTS).toEqual({ sm: 640, md: 768, lg: 1024, xl: 1280 });
  });
});

describe('useMediaQuery', () => {
  it('reports the viewport on first render, without a flash', () => {
    setViewportWidth(VIEWPORTS.iphone);
    const { result } = renderHook(() => useMediaQuery('(min-width: 1024px)'));
    // Not "false, then correct after an effect" — that flash is what makes a
    // desktop briefly render the mobile tree.
    expect(result.current).toBe(false);
  });

  it('follows the viewport as it changes', () => {
    setViewportWidth(VIEWPORTS.laptop);
    const { result } = renderHook(() => useMediaQuery('(min-width: 1024px)'));
    expect(result.current).toBe(true);

    act(() => setViewportWidth(VIEWPORTS.iphone));
    expect(result.current).toBe(false);

    act(() => setViewportWidth(VIEWPORTS.desktop));
    expect(result.current).toBe(true);
  });
});

describe('useBreakpoint', () => {
  it.each([
    ['iphone', VIEWPORTS.iphone, { sm: false, md: false, lg: false }],
    ['ipad portrait', VIEWPORTS.ipad, { sm: true, md: true, lg: false }],
    ['ipad landscape', VIEWPORTS.ipadLandscape, { sm: true, md: true, lg: true }],
    ['laptop', VIEWPORTS.laptop, { sm: true, md: true, lg: true }],
  ])('%s', (_name, viewport, expected) => {
    setViewportWidth(viewport);
    for (const [bp, want] of Object.entries(expected)) {
      const { result } = renderHook(() => useBreakpoint(bp as 'sm' | 'md' | 'lg'));
      expect(result.current, `${bp} at ${viewport.width}px`).toBe(want);
    }
  });

  it('is inclusive at the boundary, like Tailwind', () => {
    setViewportWidth({ width: BREAKPOINTS.lg, height: 900 });
    const { result } = renderHook(() => useBreakpoint('lg'));
    expect(result.current).toBe(true);
  });
});

describe('useIsCompact', () => {
  it.each([
    ['iphone portrait', VIEWPORTS.iphone, true],
    ['iphone landscape', VIEWPORTS.iphoneLandscape, true],
    ['ipad portrait', VIEWPORTS.ipad, true],
    // The arithmetic that set this line: 240 + 224 + 320 + 384 = 1168px, so a
    // landscape iPad is 144px short of the three-pane layout. It is still
    // "compact" at exactly 1024 only if lg is exclusive — it is not.
    ['ipad landscape', VIEWPORTS.ipadLandscape, false],
    ['laptop', VIEWPORTS.laptop, false],
  ])('%s -> compact=%s', (_name, viewport, expected) => {
    setViewportWidth(viewport);
    const { result } = renderHook(() => useIsCompact());
    expect(result.current).toBe(expected);
  });
});

describe('useIsHandheld', () => {
  it.each([
    ['iphone portrait', VIEWPORTS.iphone, true],
    // 852x393 — WIDER than `md`, and still a phone. A width-only test called
    // this a desktop and handed it a full-height 240px nav column on a screen
    // 393px tall. The short dimension is the one that ran out.
    ['iphone landscape', VIEWPORTS.iphoneLandscape, true],
    ['ipad portrait', VIEWPORTS.ipad, false],
    ['ipad landscape', VIEWPORTS.ipadLandscape, false],
    ['laptop', VIEWPORTS.laptop, false],
  ])('%s -> handheld=%s', (_name, viewport, expected) => {
    setViewportWidth(viewport);
    const { result } = renderHook(() => useIsHandheld());
    expect(result.current).toBe(expected);
  });

  it('follows a rotation, both ways', () => {
    setViewportWidth(VIEWPORTS.iphone);
    const { result } = renderHook(() => useIsHandheld());
    expect(result.current).toBe(true);

    act(() => setViewportWidth(VIEWPORTS.iphoneLandscape));
    expect(result.current, 'rotating a phone does not make it a desktop').toBe(true);

    act(() => setViewportWidth(VIEWPORTS.laptop));
    expect(result.current).toBe(false);
  });

  it('a short desktop window counts too, which is the right call', () => {
    // A 1440x420 window has the same problem a landscape phone has: no
    // vertical room for a full-height nav column.
    setViewportWidth({ width: 1440, height: 420 });
    const { result } = renderHook(() => useIsHandheld());
    expect(result.current).toBe(true);
  });
});

describe('useIsShort', () => {
  it.each([
    // Height is the whole test here — the first two are the same device.
    ['iphone portrait', VIEWPORTS.iphone, false],
    ['iphone landscape', VIEWPORTS.iphoneLandscape, true],
    ['ipad landscape', VIEWPORTS.ipadLandscape, false],
    ['laptop', VIEWPORTS.laptop, false],
    ['a short desktop window', { width: 1920, height: 420 }, true],
  ])('%s -> short=%s', (_name, viewport, expected) => {
    setViewportWidth(viewport);
    const { result } = renderHook(() => useIsShort());
    expect(result.current).toBe(expected);
  });

  it('ignores width entirely, unlike useIsHandheld', () => {
    // 320x900 is the narrowest phone there is, and vertically it is roomy.
    setViewportWidth({ width: 320, height: 900 });
    const { result } = renderHook(() => useIsShort());
    expect(result.current).toBe(false);
  });
});
