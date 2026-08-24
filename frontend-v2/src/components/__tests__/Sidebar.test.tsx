/**
 * The bnkscope sidebar.
 *
 * Phase 6 cut it from 16 entries across five collapsible sections to four
 * lenses plus two utility links, so most of what these tests assert is what is
 * *not* there any more — a nav that quietly regrows sections is the failure
 * mode worth catching.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { Sidebar } from '@/components/layout/Sidebar';

describe('Sidebar', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe('branding', () => {
    it('renders the bnkscope wordmark', () => {
      render(<Sidebar />);
      // Scoped to the span: the inlined mark carries its own <title>bnkscope</title>,
      // which is the SVG's accessible name, not the visible wordmark.
      expect(screen.getByText('bnkscope', { selector: 'span' })).toBeInTheDocument();
    });

    it('renders the mark as a labelled image', () => {
      render(<Sidebar />);
      expect(screen.getAllByRole('img', { name: 'bnkscope' }).length).toBeGreaterThan(0);
    });

    it('carries no bnk-forge branding', () => {
      render(<Sidebar />);
      expect(screen.queryByText('BNK Forge')).not.toBeInTheDocument();
      expect(screen.queryByText('Infrastructure')).not.toBeInTheDocument();
    });
  });

  describe('navigation', () => {
    it('renders the four lenses', () => {
      render(<Sidebar />);
      for (const name of ['Clusters', 'BNK Health', 'CNF Resources', 'AI Gateway']) {
        expect(screen.getByText(name)).toBeInTheDocument();
      }
    });

    it('points each lens at its route', () => {
      render(<Sidebar />);
      expect(screen.getByText('Clusters').closest('a')).toHaveAttribute('href', '/kubernetes');
      expect(screen.getByText('BNK Health').closest('a')).toHaveAttribute('href', '/bnk');
      expect(screen.getByText('CNF Resources').closest('a')).toHaveAttribute('href', '/cnf');
      expect(screen.getByText('AI Gateway').closest('a')).toHaveAttribute(
        'href',
        '/observability/ai-gateway',
      );
    });

    it('keeps System and MCP reachable but out of the main list', () => {
      render(<Sidebar />);
      // Backup/restore lives behind System, so it must not become unreachable.
      expect(screen.getByText('System').closest('a')).toHaveAttribute('href', '/system');
      expect(screen.getByText('MCP').closest('a')).toHaveAttribute('href', '/mcp-server');
    });

    it('has no section headings left', () => {
      render(<Sidebar />);
      for (const heading of ['OBSERVE', 'OPERATE', 'SETTINGS', 'BUILD', 'CATALOG']) {
        expect(screen.queryByText(heading)).not.toBeInTheDocument();
      }
    });

    it('no longer links to anything the pipeline owned', () => {
      render(<Sidebar />);
      for (const gone of [
        'Command Center',
        'Projects',
        'Fleet',
        'Catalog',
        'Blueprints',
        'Access Methods',
        'Users',
        'Operations Log',
        'Benchmarks',
      ]) {
        expect(screen.queryByText(gone)).not.toBeInTheDocument();
      }
    });

    it('the wordmark links home', () => {
      render(<Sidebar />);
      expect(screen.getByLabelText('bnkscope home')).toHaveAttribute('href', '/');
    });
  });

  describe('collapse', () => {
    it('hides labels but keeps the links when collapsed', async () => {
      const user = userEvent.setup();
      render(<Sidebar />);

      await user.click(screen.getByLabelText('Collapse sidebar'));

      expect(screen.getByLabelText('Expand sidebar')).toBeInTheDocument();
      expect(screen.queryByText('bnkscope', { selector: 'span' })).not.toBeInTheDocument();
      // The link itself survives — the label is sr-only, not removed.
      expect(screen.getByText('Clusters').closest('a')).toHaveAttribute('href', '/kubernetes');
    });

    it('expands again', async () => {
      const user = userEvent.setup();
      render(<Sidebar />);

      await user.click(screen.getByLabelText('Collapse sidebar'));
      await user.click(screen.getByLabelText('Expand sidebar'));

      expect(screen.getByText('bnkscope', { selector: 'span' })).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('is an aside with a label', () => {
      render(<Sidebar />);
      expect(screen.getByLabelText('Application sidebar')).toBeInTheDocument();
    });

    it('labels the nav', () => {
      render(<Sidebar />);
      expect(screen.getByLabelText('Main navigation')).toBeInTheDocument();
    });
  });

  it('shows the app version', () => {
    render(<Sidebar />);
    // __APP_VERSION__ is defined in vitest.config.ts
    expect(screen.getByText(/^v\d/)).toBeInTheDocument();
  });
});
