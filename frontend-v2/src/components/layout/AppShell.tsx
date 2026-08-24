import { useState, Suspense } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

import { CommandPalette } from '@/components/CommandPalette';
import { KeyboardShortcutsModal } from '@/components/KeyboardShortcutsModal';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { useKeyboardShortcuts, useNavigationShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useRouteAnnouncer, useScrollToTop } from '@/hooks/useAccessibility';
import { cn } from '@/lib/utils';
import { useIsShort } from '@/hooks/useMediaQuery';
import { useConnectivitySession } from '@/hooks/useConnectivity';
import { Loader2 } from 'lucide-react';

export function AppShell() {
  const navigate = useNavigate();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsModalOpen, setShortcutsModalOpen] = useState(false);
  // Below `md` the nav is a drawer; the Header owns the button that opens it.
  const [navOpen, setNavOpen] = useState(false);

  // Global keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: 'k',
      meta: true,
      action: () => setCommandPaletteOpen(true),
      description: 'Open command palette',
    },
    {
      key: '/',
      meta: true,
      action: () => setShortcutsModalOpen((prev) => !prev),
      description: 'Show keyboard shortcuts',
    },
    {
      key: '?',
      shift: true,
      action: () => setShortcutsModalOpen((prev) => !prev),
      description: 'Show keyboard shortcuts',
    },
    {
      key: 'n',
      meta: true,
      action: () => navigate('/'),
      description: 'Go to Dashboard',
    },
  ]);

  // Navigation shortcuts
  useNavigationShortcuts();

  // Accessibility: announce route changes to screen readers & scroll to top
  useRouteAnnouncer();
  useScrollToTop();

  // Single SSE subscription for the whole authenticated session.
  useConnectivitySession();

  const short = useIsShort();

  return (
    <div className="flex h-screen bg-background">
      {/* B5: Skip navigation link for keyboard/screen reader users */}
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-background focus:text-foreground focus:border focus:rounded-md focus:top-2 focus:left-2">
        Skip to main content
      </a>
      <Sidebar open={navOpen} onOpenChange={setNavOpen} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header onOpenNav={() => setNavOpen(true)} />
        {/* Tighter padding on a phone: 24px each side of a 393px screen is 12%
            of the width spent on margin. */}
        <main
          id="main-content"
          className={cn(
            // `min-h-0` lets this flex item actually shrink to the viewport
            // instead of being floored by its content's height.
            'flex-1 min-h-0 overflow-y-auto',
            // A landscape phone is 393px tall; 32px of vertical padding is 8%
            // of the page spent on margin.
            short ? 'px-4 py-2' : 'p-4 md:p-6',
          )}
        >
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-full">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            }
          >
            {/* h-full, not just the animation class. Without a height here
                the page's own `h-full` resolves against `height: auto` and is
                inert — every layout that fills its parent silently collapses.
                It cost the CNF topology graph its canvas (React Flow measured
                1152x0, nodes present and invisible) and the resource table its
                sticky header. `min-h-0` so a filled child can still scroll
                inside rather than pushing this taller. */}
            <div className="h-full min-h-0 motion-safe:animate-page-enter">
              <Outlet />
            </div>
          </Suspense>
        </main>
      </div>

      {/* Command Palette */}
      <CommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
      />

      {/* Keyboard Shortcuts Modal */}
      <KeyboardShortcutsModal
        open={shortcutsModalOpen}
        onOpenChange={setShortcutsModalOpen}
      />

      {/* Theme Toggle */}
      <ThemeToggle />
    </div>
  );
}
