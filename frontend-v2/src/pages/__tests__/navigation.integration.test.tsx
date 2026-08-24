/**
 * Navigation & Routing Integration Tests
 *
 * Tests that the Sidebar and Header components render correct navigation
 * structure, links, breadcrumbs, and interactive elements when composed
 * together with the router and auth state.
 *
 * Lower-level auth-gated visibility (viewer vs admin) is covered in
 * auth-flow.integration.test.tsx. These tests focus on navigation structure
 * and header context for an authenticated admin user.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, act } from '@testing-library/react';
import { render } from '@/test/test-utils';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';

// ---------------------------------------------------------------------------
// Navigation mock — capture navigate calls without full router integration
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

// ---------------------------------------------------------------------------
// MSW overrides for Header notification endpoints (not in default handlers)
// ---------------------------------------------------------------------------

beforeEach(() => {
  mockNavigate.mockReset();
  localStorage.clear();

  // Add notification handlers so Header renders without unhandled request warnings
  server.use(
    http.get('*/api/notifications', () => {
      return HttpResponse.json([]);
    }),
    http.get('*/api/notifications/unread-count', () => {
      return HttpResponse.json({ count: 0 });
    }),
  );
});

// ===========================================================================
// Sidebar Tests
// ===========================================================================

describe('Navigation Integration', () => {
  // -------------------------------------------------------------------------
  // 1. Sidebar renders the four lenses, flat
  // -------------------------------------------------------------------------
  describe('Sidebar renders all navigation entries', () => {
    it('shows the four lenses and the two utility links, with no sections', async () => {

      render(<Sidebar />);

      // Wait for async data (badge counts) to settle
      await waitFor(() => {
        expect(screen.getByText('Clusters')).toBeInTheDocument();
      });

      expect(screen.getByText('BNK Health')).toBeInTheDocument();
      expect(screen.getByText('CNF Resources')).toBeInTheDocument();
      expect(screen.getByText('AI Gateway')).toBeInTheDocument();

      // Utility links — demoted, not removed.
      expect(screen.getByText('System')).toBeInTheDocument();
      expect(screen.getByText('MCP')).toBeInTheDocument();

      // Phase 6 collapsed five sections into one flat list.
      expect(screen.queryByText('OBSERVE')).not.toBeInTheDocument();
      expect(screen.queryByText('OPERATE')).not.toBeInTheDocument();
      expect(screen.queryByText('SETTINGS')).not.toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // 2. Sidebar nav links have correct hrefs
  // -------------------------------------------------------------------------
  describe('Sidebar nav links have correct hrefs', () => {
    it('renders Clusters with href="/kubernetes" and BNK Health with href="/bnk"', async () => {

      render(<Sidebar />);

      await waitFor(() => {
        expect(screen.getByText('Clusters')).toBeInTheDocument();
      });

      expect(screen.getByText('Clusters').closest('a')).toHaveAttribute('href', '/kubernetes');
      expect(screen.getByText('BNK Health').closest('a')).toHaveAttribute('href', '/bnk');
    });
  });

  // -------------------------------------------------------------------------
  // 4. Header search button renders with keyboard shortcut
  // -------------------------------------------------------------------------
  describe('Header search button renders with keyboard shortcut', () => {
    it('displays "Search..." text and ⌘K shortcut badge', async () => {

      render(<Header />, { initialRoute: '/' });

      await waitFor(() => {
        expect(screen.getByText('Search...')).toBeInTheDocument();
      });

      expect(screen.getByText('⌘K')).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // 5. Header notification bell renders
  // -------------------------------------------------------------------------
  describe('Header notification bell renders', () => {
    it('renders a notification bell button with aria-label="Notifications"', async () => {

      render(<Header />, { initialRoute: '/' });

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
      });
    });
  });
});
