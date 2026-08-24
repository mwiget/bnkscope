/**
 * FU-017: lib/api/client — API client config, interceptors, retry logic
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';
import { apiClient } from '../client';

describe('apiClient', () => {
  beforeEach(() => {
    localStorage.clear();
    // Ensure window.location.href is a valid absolute URL for MSW URL resolution
    Object.defineProperty(window, 'location', {
      value: { href: 'http://localhost:3000/' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('has correct default Content-Type header', () => {
    expect(apiClient.defaults.headers['Content-Type']).toBe('application/json');
  });

  it('surfaces a 401 without navigating away', async () => {
    // There is no login page to send anyone to. The interceptor used to set
    // window.location to /login on an UNAUTHORIZED envelope, which in a router
    // with no such route blanked the app instead of showing the error.
    const before = window.location.href;

    server.use(
      http.get('*/api/protected-resource', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'Token expired' } },
          { status: 401 },
        ),
      ),
    );

    await expect(apiClient.get('/api/protected-resource')).rejects.toThrow();
    expect(window.location.href).toBe(before);
  });

  it('sends no Authorization header', async () => {
    let captured: string | null = '';
    server.use(
      http.get('*/api/test-no-auth', ({ request }) => {
        captured = request.headers.get('Authorization');
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiClient.get('/api/test-no-auth');
    expect(captured).toBeNull();
  });

  it('returns data on successful request', async () => {
    server.use(
      http.get('*/api/test-success', () => {
        return HttpResponse.json({ message: 'hello' });
      })
    );

    const response = await apiClient.get('/api/test-success');
    expect(response.data).toEqual({ message: 'hello' });
  });

  // ---------------------------------------------------------------------------
  // Structured-error predicate: these reject immediately, no timer manipulation needed
  // ---------------------------------------------------------------------------

  it('502 with structured ApiError body skips retry immediately', async () => {
    let callCount = 0;
    server.use(
      http.get('*/api/retry-test-skip', () => {
        callCount += 1;
        return HttpResponse.json(
          { error: { code: 'INVALID_INPUT', message: 'bad request' } },
          { status: 502 }
        );
      })
    );

    await expect(apiClient.get('/api/retry-test-skip')).rejects.toThrow();
    // Should have only been called once — no retries fired.
    expect(callCount).toBe(1);
  });

  it('500 with structured ApiError body skips retry immediately', async () => {
    let callCount = 0;
    server.use(
      http.get('*/api/retry-test-500-skip', () => {
        callCount += 1;
        return HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'something went wrong' } },
          { status: 500 }
        );
      })
    );

    await expect(apiClient.get('/api/retry-test-500-skip')).rejects.toThrow();
    // 500 is not in RETRYABLE_STATUS_CODES; predicate path not exercised,
    // but no retry should occur regardless.
    expect(callCount).toBe(1);
  });

  it('network error (no response object) flows through existing retry path', async () => {
    server.use(
      http.get('*/api/retry-test-network', () => {
        return HttpResponse.error();
      })
    );

    // Network errors have no response object; the predicate must not crash or
    // accidentally short-circuit on undefined — the error should propagate cleanly.
    await expect(apiClient.get('/api/retry-test-network')).rejects.toThrow();
  });

  // ---------------------------------------------------------------------------
  // Retry path: use fake timers to advance exponential-backoff delays
  // ---------------------------------------------------------------------------

  describe('retry with backoff', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('502 with no body still retries', async () => {
      let callCount = 0;
      server.use(
        http.get('*/api/retry-test-nodata', () => {
          callCount += 1;
          if (callCount === 1) {
            return new HttpResponse(null, { status: 502 });
          }
          return HttpResponse.json({ ok: true });
        })
      );

      // Drive the exponential-backoff setTimeout so the retry fires.
      const promise = apiClient.get('/api/retry-test-nodata');
      await vi.runAllTimersAsync();
      const response = await promise;

      expect(response.data).toEqual({ ok: true });
      expect(callCount).toBeGreaterThanOrEqual(2);
    });

    it('502 with empty error.code still retries', async () => {
      let callCount = 0;
      server.use(
        http.get('*/api/retry-test-emptycode', () => {
          callCount += 1;
          if (callCount === 1) {
            return HttpResponse.json(
              { error: { code: '', message: 'something broke' } },
              { status: 502 }
            );
          }
          return HttpResponse.json({ ok: true });
        })
      );

      const promise = apiClient.get('/api/retry-test-emptycode');
      await vi.runAllTimersAsync();
      const response = await promise;

      expect(response.data).toEqual({ ok: true });
      expect(callCount).toBeGreaterThanOrEqual(2);
    });
  });
});
