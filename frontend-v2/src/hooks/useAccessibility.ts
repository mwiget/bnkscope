import { useEffect, useState, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { NAV_SHORTCUTS } from '@/hooks/useKeyboardShortcuts';

// ---------------------------------------------------------------------------
// useReducedMotion — programmatic check for prefers-reduced-motion
// ---------------------------------------------------------------------------

/**
 * Returns `true` when the user has `prefers-reduced-motion: reduce` set.
 *
 * CSS utilities like `motion-safe:` handle most cases, but JS-driven
 * animations (e.g., scroll-into-view, requestAnimationFrame loops) need
 * a runtime boolean. This hook keeps it reactive — if the user toggles the
 * OS preference, the value updates immediately.
 *
 * @example
 * const reduced = useReducedMotion();
 * scrollTo({ behavior: reduced ? 'auto' : 'smooth' });
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return reduced;
}

// ---------------------------------------------------------------------------
// useRouteAnnouncer — announce page title changes for screen readers
// ---------------------------------------------------------------------------

/**
 * Title map — route path to the name a screen reader announces.
 *
 * Derived from NAV_SHORTCUTS rather than written out again, because the
 * hand-maintained copy drifted badly: it announced nine routes the router had
 * already dropped (Projects, Modules, Blueprints, Helm, Fleet, Operators,
 * Tasks, Auth Templates, Workflows) and named the surviving ones differently
 * from the sidebar a sighted user reads. Sharing one source means a new page
 * is announced by the same name it is navigated by.
 */
const ROUTE_TITLES: Record<string, string> = Object.fromEntries(
  NAV_SHORTCUTS.map(({ path, label }) => [path, label]),
);

/**
 * On every route change, announces the new page title via an `aria-live`
 * region so screen readers inform the user they've navigated.
 *
 * The live region is injected into the DOM once and persists for the
 * lifetime of the app.
 */
export function useRouteAnnouncer(): void {
  const location = useLocation();
  const regionRef = useRef<HTMLDivElement | null>(null);

  // Create the live region once
  useEffect(() => {
    if (regionRef.current) return;
    const div = document.createElement('div');
    div.setAttribute('role', 'status');
    div.setAttribute('aria-live', 'polite');
    div.setAttribute('aria-atomic', 'true');
    div.className = 'sr-only';
    div.id = 'route-announcer';
    document.body.appendChild(div);
    regionRef.current = div;
    return () => {
      div.remove();
      regionRef.current = null;
    };
  }, []);

  // Announce on route change
  useEffect(() => {
    if (!regionRef.current) return;

    const path = location.pathname;
    // The one nested route that is not its own nav entry.
    const title =
      ROUTE_TITLES[path] ??
      (path === '/observability/ai-gateway/logs' ? 'AI Gateway Logs' : 'Page');

    // Small delay so the DOM update + aria announcement don't collide
    const timer = setTimeout(() => {
      if (regionRef.current) {
        regionRef.current.textContent = `Navigated to ${title}`;
      }
    }, 100);

    return () => clearTimeout(timer);
  }, [location.pathname]);
}

// ---------------------------------------------------------------------------
// useScrollToTop — scroll main content area to top on route change
// ---------------------------------------------------------------------------

/**
 * Scrolls the `#main-content` element to the top whenever the route changes.
 * Respects reduced-motion preference.
 */
export function useScrollToTop(): void {
  const location = useLocation();
  const reduced = useReducedMotion();

  useEffect(() => {
    const main = document.getElementById('main-content');
    if (main) {
      main.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
    }
  }, [location.pathname, reduced]);
}
