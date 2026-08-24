/**
 * bnkscope navigation.
 *
 * Five lenses, flat. bnk-forge had 16 entries across five collapsible sections
 * because it had five jobs; bnkscope has one — find out what is wrong with a
 * BNK cluster — and every entry is a different lens on that. Sections and
 * per-section collapse state went with the entries they organised.
 *
 * Utility pages (System, MCP) sit in the footer rather than the main list.
 * They are reachable, because backup/restore has to be, but they are not what
 * the tool is for and should not compete with the lenses above.
 *
 * TMM Live arrived in Phase 7 — tmmscope's Grafana dashboard, embedded.
 *
 * **Below `md` it is a drawer.** 240px of a 393px phone is more than half the
 * screen given to navigation; the same nav renders in a sheet opened from the
 * header, and tapping an entry closes it.
 */
import { NavLink, Link, useMatch, useResolvedPath } from 'react-router-dom';
import * as React from 'react';
import { useState } from 'react';
import {
  Activity,
  Bot,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Layers,
  Radio,
  ScrollText,
  Server,
  Shield,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { BnkscopeMark } from '@/components/branding/BnkscopeMark';
import { useIsHandheld } from '@/hooks/useMediaQuery';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useAllClusters } from '@/hooks/useK8s';

interface NavItem {
  name: string;
  href: string;
  icon: React.ElementType;
  /** Says what the lens is *for*. Carries the whole meaning when collapsed. */
  hint: string;
  showCount?: 'clusters';
}

const NAV: NavItem[] = [
  {
    name: 'Clusters',
    href: '/kubernetes',
    icon: Boxes,
    hint: 'Every cluster bnkscope found, and every resource on them',
    showCount: 'clusters',
  },
  {
    name: 'BNK Health',
    href: '/bnk',
    icon: Shield,
    hint: 'TMM, gateways, traffic flow, and the tmctl/configview diagnostics',
  },
  {
    name: 'TMM Live',
    href: '/tmm-live',
    icon: Radio,
    hint: 'Real-time TMM telemetry, streamed by tmmscope into Grafana',
  },
  {
    name: 'Logs',
    href: '/logs',
    icon: ScrollText,
    hint: 'Search every cluster\'s logs — 24h, same window as the metrics',
  },
  {
    name: 'CNF Resources',
    href: '/cnf',
    icon: Layers,
    hint: 'Read-only browser for F5 custom resources and their conditions',
  },
  {
    name: 'AI Gateway',
    href: '/observability/ai-gateway',
    icon: Activity,
    hint: 'LLM request analytics and logs',
  },
];

const UTILITY_NAV: NavItem[] = [
  { name: 'System', href: '/system', icon: Server, hint: 'Backup, alerts, appearance' },
  { name: 'MCP', href: '/mcp-server', icon: Bot, hint: 'Read-only MCP tools for an AI agent' },
];

interface SidebarProps {
  /** Below `md`, whether the nav drawer is open. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function Sidebar({ open = false, onOpenChange }: SidebarProps = {}) {
  const [collapsed, setCollapsed] = useState(false);
  const handheld = useIsHandheld();
  const { data: clustersData } = useAllClusters();
  const clusterCount = clustersData?.count ?? 0;

  // In the drawer there is no room for a collapsed rail, and no reason for one.
  const isCollapsed = handheld ? false : collapsed;

  const renderItem = (item: NavItem) => {
    const count = item.showCount === 'clusters' ? clusterCount : null;
    const link = (
      <SidebarNavItem
        key={item.name}
        item={item}
        collapsed={isCollapsed}
        count={count}
        onNavigate={handheld ? () => onOpenChange?.(false) : undefined}
      />
    );

    if (isCollapsed) {
      return (
        <Tooltip key={item.name} delayDuration={0}>
          <TooltipTrigger asChild>{link}</TooltipTrigger>
          <TooltipContent side="right">
            <p className="font-medium">{item.name}</p>
            <p className="text-xs text-muted-foreground">{item.hint}</p>
          </TooltipContent>
        </Tooltip>
      );
    }
    return link;
  };

  const aside = (
    <TooltipProvider>
      <aside
        aria-label="Application sidebar"
        className={cn(
          'border-border bg-card flex flex-col transition-all duration-300',
          // In the drawer the sheet owns the height and the border.
          handheld ? 'h-full w-full' : cn('h-screen border-r', isCollapsed ? 'w-16' : 'w-60'),
        )}
      >
        {/* The 34px slot and the one-shot beam sweep are the mark's documented
            placement — see scripts/bnkscope-icon/README.md. */}
        <div
          className={cn(
            'border-b border-border flex items-center',
            isCollapsed ? 'justify-center py-3' : 'px-4 py-4',
          )}
        >
          <Link to="/" className="flex items-center gap-2.5" aria-label="bnkscope home">
            <BnkscopeMark size={34} animate />
            {!isCollapsed && (
              <span className="text-lg font-semibold tracking-tight text-foreground">
                bnkscope
              </span>
            )}
          </Link>
        </div>

        <nav
          className={cn('flex-1 overflow-y-auto', isCollapsed ? 'py-3 px-1' : 'p-3')}
          aria-label="Main navigation"
        >
          <div className={cn('space-y-1', isCollapsed && 'flex flex-col items-center')}>
            {NAV.map(renderItem)}
          </div>

          <div
            className={cn(
              'mt-6 space-y-1 border-t border-border pt-4',
              isCollapsed && 'flex flex-col items-center',
            )}
          >
            {UTILITY_NAV.map(renderItem)}
          </div>
        </nav>

        <div className="p-3 border-t border-border">
          {handheld ? (
            // In the drawer there is no rail to collapse to, so the toggle
            // would be a control that does nothing. The version still earns
            // its place — it is the first thing asked for in a bug report.
            <span className="text-xs text-muted-foreground">v{__APP_VERSION__}</span>
          ) : !isCollapsed ? (
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>v{__APP_VERSION__}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => setCollapsed(true)}
                aria-label="Collapse sidebar"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              className="w-full"
              onClick={() => setCollapsed(false)}
              aria-label="Expand sidebar"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>
      </aside>
    </TooltipProvider>
  );

  if (handheld) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="left" className="w-[80vw] max-w-[16rem] p-0">
          <VisuallyHidden>
            <SheetTitle>Navigation</SheetTitle>
          </VisuallyHidden>
          {aside}
        </SheetContent>
      </Sheet>
    );
  }

  return aside;
}

// =====================================================================
// SidebarNavItem
// =====================================================================
//
// One row of the nav. Separate component so useMatch / useResolvedPath sit at
// the top level (Rules of Hooks) and NavLink gets a STRING className.
//
// Why the string matters: in collapsed mode the link is wrapped in
// <TooltipTrigger asChild>, and Radix's Slot merges props by string
// concatenation. A function className gets toString()-ed into the class
// attribute, the browser parses every word of the function source as a
// Tailwind class, and the colours and hover state come out wrong.

interface SidebarNavItemProps {
  item: NavItem;
  collapsed: boolean;
  count: number | null;
  /** Called after navigating — dismisses the drawer on a handheld. */
  onNavigate?: () => void;
}

const SidebarNavItem = React.forwardRef<HTMLAnchorElement, SidebarNavItemProps>(
  ({ item, collapsed, count, onNavigate, ...rest }, ref) => {
    const resolved = useResolvedPath(item.href);
    const match = useMatch({ path: resolved.pathname, end: item.href === '/' });
    const isActive = !!match;

    const linkClassName = cn(
      'flex items-center py-2.5 rounded-lg text-sm font-medium transition-all relative',
      collapsed ? 'w-10 mx-auto justify-center' : 'gap-3 px-3',
      isActive
        ? 'bg-primary/10 text-primary font-medium'
        : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
    );

    return (
      <NavLink
        to={item.href}
        end={item.href === '/'}
        className={linkClassName}
        title={collapsed ? undefined : item.hint}
        onClick={onNavigate}
        ref={ref}
        {...rest}
      >
        <item.icon className="h-4 w-4 flex-shrink-0" />
        <span className={cn('flex-1 text-left', collapsed && 'sr-only')}>{item.name}</span>
        {!collapsed && count !== null && count > 0 && (
          <span
            className={cn(
              'px-1.5 py-0.5 text-xs rounded-full',
              isActive ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground',
            )}
          >
            {count}
          </span>
        )}
      </NavLink>
    );
  },
);
SidebarNavItem.displayName = 'SidebarNavItem';
