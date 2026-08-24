/**
 * The layout at real device widths.
 *
 * Before this work the three-pane explorer needed 1168px — app sidebar 240 +
 * category tree 224 + a usable 320 of content + detail panel 384 — and every
 * pane was `flex-shrink-0`, so a narrower viewport did not reflow, it
 * overflowed. A phone rendered a desktop layout you panned around.
 *
 * These tests assert the panes become sheets rather than columns below `lg`,
 * and that the way *in* to each one exists — a drawer with no trigger is the
 * same as no drawer.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { render } from '@/test/test-utils';
import { VIEWPORTS, resetViewport, setViewportWidth } from '@/test/viewport';
import {
  ResourceCategorySidebar,
  ResourceCategorySidebarTrigger,
} from '@/components/layout/ResourceCategorySidebar';
import { AppShell } from '@/components/layout/AppShell';
import { ResourceExplorerLayout } from '@/components/layout/ResourceExplorerLayout';
import { ResourcePageHeader } from '@/components/layout/ResourcePageHeader';
import { ResourceViewTabs } from '@/components/layout/ResourceViewTabs';
import { Sidebar } from '@/components/layout/Sidebar';

const GROUPS = [
  { category: 'Workloads', items: [{ key: 'pods', label: 'Pods' }, { key: 'deploys', label: 'Deployments' }] },
];

function renderCategorySidebar(props: Partial<Parameters<typeof ResourceCategorySidebar>[0]> = {}) {
  const onSelect = vi.fn();
  const onOpenChange = vi.fn();
  const utils = render(
    <ResourceCategorySidebar
      groups={GROUPS}
      selectedKey="pods"
      onSelect={onSelect}
      expandedCategories={['Workloads']}
      onToggleCategory={vi.fn()}
      aria-label="Resource categories"
      {...props}
    />,
  );
  return { ...utils, onSelect, onOpenChange };
}

beforeEach(() => {
  resetViewport();
});

describe('ResourceCategorySidebar', () => {
  describe('on a desktop', () => {
    it('is a column, always visible', () => {
      setViewportWidth(VIEWPORTS.laptop);
      const { container } = renderCategorySidebar();

      expect(container.querySelector('aside')).not.toBeNull();
      expect(screen.getByText('Pods')).toBeInTheDocument();
      // No dialog: it is not a drawer here.
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('stays put when an item is selected', async () => {
      setViewportWidth(VIEWPORTS.laptop);
      const onOpenChange = vi.fn();
      renderCategorySidebar({ onOpenChange });

      await userEvent.click(screen.getByText('Deployments'));

      // Nothing to dismiss — closing would be a control acting on nothing.
      expect(onOpenChange).not.toHaveBeenCalled();
    });
  });

  describe('below lg', () => {
    it.each([
      ['iPad portrait', VIEWPORTS.ipad],
      ['iPhone', VIEWPORTS.iphone],
    ])('is a drawer on %s, not a column', (_name, width) => {
      setViewportWidth(width);
      const { container } = renderCategorySidebar({ open: true });

      expect(container.querySelector('aside')).toBeNull();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('renders nothing at all while closed', () => {
      setViewportWidth(VIEWPORTS.iphone);
      renderCategorySidebar({ open: false });

      expect(screen.queryByText('Pods')).not.toBeInTheDocument();
    });

    it('closes itself once you pick something', async () => {
      setViewportWidth(VIEWPORTS.iphone);
      const onOpenChange = vi.fn();
      const { onSelect } = renderCategorySidebar({ open: true, onOpenChange });

      await userEvent.click(screen.getByText('Deployments'));

      expect(onSelect).toHaveBeenCalledWith('deploys');
      // You came here to change what you are looking at; leaving the drawer up
      // would cover the thing you just asked for.
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it('is a labelled dialog, so a screen reader announces what opened', () => {
      setViewportWidth(VIEWPORTS.iphone);
      renderCategorySidebar({ open: true });

      expect(
        screen.getByRole('dialog', { name: 'Resource categories' }),
      ).toBeInTheDocument();
    });
  });
});

describe('ResourceCategorySidebarTrigger', () => {
  it('is absent on a desktop, where the sidebar is already on screen', () => {
    setViewportWidth(VIEWPORTS.laptop);
    render(<ResourceCategorySidebarTrigger onClick={vi.fn()} label="Resources" />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it.each([
    ['iPad portrait', VIEWPORTS.ipad],
    ['iPhone', VIEWPORTS.iphone],
  ])('is present on %s — a drawer with no way in is no drawer', (_name, width) => {
    setViewportWidth(width);
    render(<ResourceCategorySidebarTrigger onClick={vi.fn()} label="Resources" />);

    expect(screen.getByRole('button', { name: /open resources/i })).toBeInTheDocument();
  });

  it('opens the drawer', async () => {
    setViewportWidth(VIEWPORTS.iphone);
    const onClick = vi.fn();
    render(<ResourceCategorySidebarTrigger onClick={onClick} label="Resources" />);

    await userEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalled();
  });
});

describe('ResourceExplorerLayout.DetailPanel', () => {
  it('is a column on a desktop', () => {
    setViewportWidth(VIEWPORTS.laptop);
    const { container } = render(
      <ResourceExplorerLayout.DetailPanel open>
        <p>pod-abc123</p>
      </ResourceExplorerLayout.DetailPanel>,
    );

    expect(screen.getByText('pod-abc123')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(container.querySelector('.w-96')).not.toBeNull();
  });

  it('is a bottom sheet below lg', () => {
    setViewportWidth(VIEWPORTS.ipad);
    render(
      <ResourceExplorerLayout.DetailPanel open label="Resource details">
        <p>pod-abc123</p>
      </ResourceExplorerLayout.DetailPanel>,
    );

    expect(screen.getByRole('dialog', { name: 'Resource details' })).toBeInTheDocument();
    expect(screen.getByText('pod-abc123')).toBeInTheDocument();
  });

  it('renders nothing when closed, at either size', () => {
    setViewportWidth(VIEWPORTS.laptop);
    const { unmount } = render(
      <ResourceExplorerLayout.DetailPanel open={false}>
        <p>pod-abc123</p>
      </ResourceExplorerLayout.DetailPanel>,
    );
    expect(screen.queryByText('pod-abc123')).not.toBeInTheDocument();
    unmount();

    setViewportWidth(VIEWPORTS.iphone);
    render(
      <ResourceExplorerLayout.DetailPanel open={false}>
        <p>pod-abc123</p>
      </ResourceExplorerLayout.DetailPanel>,
    );
    expect(screen.queryByText('pod-abc123')).not.toBeInTheDocument();
  });

  it('offers a close control on a desktop when the caller can accept one', async () => {
    setViewportWidth(VIEWPORTS.laptop);
    const onOpenChange = vi.fn();
    render(
      <ResourceExplorerLayout.DetailPanel open onOpenChange={onOpenChange}>
        <p>pod-abc123</p>
      </ResourceExplorerLayout.DetailPanel>,
    );

    await userEvent.click(screen.getByRole('button', { name: /close details/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('app Sidebar', () => {
  it('is a column above md', () => {
    setViewportWidth(VIEWPORTS.ipad);
    const { container } = render(<Sidebar />);

    expect(container.querySelector('aside')).not.toBeNull();
    expect(screen.getByText('Clusters')).toBeInTheDocument();
  });

  it('is a drawer on a phone', () => {
    setViewportWidth(VIEWPORTS.iphone);
    render(<Sidebar open />);

    const dialog = screen.getByRole('dialog', { name: 'Navigation' });
    expect(within(dialog).getByText('Clusters')).toBeInTheDocument();
  });

  it('takes 240px of a 393px phone only when asked for', () => {
    setViewportWidth(VIEWPORTS.iphone);
    render(<Sidebar open={false} />);

    // Closed: not occupying more than half the screen with navigation.
    expect(screen.queryByText('Clusters')).not.toBeInTheDocument();
  });

  it('dismisses itself after you navigate', async () => {
    setViewportWidth(VIEWPORTS.iphone);
    const onOpenChange = vi.fn();
    render(<Sidebar open onOpenChange={onOpenChange} />);

    await userEvent.click(screen.getByText('BNK Health'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('does not offer the collapse rail on a phone, where there is no room', () => {
    setViewportWidth(VIEWPORTS.iphone);
    render(<Sidebar open />);

    expect(screen.queryByLabelText('Collapse sidebar')).not.toBeInTheDocument();
  });
});

describe('ResourceViewTabs', () => {
  const TABS = [
    { key: 'gateways', label: 'Gateways' },
    { key: 'listeners', label: 'Listeners' },
    { key: 'routes', label: 'Routes' },
    { key: 'backends', label: 'Backends' },
    { key: 'security', label: 'Security' },
  ];

  it('scrolls rather than squashing on a phone', () => {
    // The bug: every tab was `flex-1 min-w-0` with a truncated label, so five
    // tabs on a 393px screen shrank to ~78px each and read "Liste…". The row
    // never overflowed, so `overflow-x-auto` had nothing to scroll and the
    // labels were simply cut off with no way to reach them.
    setViewportWidth(VIEWPORTS.iphone);
    const { container } = render(
      <ResourceViewTabs active="gateways" onChange={vi.fn()} tabs={TABS} aria-label="F5 BNK category" />,
    );

    const tablist = container.querySelector('[role="tablist"]');
    expect(tablist?.className).toContain('overflow-x-auto');

    // Natural width, so the row genuinely overflows and can be scrolled.
    const tab = screen.getByRole('tab', { name: 'Listeners' });
    expect(tab.className).toContain('flex-none');
    expect(tab.className).not.toMatch(/(^|\s)flex-1/);
  });

  it('shares the width once there is enough of it', () => {
    setViewportWidth(VIEWPORTS.laptop);
    render(
      <ResourceViewTabs active="gateways" onChange={vi.fn()} tabs={TABS} aria-label="F5 BNK category" />,
    );

    // The `sm:` variants take over above 640px — the classes are present at
    // every width; the breakpoint decides which wins.
    expect(screen.getByRole('tab', { name: 'Listeners' }).className).toContain('sm:flex-1');
  });

  it('keeps every label reachable, not truncated away', () => {
    setViewportWidth(VIEWPORTS.iphone);
    render(
      <ResourceViewTabs active="gateways" onChange={vi.fn()} tabs={TABS} aria-label="F5 BNK category" />,
    );

    for (const tab of TABS) {
      expect(screen.getByRole('tab', { name: tab.label })).toBeInTheDocument();
    }
  });
});

describe('vertical space on a short viewport', () => {
  // An iPhone in landscape is 393px tall. The page header alone was taking
  // 240px of it — title 32 + subtitle 20 + gap 16 + controls 36 + padding 32,
  // plus the app header and the tab strip — leaving 153px of content that
  // could not scroll. These tests hold the height back.
  const CLUSTERS = [{ id: 1, name: 'infra' }] as never;

  function renderHeader() {
    return render(
      <ResourcePageHeader
        title="F5 BNK"
        subtitle="BIG-IP Next for Kubernetes — gateways, policies, and traffic flow"
        clusters={CLUSTERS}
        selectedClusterId={1}
        onClusterChange={vi.fn()}
      />,
    );
  }

  it('keeps the page title when there is room for it', () => {
    setViewportWidth(VIEWPORTS.laptop);
    renderHeader();

    expect(screen.getByRole('heading', { name: 'F5 BNK' })).toBeInTheDocument();
    expect(screen.getByText(/BIG-IP Next for Kubernetes/)).toBeInTheDocument();
  });

  it('drops it on a landscape phone, where the app header already says it', () => {
    setViewportWidth(VIEWPORTS.iphoneLandscape);
    renderHeader();

    expect(screen.queryByRole('heading', { name: 'F5 BNK' })).not.toBeInTheDocument();
    expect(screen.queryByText(/BIG-IP Next for Kubernetes/)).not.toBeInTheDocument();
  });

  it('still lets you pick a cluster there — chrome shrinks, controls stay', () => {
    setViewportWidth(VIEWPORTS.iphoneLandscape);
    renderHeader();

    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('spends less padding on height when height is what is scarce', () => {
    setViewportWidth(VIEWPORTS.iphoneLandscape);
    const { container } = renderHeader();
    expect(container.firstElementChild?.className).toContain('py-2');

    setViewportWidth(VIEWPORTS.laptop);
    const { container: roomy } = renderHeader();
    expect(roomy.firstElementChild?.className).toContain('py-4');
  });
});

describe('ResourceExplorerLayout.Root', () => {
  it('fills its parent rather than the viewport', () => {
    // It renders inside AppShell's <main>, which already starts below the app
    // header and adds padding. `h-screen` overflowed that by ~88px and sized
    // the Body's scroller against the full viewport, so the content measured
    // itself as fitting and never scrolled while its tail sat off-screen.
    const { container } = render(
      <ResourceExplorerLayout>
        <p>content</p>
      </ResourceExplorerLayout>,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root.className).not.toContain('h-screen');
    expect(root.className).toContain('h-full');
    // Without min-h-0 the flex column is floored by its content's height and
    // the inner overflow-hidden Body never gets a bounded height to scroll in.
    expect(root.className).toContain('min-h-0');
  });

  it('gives the routed page a height to fill', () => {
    // Without this, a page's own `h-full` resolves against `height: auto` and
    // is inert: React Flow measured 1152x0 on the CNF topology view — three
    // nodes present in the DOM and none of them on screen — and the resource
    // table's sticky header never stuck. Asserted on the class because the
    // failure is a computed height jsdom does not compute.
    // AppShell scrolls <main> to the top on navigation; jsdom has no
    // Element.scrollTo.
    if (!Element.prototype.scrollTo) {
      Element.prototype.scrollTo = () => {};
    }
    render(<AppShell />);
    const main = document.querySelector('#main-content');
    const page = main?.querySelector('.motion-safe\\:animate-page-enter');
    expect(page?.className).toContain('h-full');
    expect(page?.className).toContain('min-h-0');
  });

});
