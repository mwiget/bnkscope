/**
 * Tests for CommandPalette component
 *
 * Covers: renders when open, shows quick actions, navigation items,
 * recent projects, recent deployments, search input, item selection
 * triggers navigation and closes palette.
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { CommandPalette } from '@/components/CommandPalette';
import { NAV_SHORTCUTS } from '@/hooks/useKeyboardShortcuts';

// Mock scrollIntoView (used by cmdk library, not available in jsdom)
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

// Mock navigation
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

describe('CommandPalette', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders search input when open', () => {
    render(<CommandPalette {...defaultProps} />);

    expect(screen.getByPlaceholderText(/type a command or search/i)).toBeInTheDocument();
  });

  it('renders Navigation group', async () => {
    render(<CommandPalette {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('Navigation')).toBeInTheDocument();
    });
  });

  it('offers every page, under the name the sidebar uses', async () => {
    // Generated from NAV_SHORTCUTS, so it cannot drift from the router again.
    // Hand-maintained, it had six entries: two pointed at /fleet — deleted
    // with the pipeline — five of the nine pages were missing, and the labels
    // disagreed with the sidebar. This test asserted "Fleet Overview" was
    // present, so the suite certified the bug.
    render(<CommandPalette {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText('Overview')).toBeInTheDocument();
    });
    for (const label of NAV_SHORTCUTS.map((n) => n.label)) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('offers nothing that is not a live route', async () => {
    render(<CommandPalette {...defaultProps} />);

    await waitFor(() => expect(screen.getByText('Overview')).toBeInTheDocument());
    for (const gone of ['Fleet Overview', 'Fleet: Operators', 'Dashboard']) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it('renders no empty group heading', async () => {
    // `quickActions` was an empty array inside a <CommandGroup heading="Quick
    // Actions">, so the palette opened with a labelled section containing
    // nothing.
    render(<CommandPalette {...defaultProps} />);

    await waitFor(() => expect(screen.getByText('Overview')).toBeInTheDocument());
    expect(screen.queryByText('Quick Actions')).not.toBeInTheDocument();
  });

  it('does not render when open is false', () => {
    render(<CommandPalette open={false} onOpenChange={vi.fn()} />);

    expect(screen.queryByPlaceholderText(/type a command or search/i)).not.toBeInTheDocument();
  });

  it('shows the G-sequence for each page', async () => {
    render(<CommandPalette {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getAllByText(/^G [A-Z]$/).length).toBe(NAV_SHORTCUTS.length);
    });
  });
});
