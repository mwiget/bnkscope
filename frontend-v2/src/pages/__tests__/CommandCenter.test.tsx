/**
 * The home page.
 *
 * Its whole job is to answer "is anything wrong right now, and where?", so the
 * tests are about ordering and framing: trouble first, a headline that reflects
 * reality, and discovery instead of an empty grid when nothing is registered.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';

import { render, screen, waitFor } from '@/test/test-utils';
import { server } from '@/test/mocks/server';
import CommandCenter from '@/pages/CommandCenter';

function cluster(id: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    name,
    context: name,
    api_server: `https://${name}:6443`,
    cloud_provider: 'on-prem',
    default_namespace: 'default',
    status: 'active',
    version: '1.29',
    ...extra,
  };
}

function serveClusters(clusters: ReturnType<typeof cluster>[]) {
  server.use(
    http.get('*/api/k8s/clusters', ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname !== '/api/k8s/clusters') return;
      return HttpResponse.json({ clusters, count: clusters.length });
    }),
  );
}

/** Reachability arrives over the connectivity registry, not the cluster list. */
function serveReachability(states: { target_id: number; state: string }[]) {
  server.use(
    http.get('*/api/connectivity/state', () =>
      HttpResponse.json({
        states: states.map((s) => ({
          target_type: 'cluster',
          target_id: s.target_id,
          state: s.state,
          checked_at: '2026-08-23T00:00:00Z',
          error_context: {},
        })),
      }),
    ),
  );
}

function serveNotifications(items: Record<string, unknown>[]) {
  server.use(
    http.get('*/api/notifications', () => HttpResponse.json(items)),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  serveNotifications([]);
});

describe('CommandCenter', () => {
  describe('with no clusters', () => {
    it('hands over to discovery rather than showing an empty grid', async () => {
      serveClusters([]);
      render(<CommandCenter />);

      await waitFor(() =>
        expect(screen.getByText(/Nothing registered yet/)).toBeInTheDocument(),
      );
      expect(screen.getByText('Discovered from your kubeconfig')).toBeInTheDocument();
    });
  });

  describe('with clusters', () => {
    it('lists them', async () => {
      serveClusters([cluster(1, 'lab-a'), cluster(2, 'lab-b')]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText('lab-a')).toBeInTheDocument());
      expect(screen.getByText('lab-b')).toBeInTheDocument();
    });

    it('says everything is fine when everything is reachable', async () => {
      serveClusters([cluster(1, 'lab-a')]);
      serveReachability([{ target_id: 1, state: 'reachable' }]);
      render(<CommandCenter />);

      await waitFor(() =>
        expect(screen.getByText('Everything is reachable')).toBeInTheDocument(),
      );
      expect(screen.getByText('1 cluster responding.')).toBeInTheDocument();
    });

    it('leads with the problem when one is unreachable', async () => {
      serveClusters([cluster(1, 'lab-a'), cluster(2, 'lab-b')]);
      serveReachability([
        { target_id: 1, state: 'reachable' },
        { target_id: 2, state: 'unreachable' },
      ]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText('Needs attention')).toBeInTheDocument());
      expect(screen.getByText('1 of 2 clusters not responding.')).toBeInTheDocument();
    });

    it('sorts the unreachable cluster above the healthy one', async () => {
      // Deliberately named so alphabetical order would put the healthy one first.
      serveClusters([cluster(1, 'aaa-healthy'), cluster(2, 'zzz-broken')]);
      serveReachability([
        { target_id: 1, state: 'reachable' },
        { target_id: 2, state: 'unreachable' },
      ]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText('zzz-broken')).toBeInTheDocument());

      const names = screen
        .getAllByRole('link')
        .map((a) => a.textContent ?? '')
        .filter((t) => t.includes('healthy') || t.includes('broken'));
      expect(names[0]).toContain('zzz-broken');
    });

    it('shows the API server and version on each row', async () => {
      serveClusters([cluster(1, 'lab-a')]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText(/https:\/\/lab-a:6443/)).toBeInTheDocument());
      expect(screen.getByText(/v1\.29/)).toBeInTheDocument();
    });

    it('links every cluster into the browser', async () => {
      serveClusters([cluster(1, 'lab-a')]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText('lab-a')).toBeInTheDocument());
      expect(screen.getByText('lab-a').closest('a')).toHaveAttribute('href', '/kubernetes');
    });
  });

  describe('alerts', () => {
    it('surfaces unread errors and warnings', async () => {
      serveClusters([cluster(1, 'lab-a')]);
      serveNotifications([
        {
          id: 1,
          user: 'local',
          type: 'error',
          title: 'TMM crashlooping',
          message: 'f5-tmm-0 restarted 5 times',
          is_read: false,
          created_at: '2026-08-23T00:00:00Z',
          severity: 'error',
          category: 'cluster',
          action_url: null,
          dedupe_key: null,
        },
      ]);
      render(<CommandCenter />);

      await waitFor(() =>
        expect(screen.getByText('TMM crashlooping')).toBeInTheDocument(),
      );
      expect(screen.getByText(/f5-tmm-0 restarted 5 times/)).toBeInTheDocument();
    });

    it('ignores read notifications and plain info', async () => {
      serveClusters([cluster(1, 'lab-a')]);
      serveNotifications([
        {
          id: 1, user: 'local', type: 'error', title: 'Already seen',
          message: 'x', is_read: true, created_at: '2026-08-23T00:00:00Z',
          severity: 'error', category: 'cluster', action_url: null, dedupe_key: null,
        },
        {
          id: 2, user: 'local', type: 'info', title: 'Just FYI',
          message: 'y', is_read: false, created_at: '2026-08-23T00:00:00Z',
          severity: 'info', category: 'cluster', action_url: null, dedupe_key: null,
        },
      ]);
      render(<CommandCenter />);

      await waitFor(() => expect(screen.getByText('lab-a')).toBeInTheDocument());
      expect(screen.queryByText('Already seen')).not.toBeInTheDocument();
      expect(screen.queryByText('Just FYI')).not.toBeInTheDocument();
      expect(screen.queryByText('Unread alerts')).not.toBeInTheDocument();
    });
  });

  describe('errors', () => {
    it('shows a retryable error when the cluster list fails', async () => {
      server.use(
        http.get('*/api/k8s/clusters', ({ request }) => {
          const url = new URL(request.url);
          if (url.pathname !== '/api/k8s/clusters') return;
          return HttpResponse.json({ error: { message: 'boom' } }, { status: 500 });
        }),
      );
      render(<CommandCenter />);

      await waitFor(
        () => expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument(),
        { timeout: 5000 },
      );
    });
  });
});
