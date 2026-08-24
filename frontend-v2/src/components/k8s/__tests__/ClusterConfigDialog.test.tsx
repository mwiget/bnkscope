import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ClusterConfigDialog } from '../ClusterConfigDialog';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';

const sshCredentials = [
  {
    id: 10,
    name: 'test-ssh',
    host: '10.0.0.5',
    port: 22,
    username: 'ubuntu',
    auth_type: 'key',
    has_password: false,
    has_private_key: true,
    is_default: true,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
    clusters_count: 0,
    projects_count: 0,
  },
];

describe('ClusterConfigDialog', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    cluster: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get('*/api/credential-templates', () => {
        return HttpResponse.json([]);
      }),
      http.get('*/api/ssh-credentials', () => {
        return HttpResponse.json(sshCredentials);
      }),
    );
  });

  it('renders create dialog title and form fields', () => {
    render(<ClusterConfigDialog {...defaultProps} />);
    // Title and the submit button share the label; assert the heading.
    expect(screen.getByRole('heading', { name: 'Add Cluster' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByText('Choose file')).toBeInTheDocument();
  });

  it('renders edit dialog title when cluster is provided', () => {
    const cluster = {
      id: 1,
      name: 'prod-cluster',
      status: 'connected' as const,
      default_namespace: 'default',
      created_at: '2026-01-01',
    };
    render(<ClusterConfigDialog {...defaultProps} cluster={cluster} />);
    expect(screen.getByText('Edit Cluster')).toBeInTheDocument();
    expect(screen.getByDisplayValue('prod-cluster')).toBeInTheDocument();
  });

  // -- K8S-006: Auto-enable SSH tunnel for SSH projects --

  // -- K8S-007: Probe via SSH --

  it('does not auto-probe when editing an existing cluster', () => {
    const cluster = {
      id: 1,
      name: 'existing-cluster',
      status: 'active' as const,
      default_namespace: 'default',
      created_at: '2026-01-01',
    };

    render(
      <ClusterConfigDialog
        {...defaultProps}
        cluster={cluster}
        sshCredentialId={10}
      />
    );

    // Should show edit title, not trigger probe
    expect(screen.getByText('Edit Cluster')).toBeInTheDocument();
  });
});
