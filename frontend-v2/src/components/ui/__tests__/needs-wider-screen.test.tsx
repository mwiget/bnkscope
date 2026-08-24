/**
 * The gate for views a phone cannot honestly render.
 *
 * The property that matters most is the one about *not* gating: being told
 * what a tool cannot do is help, being prevented is not, and the person
 * holding the phone is the one who knows whether they need the graph. So
 * "Show anyway" is always there, and the tests below check it works, sticks,
 * and never appears on a screen wide enough not to need it.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NeedsWiderScreen } from '@/components/ui/needs-wider-screen';
import { VIEWPORTS, resetViewport, setViewportWidth } from '@/test/viewport';

function renderGate(props: Partial<React.ComponentProps<typeof NeedsWiderScreen>> = {}) {
  return render(
    <NeedsWiderScreen
      id={props.id ?? `gate-${Math.random()}`}
      title="The topology graph"
      reason="Nodes overlap below 1024px."
      {...props}
    >
      <div data-testid="the-view">graph</div>
    </NeedsWiderScreen>,
  );
}

beforeEach(() => {
  resetViewport();
});

describe('NeedsWiderScreen', () => {
  describe('when the screen is wide enough', () => {
    it('renders the view and says nothing', () => {
      setViewportWidth(VIEWPORTS.laptop);
      renderGate();

      expect(screen.getByTestId('the-view')).toBeInTheDocument();
      expect(screen.queryByText(/needs a wider screen/i)).not.toBeInTheDocument();
      // No override button to clutter a screen that does not need one.
      expect(screen.queryByRole('button', { name: /show anyway/i })).not.toBeInTheDocument();
    });

    it('an iPad passes the default (handheld) threshold', () => {
      setViewportWidth(VIEWPORTS.ipad);
      renderGate();
      expect(screen.getByTestId('the-view')).toBeInTheDocument();
    });

    it("but not the 'compact' threshold, which wants a desktop", () => {
      setViewportWidth(VIEWPORTS.ipad);
      renderGate({ threshold: 'compact' });
      expect(screen.queryByTestId('the-view')).not.toBeInTheDocument();
    });
  });

  describe('when it is too narrow', () => {
    it('explains rather than rendering something unusable', () => {
      setViewportWidth(VIEWPORTS.iphone);
      renderGate();

      expect(screen.queryByTestId('the-view')).not.toBeInTheDocument();
      expect(screen.getByText(/The topology graph needs a wider screen/)).toBeInTheDocument();
      expect(screen.getByText('Nodes overlap below 1024px.')).toBeInTheDocument();
    });

    it('offers what you can do here instead', () => {
      setViewportWidth(VIEWPORTS.iphone);
      renderGate({ instead: <>Use the list view.</> });

      expect(screen.getByText('Use the list view.')).toBeInTheDocument();
    });

    it('never traps you — "Show anyway" is always offered', async () => {
      setViewportWidth(VIEWPORTS.iphone);
      renderGate({ id: 'escape-hatch' });

      await userEvent.click(screen.getByRole('button', { name: /show anyway/i }));

      expect(screen.getByTestId('the-view')).toBeInTheDocument();
      expect(screen.queryByText(/needs a wider screen/i)).not.toBeInTheDocument();
    });
  });

  describe('the override', () => {
    it('sticks across remounts, so you are not asked on every navigation', async () => {
      setViewportWidth(VIEWPORTS.iphone);
      const { unmount } = renderGate({ id: 'sticky-gate' });

      await userEvent.click(screen.getByRole('button', { name: /show anyway/i }));
      expect(screen.getByTestId('the-view')).toBeInTheDocument();
      unmount();

      renderGate({ id: 'sticky-gate' });
      expect(screen.getByTestId('the-view')).toBeInTheDocument();
    });

    it('is per view — deciding to see the graph does not unlock the terminal', async () => {
      setViewportWidth(VIEWPORTS.iphone);
      const { unmount } = renderGate({ id: 'graph-only' });
      await userEvent.click(screen.getByRole('button', { name: /show anyway/i }));
      unmount();

      renderGate({ id: 'a-different-view' });
      expect(screen.queryByTestId('the-view')).not.toBeInTheDocument();
    });
  });
});
