/**
 * TMM Live.
 *
 * Four states, and the page is judged on whether it tells the operator the
 * right next thing in each: stack down, streaming, streaming under a name we
 * did not recognise, and no clusters at all.
 *
 * Since D-036 injection is a button rather than a printed command, and the
 * property that matters most here is the *asymmetry*: adding the exporter does
 * not restart TMM and is one click, while removing it can only be done by
 * recreating the pods, so it must not be.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';

import userEvent from '@testing-library/user-event';

import { render, screen, waitFor, within } from '@/test/test-utils';
import { server } from '@/test/mocks/server';
import TmmLive from '@/pages/TmmLive';

function serveClusters(clusters: Record<string, unknown>[]) {
  server.use(
    http.get('*/api/k8s/clusters', ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname !== '/api/k8s/clusters') return;
      return HttpResponse.json({ clusters, count: clusters.length });
    }),
  );
}

const CLUSTER = {
  id: 1,
  name: 'dpu-cplane-tenant1',
  context: 'kubernetes-admin@dpu-cplane-tenant1',
  api_server: 'https://192.168.68.200:32170',
  cloud_provider: 'on-prem',
  default_namespace: 'default',
  status: 'active',
};

function serveStatus(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/tmmscope/status', () =>
      HttpResponse.json({
        configured: true,
        running: true,
        grafana_url: 'http://localhost:3000',
        prometheus_url: 'http://localhost:9491',
        updated_at: '2026-08-23T00:00:00Z',
        streaming_clusters: ['dpu-cplane-tenant1'],
        dashboards: [
          { uid: 'tmm-realtime', title: 'TMM Real-Time', description: 'counters' },
        ],
        detail: null,
        ...overrides,
      }),
    ),
  );
}

function serveInjection(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/tmmscope/clusters/:id/injection', () =>
      HttpResponse.json({
        ok: true,
        cluster_id: 1,
        tmm_pods: 2,
        injected_pods: 0,
        injected: false,
        partial: false,
        pods: [],
        added: [],
        skipped: [],
        deleted: [],
        failed: [],
        remote_write_url: null,
        remote_write_derivation: null,
        cluster_label: null,
        detail: null,
        stale: false,
        stale_pods: 0,
        stale_target: null,
        expected_port: 9491,
        ...overrides,
      }),
    ),
  );
}

function serveTelemetry(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/tmmscope/clusters/:id', () =>
      HttpResponse.json({
        cluster_id: 1,
        cluster_name: 'dpu-cplane-tenant1',
        context: 'kubernetes-admin@dpu-cplane-tenant1',
        streaming_as: 'dpu-cplane-tenant1',
        streaming: true,
        label_pinned: false,
        available_labels: ['dpu-cplane-tenant1'],
        dashboard_url:
          'http://localhost:3000/d/tmm-realtime?var-cluster=dpu-cplane-tenant1&theme=dark&kiosk',
        inject_command:
          'tmmscope inject --context kubernetes-admin@dpu-cplane-tenant1 --cluster dpu-cplane-tenant1',
        eject_command: 'tmmscope eject --context kubernetes-admin@dpu-cplane-tenant1',
        ...overrides,
      }),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  serveClusters([CLUSTER]);
  serveInjection();
});

describe('TmmLive', () => {
  describe('when tmmscope is not running', () => {
    it('offers bnkscope\'s own stack first, and tmmscope as an alternative', async () => {
      serveStatus({ running: false, detail: 'No telemetry stack is running.' });
      serveTelemetry({ streaming: false, dashboard_url: null });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('No telemetry stack is running')).toBeInTheDocument(),
      );
      expect(screen.getByText('bnkscope up --telemetry')).toBeInTheDocument();
      // tmmscope still works — this absorbs the stack without breaking anyone
      // already running it.
      expect(screen.getByText('tmmscope up')).toBeInTheDocument();
      expect(screen.getByText(/needs the Docker socket/)).toBeInTheDocument();
    });

    it('renders no dashboard frame', async () => {
      serveStatus({ running: false, detail: 'down' });
      serveTelemetry({ streaming: false, dashboard_url: null });

      const { container } = render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('No telemetry stack is running')).toBeInTheDocument(),
      );
      expect(container.querySelector('iframe')).toBeNull();
    });
  });

  describe('when the cluster is streaming', () => {
    it('links Grafana at its dashboard list, not its home page', async () => {
      // Grafana's home for an anonymous Viewer is a welcome screen, and the TMM
      // dashboards live in a folder — landing on / reads as an empty Grafana.
      serveStatus();
      serveTelemetry();

      render(<TmmLive />);

      const link = await screen.findByRole('link', { name: /open grafana/i });
      expect(link).toHaveAttribute('href', 'http://localhost:3000/dashboards');
    });

    it('embeds the dashboard scoped to that cluster', async () => {
      serveStatus();
      serveTelemetry();

      const { container } = render(<TmmLive />);

      await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
      const frame = container.querySelector('iframe')!;
      expect(frame.getAttribute('src')).toContain('var-cluster=dpu-cplane-tenant1');
      expect(frame.getAttribute('src')).toContain('kiosk');
    });

    it('sandboxes the frame — it is a separate origin even on the same machine', async () => {
      serveStatus();
      serveTelemetry();

      const { container } = render(<TmmLive />);

      await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
      const frame = container.querySelector('iframe')!;
      expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-popups');
      expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    });

    it('names the label the telemetry arrives under', async () => {
      serveStatus();
      serveTelemetry();

      render(<TmmLive />);

      await waitFor(() => expect(screen.getByText('streaming')).toBeInTheDocument());
      expect(screen.getAllByText('dpu-cplane-tenant1').length).toBeGreaterThan(0);
    });

    it('keeps removal behind a fold', async () => {
      serveStatus();
      serveTelemetry();

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('Stop streaming from this cluster')).toBeInTheDocument(),
      );
    });

    it('offers the host eject command when bnkscope did not inject it', async () => {
      // Nothing bnkscope put there — so there is nothing for it to take out,
      // and the durable sidecar it cannot see is removed the way it was added.
      serveStatus();
      serveTelemetry();
      serveInjection({ injected_pods: 0 });

      render(<TmmLive />);

      await waitFor(() =>
        expect(
          screen.getByText('tmmscope eject --context kubernetes-admin@dpu-cplane-tenant1'),
        ).toBeInTheDocument(),
      );
    });

    it('never removes without a typed confirmation', async () => {
      // The asymmetry this page exists to encode: clearing an ephemeral
      // container means recreating the TMM pods, which drops traffic. It must
      // not be reachable in one click the way injecting is.
      serveStatus();
      serveTelemetry();
      serveInjection({ injected_pods: 2, injected: true });

      render(<TmmLive />);

      const button = await screen.findByRole('button', {
        name: /remove the exporter — restarts tmm/i,
      });
      await userEvent.click(button);

      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText(/Restart TMM to remove the exporter/)).toBeInTheDocument();
      expect(within(dialog).getByText(/Dataplane traffic is dropped/)).toBeInTheDocument();

      // Confirm is inert until the cluster name is typed.
      const confirm = within(dialog).getByRole('button', { name: 'Confirm' });
      expect(confirm).toBeDisabled();

      await userEvent.type(
        within(dialog).getByRole('textbox'),
        'dpu-cplane-tenant1',
      );
      expect(confirm).toBeEnabled();
    });
  });

  describe('when the cluster is not streaming', () => {
    it('offers injection as a button, not a command to go and type', async () => {
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({
        streaming: false,
        streaming_as: null,
        available_labels: [],
        dashboard_url: null,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(
          screen.getByText(/dpu-cplane-tenant1 is not streaming/),
        ).toBeInTheDocument(),
      );
      expect(
        screen.getByRole('button', { name: /add the exporter/i }),
      ).toBeEnabled();
    });

    it('replaces the button while metrics are still on their way', async () => {
      // The gap that caused a double injection: the pods carry the exporter,
      // Prometheus has nothing yet, and the page went back to showing an
      // inviting "Add the exporter" as though the click had done nothing.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({ tmm_pods: 3, injected_pods: 3, injected: true });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/waiting for the first metrics/i)).toBeInTheDocument(),
      );
      expect(
        screen.queryByRole('button', { name: /add the exporter/i }),
      ).not.toBeInTheDocument();
    });

    it('says how many pods are already carrying it while waiting', async () => {
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({ tmm_pods: 3, injected_pods: 3, injected: true });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent(
          /Exporter running in 3 of 3 f5-tmm pods/i,
        ),
      );
    });

    it('calls out an exporter left pushing at a port that moved', async () => {
      // The real incident: injected while Prometheus was on 9492, the port
      // later moved back to 9491, and the exporters kept running and kept
      // pushing into a closed socket. Every graph said "no data" and the page
      // offered no way to tell that apart from never having injected.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({
        tmm_pods: 3,
        injected_pods: 3,
        injected: true,
        stale: true,
        stale_pods: 3,
        stale_target: 'http://192.168.99.1:9492/api/v1/write',
        expected_port: 9491,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/http:\/\/192\.168\.99\.1:9492/)).toBeInTheDocument(),
      );
      // Names the fix, and that the fix is not free.
      expect(screen.getByText(/needs the TMM pods recreated/i)).toBeInTheDocument();
      // Injecting again would change nothing — a pod already carrying the
      // exporter is skipped — so it must not be the offered action.
      expect(
        screen.queryByRole('button', { name: /add the exporter/i }),
      ).not.toBeInTheDocument();
    });

    it('says how many pods it would touch', async () => {
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({ tmm_pods: 3 });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/3 f5-tmm pods/)).toBeInTheDocument(),
      );
    });

    it('says there is no TMM here rather than offering a dead button', async () => {
      // A disabled "Add the exporter" under copy reading "Add the exporter to
      // this cluster's TMM pods" is an instruction that cannot be followed.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({ tmm_pods: 0 });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/found no running/i)).toBeInTheDocument(),
      );
      expect(
        screen.queryByRole('button', { name: /add the exporter/i }),
      ).not.toBeInTheDocument();
    });

    it('names DPF as the reason when the cluster is the infra one', async () => {
      // The infrastructure cluster runs the DPF operator and the DPUs; TMM
      // runs on the Kamaji tenant. "No f5-tmm pods" is true but unhelpful
      // there — it reads as something being broken.
      serveClusters([
        {
          id: 1,
          name: 'infra',
          context: 'kubernetes-admin@kubernetes',
          status: 'active',
          meta_data: { has_dpf: true },
        },
      ]);
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });
      serveInjection({ tmm_pods: 0 });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/DPF infrastructure cluster/i)).toBeInTheDocument(),
      );
      expect(
        screen.queryByRole('button', { name: /add the exporter/i }),
      ).not.toBeInTheDocument();
    });

    it('says plainly that the injection is transient', async () => {
      // The one property an operator must not have to discover for themselves.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });

      render(<TmmLive />);

      await waitFor(() =>
        expect(
          screen.getByText(/does not survive a pod restart/),
        ).toBeInTheDocument(),
      );
      expect(screen.getByText(/does not\s+restart TMM/)).toBeInTheDocument();
    });

    it('keeps the host command as an escape hatch', async () => {
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({ streaming: false, available_labels: [], dashboard_url: null });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('Or run it on the host')).toBeInTheDocument(),
      );
      expect(screen.getByText(/tmmscope inject --context/)).toBeInTheDocument();
      // --permanent is the one thing the button deliberately cannot do.
      expect(screen.getByText('--permanent')).toBeInTheDocument();
    });

    it('offers a binding when something else is streaming', async () => {
      // The real mismatch: telemetry is arriving, but under a name bnkscope
      // could not join to this cluster.
      serveStatus({ streaming_clusters: ['some-other-name'] });
      serveTelemetry({
        streaming: false,
        streaming_as: null,
        available_labels: ['some-other-name'],
        dashboard_url: null,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/none of it is labelled for this cluster/)).toBeInTheDocument(),
      );
      expect(screen.getByText('Bind to a streaming label…')).toBeInTheDocument();
    });
  });

  describe('with no clusters', () => {
    it('says to add one first', async () => {
      serveClusters([]);
      serveStatus();

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('No clusters registered')).toBeInTheDocument(),
      );
    });
  });
});
