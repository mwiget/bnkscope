/**
 * Error Handling Integration Tests
 *
 * What the app does when something is broken:
 *   1. an unknown route
 *   2. the backend returning 500 on the page's own data
 *   3. the backend not answering at all
 *
 * (2) and (3) used to exercise the Projects page, which went with the pipeline
 * in Phase 1. They now run against the home page, which is the right target:
 * it is the first thing an operator loads, and a tool for diagnosing broken
 * things has no business rendering a blank screen when it is itself broken.
 *
 * ErrorBoundary uses useRouteError() and needs a react-router errorElement
 * context, so it cannot be tested in isolation here. NotFound is standalone.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';
import { render } from '@/test/test-utils';
import { NotFound } from '@/components/ErrorBoundary';
import CommandCenter from '@/pages/CommandCenter';

// ---------------------------------------------------------------------------
// Navigation mock
// ---------------------------------------------------------------------------
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

// ---------------------------------------------------------------------------
// Common setup
// ---------------------------------------------------------------------------
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

// ===========================================================================
// Tests
// ===========================================================================

describe('Error Handling (integration)', () => {
  // -------------------------------------------------------------------------
  // 1. NotFound renders 404 page
  // -------------------------------------------------------------------------
  it('NotFound renders 404 page with correct content and link', () => {
    render(<NotFound />);

    // Large "404" text
    expect(screen.getByText('404')).toBeInTheDocument();

    // Heading
    expect(screen.getByText('Page not found')).toBeInTheDocument();

    // Description
    expect(
      screen.getByText(
        "The page you're looking for doesn't exist or has been moved.",
      ),
    ).toBeInTheDocument();

    // "Back to Dashboard" link pointing to "/"
    const link = screen.getByRole('link', { name: /back to dashboard/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });

  // -------------------------------------------------------------------------
  // 2. A 500 on the page's own data
  // -------------------------------------------------------------------------
  it('offers a retry rather than a blank page when the cluster list 500s', async () => {
    server.use(
      http.get('*/api/k8s/clusters', ({ request }) => {
        const url = new URL(request.url);
        if (url.pathname !== '/api/k8s/clusters') return;
        return HttpResponse.json(
          { error: { code: 'INTERNAL_SERVER_ERROR', message: 'boom' } },
          { status: 500 },
        );
      }),
    );

    render(<CommandCenter />);

    await waitFor(
      () => expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument(),
      { timeout: 5000 },
    );
  });

  // -------------------------------------------------------------------------
  // 3. The backend not answering at all
  // -------------------------------------------------------------------------
  it('surfaces a network failure the same way as a 500', async () => {
    server.use(
      http.get('*/api/k8s/clusters', ({ request }) => {
        const url = new URL(request.url);
        if (url.pathname !== '/api/k8s/clusters') return;
        return HttpResponse.error();
      }),
    );

    render(<CommandCenter />);

    await waitFor(
      () => expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument(),
      { timeout: 5000 },
    );
  });
});
