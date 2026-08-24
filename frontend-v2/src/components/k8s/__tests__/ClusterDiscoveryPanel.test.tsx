/**
 * The discovery panel is the operator's whole answer to "why isn't my cluster
 * here?", so what these tests pin down is that the answer is actually shown:
 * the state, the reason, and whether there is anything to click.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';

import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { server } from '@/test/mocks/server';
import { ClusterDiscoveryPanel } from '../ClusterDiscoveryPanel';
import type { DiscoveryCandidate } from '@/types';

function candidate(overrides: Partial<DiscoveryCandidate> = {}): DiscoveryCandidate {
  return {
    context: 'lab-a',
    api_server: 'https://10.1.2.3:6443',
    cloud_provider: 'on-prem',
    auth_method: 'client-certificate',
    source_path: '/host/.kube/config',
    state: 'reachable',
    registered: false,
    cluster_id: null,
    has_bnk: false,
    version: '1.29',
    detail: null,
    ...overrides,
  };
}

function serveCandidates(candidates: DiscoveryCandidate[]) {
  server.use(
    http.get('*/api/k8s/discovery', () =>
      HttpResponse.json({
        candidates,
        found: candidates.length,
        registered: candidates.filter((c) => c.registered).length,
      }),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ClusterDiscoveryPanel', () => {
  it('lists a discovered context with its state and version', async () => {
    serveCandidates([candidate()]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() => expect(screen.getByText('lab-a')).toBeInTheDocument());
    expect(screen.getByText('Reachable')).toBeInTheDocument();
    expect(screen.getByText('v1.29')).toBeInTheDocument();
    expect(screen.getByText(/10\.1\.2\.3:6443/)).toBeInTheDocument();
  });

  it('marks a context that registered itself and offers no Add button', async () => {
    serveCandidates([candidate({ registered: true, has_bnk: true, cluster_id: 1 })]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() => expect(screen.getByText('Added')).toBeInTheDocument());
    expect(screen.getByText('BNK')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument();
  });

  it('offers Add for a reachable context that was only reported', async () => {
    serveCandidates([
      candidate({ detail: 'Reachable, but no F5/BNK namespace found.' }),
    ]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/no F5\/BNK namespace found/)).toBeInTheDocument();
  });

  it('adopts a context when Add is clicked', async () => {
    const adopted = vi.fn();
    serveCandidates([candidate()]);
    server.use(
      http.post('*/api/k8s/discovery/adopt', async ({ request }) => {
        adopted(await request.json());
        return HttpResponse.json({ candidates: [], found: 1, registered: 1 });
      }),
    );

    render(<ClusterDiscoveryPanel />);
    const button = await screen.findByRole('button', { name: /add/i });
    await userEvent.click(button);

    // Only the context name is sent — the kubeconfig is re-read on the host.
    await waitFor(() => expect(adopted).toHaveBeenCalledWith({ context: 'lab-a' }));
  });

  it('does not offer Add for an unreachable context', async () => {
    serveCandidates([
      candidate({ state: 'unreachable', version: null, detail: 'Timed out — VPN down.' }),
    ]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() => expect(screen.getByText('Unreachable')).toBeInTheDocument());
    expect(screen.getByText(/VPN down/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument();
  });

  it('shows why an unusable context cannot be added', async () => {
    serveCandidates([
      candidate({
        context: 'aks-prod',
        state: 'unusable',
        auth_method: 'exec:kubelogin',
        detail: 'This context authenticates with `kubelogin`, which bnkscope cannot run.',
      }),
    ]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() => expect(screen.getByText('Cannot use')).toBeInTheDocument());
    // Named twice on purpose: once as the auth method, once in the reason.
    expect(screen.getByText(/bnkscope cannot run/)).toBeInTheDocument();
    expect(screen.getByText(/exec:kubelogin/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument();
  });

  it('explains the mount when no contexts are found at all', async () => {
    serveCandidates([]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() =>
      expect(screen.getByText('No kube contexts found')).toBeInTheDocument(),
    );
    expect(screen.getByText(/mounted read-only/)).toBeInTheDocument();
  });

  it('surfaces a failed sweep rather than showing an empty list', async () => {
    server.use(
      http.get('*/api/k8s/discovery', () =>
        HttpResponse.json({ error: { message: 'boom' } }, { status: 500 }),
      ),
    );
    render(<ClusterDiscoveryPanel />);

    await waitFor(() =>
      expect(screen.getByText(/Could not read the local kubeconfig/)).toBeInTheDocument(),
    );
  });

  it('re-probes on Rescan', async () => {
    let sweeps = 0;
    server.use(
      http.get('*/api/k8s/discovery', () => {
        sweeps += 1;
        return HttpResponse.json({ candidates: [candidate()], found: 1, registered: 0 });
      }),
    );

    render(<ClusterDiscoveryPanel />);
    await waitFor(() => expect(sweeps).toBe(1));

    await userEvent.click(screen.getByRole('button', { name: /rescan/i }));
    await waitFor(() => expect(sweeps).toBe(2));
  });

  it('counts what was found, registered, and left out', async () => {
    serveCandidates([
      candidate({ context: 'a', registered: true, has_bnk: true }),
      candidate({ context: 'b' }),
      candidate({ context: 'c', state: 'unreachable' }),
    ]);
    render(<ClusterDiscoveryPanel />);

    await waitFor(() =>
      expect(screen.getByText(/3 contexts found · 1 registered · 2 not added/)).toBeInTheDocument(),
    );
  });
});
