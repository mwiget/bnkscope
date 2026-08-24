/**
 * Tests for DatabaseManagement component
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import DatabaseManagement from '../DatabaseManagement';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DatabaseManagement', () => {
  it('renders collapsible card header', () => {
    render(<DatabaseManagement />);
    expect(screen.getByText('Database management')).toBeInTheDocument();
    expect(
      screen.getByText('Monitor database size and reclaim unused space')
    ).toBeInTheDocument();
  });

  it('shows database stats when expanded', async () => {
    const user = userEvent.setup();
    render(<DatabaseManagement />);

    await user.click(screen.getByText('Database management'));

    await waitFor(() => {
      expect(screen.getByText('Database Overview')).toBeInTheDocument();
      expect(screen.getByText('Total Database Size')).toBeInTheDocument();
    });
  });

  it('offers vacuum, and no record deletion', async () => {
    // The Delete Old Records control posted to /api/system/database/cleanup,
    // which the backend has never served, and its three record types all named
    // tables from the removed pipeline. Vacuum is the one the backend has.
    const user = userEvent.setup();
    render(<DatabaseManagement />);

    await user.click(screen.getByText('Database management'));

    await waitFor(() => {
      expect(screen.getByText('Maintenance')).toBeInTheDocument();
      expect(screen.getByText('Vacuum & Optimize')).toBeInTheDocument();
    });
    expect(screen.queryByText('Delete Old Records')).not.toBeInTheDocument();
  });
});
