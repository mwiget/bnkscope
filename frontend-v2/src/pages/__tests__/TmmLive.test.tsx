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
        last_seen: { 'dpu-cplane-tenant1': 3 },
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
        permanent_pods: 0,
        permanent_owner: null,
        streaming_pods: 0,
        silent_pods: 0,
        verdict: null,
        verdict_detail: null,
        settle_seconds: 90,
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
        last_seen_age: 3,
        dashboard_url:
          'http://localhost:3000/d/tmm-realtime?var-cluster=dpu-cplane-tenant1&theme=dark&kiosk',
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

    it('does not let the stack answering its own health check read as metrics', async () => {
      // One green "telemetry up" badge meant only that Grafana answered
      // /api/health. It stayed green through a cluster that had stopped
      // delivering entirely, which is the most confident possible way to be
      // wrong about the one thing the page is for.
      serveStatus({ streaming_clusters: [], last_seen: { 'dpu-cplane-tenant1': 543 } });
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: 543,
      });
      serveInjection({ tmm_pods: 1, injected_pods: 1, injected: true, verdict: 'not_delivering' });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('stopped 9m ago')).toBeInTheDocument(),
      );
      expect(screen.getByText('stack up')).toBeInTheDocument();
      expect(screen.queryByText('telemetry up')).not.toBeInTheDocument();
    });

    it('names the label the telemetry arrives under', async () => {
      serveStatus();
      serveTelemetry();

      render(<TmmLive />);

      await waitFor(() => expect(screen.getByText('streaming')).toBeInTheDocument());
      expect(screen.getAllByText('dpu-cplane-tenant1').length).toBeGreaterThan(0);
    });

    it('names the one node that went silent while the cluster kept streaming', async () => {
      // Reinstall one DPU of several and the cluster-level answer stays green:
      // its siblings are still pushing. The dashboard is simply missing a node,
      // with nothing on the page to say which or why.
      serveStatus();
      serveTelemetry();
      serveInjection({
        tmm_pods: 2,
        injected_pods: 2,
        injected: true,
        streaming_pods: 1,
        silent_pods: 1,
        verdict: 'partial_delivery',
        verdict_detail: '1 of 2 exporter(s) stopped delivering.',
        pods: [
          {
            pod: 'tmm-alive',
            namespace: 'ns',
            injected: true,
            kind: 'permanent',
            pushing_to: 'http://192.168.68.113:9491/api/v1/write',
            stale: false,
            started_at: null,
            running_for: 4000,
            streaming: true,
            last_push_error: null,
          },
          {
            pod: 'tmm-reinstalled',
            namespace: 'ns',
            injected: true,
            kind: 'permanent',
            pushing_to: 'http://192.168.68.113:9491/api/v1/write',
            stale: false,
            started_at: null,
            running_for: 600,
            streaming: false,
            last_push_error: 'remote_write: connect: connection refused',
          },
        ],
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/stopped delivering/i)).toBeInTheDocument(),
      );
      // Named in the list of silent pods, and again on its own error line.
      expect(screen.getAllByText(/tmm-reinstalled/).length).toBeGreaterThan(0);
      expect(screen.getByText(/connection refused/)).toBeInTheDocument();
      // The one that is fine is not called out as a problem.
      expect(screen.queryByText(/tmm-alive/)).not.toBeInTheDocument();
    });

    it('will not offer to recreate pods for a sidecar it did not put there', async () => {
      // A permanent sidecar is in the pod template. Deleting the pod drops
      // dataplane traffic and the exporter comes back with the replacement —
      // all cost, no effect.
      serveStatus();
      serveTelemetry();
      serveInjection({
        injected_pods: 2,
        injected: true,
        permanent_pods: 2,
        permanent_owner: 'DaemonSet f5-tmm',
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('Stop streaming from this cluster')).toBeInTheDocument(),
      );
      expect(
        screen.queryByRole('button', { name: /remove the exporter/i }),
      ).not.toBeInTheDocument();
      expect(screen.getByText(/permanent sidecar in the TMM pod template/i)).toBeInTheDocument();
      // The whole point of refusing: say where it *can* be removed. A command
      // cannot — the sidecar may have come from any of several cluster
      // builders — but the workload that owns the template can.
      expect(screen.getByText('DaemonSet f5-tmm')).toBeInTheDocument();
    });

    it('keeps removal behind a fold', async () => {
      serveStatus();
      serveTelemetry();

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText('Stop streaming from this cluster')).toBeInTheDocument(),
      );
    });

    it('says there is nothing to remove rather than naming a CLI', async () => {
      // Nothing bnkscope put there is nothing for it to take out. The old copy
      // printed `tmmscope eject` here, which was wrong twice: it is a binary
      // the operator may not have, and it only undoes `tmmscope inject
      // --permanent` — not a sidecar the cluster build shipped.
      serveStatus();
      serveTelemetry();
      serveInjection({ injected_pods: 0 });

      render(<TmmLive />);

      await waitFor(() =>
        expect(
          screen.getByText(/did not inject this cluster's exporter/i),
        ).toBeInTheDocument(),
      );
      expect(screen.queryByText(/tmmscope eject/)).not.toBeInTheDocument();
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
        last_seen_age: null,
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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
      serveInjection({
        tmm_pods: 3,
        injected_pods: 3,
        injected: true,
        verdict: 'settling',
        verdict_detail: 'The exporter started 12s ago.',
      });

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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
      serveInjection({
        tmm_pods: 3,
        injected_pods: 3,
        injected: true,
        verdict: 'settling',
        verdict_detail: 'The exporter started 12s ago.',
      });

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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
      serveInjection({
        tmm_pods: 3,
        injected_pods: 3,
        injected: true,
        stale: true,
        stale_pods: 3,
        stale_target: 'http://192.168.99.1:9492/api/v1/write',
        expected_port: 9491,
        verdict: 'stale_target',
        verdict_detail: 'The exporter is pushing to a port nothing is listening on.',
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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });
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
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(
          screen.getByText(/does not survive a pod restart/),
        ).toBeInTheDocument(),
      );
      expect(screen.getByText(/does not\s+restart TMM/)).toBeInTheDocument();
    });

    it('stops claiming the metrics are on their way once they plainly are not', async () => {
      // The bug: an exporter installed, running, and pushing at the right
      // address into a black hole rendered as "waiting for the first metrics —
      // this takes a few seconds", forever. Re-installing it fixes nothing, so
      // the page must say what is actually wrong instead of offering hope.
      serveStatus({ streaming_clusters: [], last_seen: { 'dpu-cplane-tenant1': 543 } });
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: 543,
      });
      serveInjection({
        tmm_pods: 1,
        injected_pods: 1,
        injected: true,
        permanent_pods: 1,
        silent_pods: 1,
        verdict: 'not_delivering',
        verdict_detail:
          'The exporter has been running 9m and pushing to ' +
          'http://192.168.68.113:9491/api/v1/write, and nothing has arrived.',
        pods: [
          {
            pod: 'tmm-j7mxf',
            namespace: 'dpf-operator-system',
            injected: true,
            kind: 'permanent',
            pushing_to: 'http://192.168.68.113:9491/api/v1/write',
            stale: false,
            started_at: '2026-08-26T08:20:15Z',
            running_for: 600,
            streaming: false,
            last_push_error:
              'remote_write: Post "http://192.168.68.113:9491/api/v1/write": ' +
              'dial tcp: connect: connection refused',
          },
        ],
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/nothing has arrived/i)).toBeInTheDocument(),
      );
      // The exporter's own words. Every symptom of this lives inside the pod,
      // and this line is the one that names the cause.
      expect(screen.getByText(/connection refused/)).toBeInTheDocument();
      expect(screen.queryByText(/waiting for the first metrics/i)).not.toBeInTheDocument();
      // Neither offered action would change anything here.
      expect(
        screen.queryByRole('button', { name: /add the exporter/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /remove the exporter/i }),
      ).not.toBeInTheDocument();
    });

    it('says when it last delivered, not just that it is not delivering now', async () => {
      // Prometheus drops a series once it goes stale, so "not streaming" alone
      // reads identically for a cluster that stopped nine minutes ago and one
      // that never streamed — and sends you hunting a missing exporter that is
      // in fact installed and running.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: 543,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByText(/last delivered metrics/i)).toBeInTheDocument(),
      );
      expect(screen.getByText('9m ago')).toBeInTheDocument();
    });

    it('does not send you to a CLI bnkscope does not need', async () => {
      // The button is the whole path: bnkscope injects through the Kubernetes
      // API it already holds a client for, and `bnkscope up` brings its own
      // Prometheus and Grafana. Printing `tmmscope inject` here advertised a
      // dependency that is not one, at the exact moment the operator is least
      // able to tell the difference.
      serveStatus({ streaming_clusters: [] });
      serveTelemetry({
        streaming: false,
        available_labels: [],
        dashboard_url: null,
        last_seen_age: null,
      });

      render(<TmmLive />);

      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Add the exporter' })).toBeInTheDocument(),
      );
      expect(screen.queryByText('Or run it on the host')).not.toBeInTheDocument();
      expect(screen.queryByText(/tmmscope inject --context/)).not.toBeInTheDocument();
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
