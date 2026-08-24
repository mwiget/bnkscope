/**
 * The two ways to add a cluster, in one dialog.
 *
 * The ordering is the point: discovery first, kubeconfig form behind a
 * deliberate click. bnkscope runs where the kubeconfig already is, so making
 * the form the default would suggest typing is the normal route.
 */
import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';

import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { server } from '@/test/mocks/server';
import { AddClusterDialog } from '../AddClusterDialog';

describe('AddClusterDialog', () => {
  it('leads with what was discovered, not with the form', async () => {
    server.use(
      http.get('*/api/k8s/discovery', () =>
        HttpResponse.json({
          candidates: [
            {
              context: 'lab-a',
              api_server: 'https://10.1.2.3:6443',
              cloud_provider: 'on-prem',
              auth_method: 'token',
              source_path: '/host/.kube/config',
              state: 'reachable',
              registered: false,
              cluster_id: null,
              has_bnk: false,
              version: '1.29',
              detail: null,
            },
          ],
          found: 1,
          registered: 0,
        }),
      ),
    );

    render(<AddClusterDialog open onOpenChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('lab-a')).toBeInTheDocument());
    // The kubeconfig textarea is not on screen until asked for.
    expect(screen.queryByLabelText(/kubeconfig/i)).not.toBeInTheDocument();
  });

  it('offers the kubeconfig form as the stated fallback', async () => {
    render(<AddClusterDialog open onOpenChange={vi.fn()} />);

    await waitFor(() =>
      expect(
        screen.getByText(/Not in your kubeconfig, or using an auth plugin/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('button', { name: /paste a kubeconfig instead/i }),
    ).toBeInTheDocument();
  });

  it('swaps to the manual form when asked', async () => {
    render(<AddClusterDialog open onOpenChange={vi.fn()} />);

    const fallback = await screen.findByRole('button', {
      name: /paste a kubeconfig instead/i,
    });
    await userEvent.click(fallback);

    // The candidate list steps aside rather than stacking behind the form.
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: /paste a kubeconfig instead/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it('renders nothing when closed', () => {
    render(<AddClusterDialog open={false} onOpenChange={vi.fn()} />);
    expect(screen.queryByText('Add a cluster')).not.toBeInTheDocument();
  });
});
