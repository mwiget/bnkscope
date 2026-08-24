/**
 * Tests for SystemDefaults component
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@/test/test-utils';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';
import SystemDefaults from '../SystemDefaults';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SystemDefaults', () => {
  it('renders section headings after loading', async () => {
    server.use(
      http.get('*/api/system/defaults', () =>
        HttpResponse.json({
          execution: {
            max_retries: { key: 'execution.max_retries', raw_value: '3' },
            retry_delay: { key: 'execution.retry_delay', raw_value: '5' },
          },
        })
      ),
    );

    render(<SystemDefaults />);

    await waitFor(() => {
      expect(screen.getByText('System Defaults')).toBeInTheDocument();
    });
    expect(screen.getByText('Execution settings')).toBeInTheDocument();
    // Project defaults, cloud-provider regions and OpenTofu timeouts were the
    // removed product advertising itself on the most prominent settings
    // surface bnkscope has.
    expect(screen.queryByText('Project defaults')).not.toBeInTheDocument();
    expect(screen.queryByText('Cloud provider defaults')).not.toBeInTheDocument();
    expect(screen.queryByText('OpenTofu timeouts')).not.toBeInTheDocument();
  });

  it('shows save button as disabled when no changes', async () => {
    server.use(
      http.get('*/api/system/defaults', () =>
        HttpResponse.json({
          execution: {
            max_retries: { key: 'execution.max_retries', raw_value: '3' },
          },
        })
      ),
    );

    render(<SystemDefaults />);

    await waitFor(() => {
      expect(screen.getByText('Save Changes')).toBeInTheDocument();
    });

    const saveBtn = screen.getByText('Save Changes').closest('button');
    expect(saveBtn).toBeDisabled();
  });

  it('renders execution settings section', async () => {
    server.use(
      http.get('*/api/system/defaults', () =>
        HttpResponse.json({
          project: { default_type: { key: 'project.default_type', raw_value: 'cloud-ibm' } },
          execution: {
            max_retries: { key: 'execution.max_retries', raw_value: '3' },
            retry_delay: { key: 'execution.retry_delay', raw_value: '5' },
          },
        })
      ),
    );

    render(<SystemDefaults />);

    await waitFor(() => {
      expect(screen.getByText('Execution settings')).toBeInTheDocument();
    });
    expect(screen.getByText('Max Retries')).toBeInTheDocument();
    expect(screen.getByText('Retry Delay')).toBeInTheDocument();
  });
});
