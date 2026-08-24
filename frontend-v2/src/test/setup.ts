/**
 * Test setup file for Vitest
 *
 * Configures:
 * - @testing-library/jest-dom matchers
 * - MSW server for API mocking
 * - Global browser API mocks (matchMedia, ResizeObserver, IntersectionObserver)
 */
import '@testing-library/jest-dom';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { cleanup } from '@testing-library/react';
import { server } from './mocks/server';

// Start MSW server before all tests
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }));

// Reset handlers after each test (so individual tests can override)
afterEach(() => {
  cleanup();
  server.resetHandlers();
  // A test that widened or narrowed the viewport must not leak it into the
  // next one — layout bugs that only appear in file order are miserable.
  resetViewport();
});

// Clean up after all tests
afterAll(() => server.close());

// ============================================================================
// Global Browser API Mocks
// ============================================================================

// Mock window.matchMedia (used by Radix UI, Tailwind, dark mode detection, and
// the responsive layout hooks in hooks/useMediaQuery.ts).
//
// It answers width queries against a settable viewport rather than returning
// false for everything. Returning false made every `(min-width: …)` query fail,
// which reads as "narrower than every breakpoint" — so the whole suite would
// silently render the handheld layout. The default is a desktop width, so a
// test that says nothing about the viewport gets the desktop tree; a test that
// cares calls `setViewportWidth()` from '@/test/viewport'.
import { getViewportHeight, getViewportWidth, resetViewport, subscribeToViewport } from './viewport';

function parseMinWidth(query: string): number | null {
  const m = /\(min-width:\s*(\d+)px\)/.exec(query);
  return m ? Number(m[1]) : null;
}

function parseMaxWidth(query: string): number | null {
  const m = /\(max-width:\s*(\d+)px\)/.exec(query);
  return m ? Number(m[1]) : null;
}

function parseMaxHeight(query: string): number | null {
  const m = /\(max-height:\s*(\d+)px\)/.exec(query);
  return m ? Number(m[1]) : null;
}

function queryMatches(query: string): boolean {
  const maxH = parseMaxHeight(query);
  if (maxH !== null) return getViewportHeight() <= maxH;
  const min = parseMinWidth(query);
  if (min !== null) return getViewportWidth() >= min;
  const max = parseMaxWidth(query);
  if (max !== null) return getViewportWidth() <= max;
  // Anything else — prefers-color-scheme, pointer: coarse — stays false, which
  // is the light-theme, mouse-pointer default the suite assumes.
  return false;
}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => {
    const listeners = new Set<(e: MediaQueryListEvent) => void>();
    const list = {
      get matches() {
        return queryMatches(query);
      },
      media: query,
      onchange: null,
      addListener: (fn: (e: MediaQueryListEvent) => void) => listeners.add(fn),
      removeListener: (fn: (e: MediaQueryListEvent) => void) => listeners.delete(fn),
      addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.delete(fn),
      dispatchEvent: () => false,
    };
    // Re-notify on viewport change, so a component subscribed through the hook
    // re-renders exactly as it would in a browser.
    subscribeToViewport(() => {
      const event = { matches: queryMatches(query), media: query } as MediaQueryListEvent;
      listeners.forEach((fn) => fn(event));
    });
    return list;
  },
});

// Mock ResizeObserver (used by Radix UI popovers, dialogs)
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

// Mock IntersectionObserver (used by lazy loading, infinite scroll)
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver;

// Mock WebSocket. jsdom implements WebSocket but actually attempts to dial the URL,
// and any component constructing `new WebSocket(...)` (e.g. SystemUpgrade) leaks an
// async connection error after the test unmounts — surfacing as a worker-killing
// AggregateError from MSW's MockHttpSocket. A no-op stub keeps the constructor
// signature intact without doing any real I/O.
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;
  readyState = MockWebSocket.CLOSED;
  url = '';
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  constructor(url: string | URL) { this.url = String(url); }
  send() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() { return false; }
}
window.WebSocket = MockWebSocket as unknown as typeof WebSocket;

// Mock scrollIntoView (used by Radix UI Select to scroll to selected item;
// not implemented in jsdom and throws "candidate?.scrollIntoView is not a function")
window.HTMLElement.prototype.scrollIntoView = () => {};

// Mock localStorage / sessionStorage. Node 25 + jsdom combo leaves these
// exposed but with no working Storage prototype, so `getItem` / `setItem`
// fail as "not a function". Provide a minimal in-memory Storage shim.
function makeStorage(): Storage {
  let store: Record<string, string> = {};
  return {
    get length() { return Object.keys(store).length; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
}
Object.defineProperty(window, 'localStorage', { value: makeStorage(), writable: true, configurable: true });
Object.defineProperty(window, 'sessionStorage', { value: makeStorage(), writable: true, configurable: true });

// Guard EventTarget.dispatchEvent against late, post-teardown events. Radix UI's
// focus-scope schedules a `setTimeout(0)` on unmount that does
// `container.dispatchEvent(new CustomEvent(...))` (react-focus-scope index.mjs:90-92).
// When that timer fires after a test has finished and jsdom is tearing the realm
// down, the CustomEvent is no longer a valid Event in the dying realm and
// dispatchEvent throws "parameter 1 is not of type 'Event'" — a worker-killing
// unhandled error that fails the whole run even though every test passed. Drop any
// dispatch whose argument isn't a real Event; legitimate dispatches always pass one.
const realDispatchEvent = EventTarget.prototype.dispatchEvent;
EventTarget.prototype.dispatchEvent = function (event: Event) {
  if (!(event instanceof Event)) return false;
  return realDispatchEvent.call(this, event);
};

// Suppress console.error/warn noise in tests (optional, but keeps output clean)
// Uncomment if you want silent tests:
// const originalError = console.error;
// console.error = (...args: unknown[]) => {
//   if (typeof args[0] === 'string' && args[0].includes('Warning:')) return;
//   originalError.call(console, ...args);
// };
