/**
 * ResourceExplorerLayout — sidebar + content + detail panel, at any width.
 *
 * Used by the Clusters, BNK Health and CNF pages.
 *
 *   - ResourceExplorerLayout        root: full-height flex column
 *   - ResourceExplorerLayout.Header top bar
 *   - ResourceExplorerLayout.Sidebar   left filter tree
 *   - ResourceExplorerLayout.Content   centre, scrollable
 *   - ResourceExplorerLayout.DetailPanel  right panel
 *   - SidebarFilterItem / SidebarSection  sidebar building blocks
 *
 * **Below `lg` the detail panel becomes a bottom sheet.** Side by side the
 * panes need 240 + 224 + 320 + 384 = 1168px before anything useful is on
 * screen, so even a landscape iPad is 144px short. It becomes a *sheet* rather
 * than a hidden element because the content is the same either way: rendering
 * both trees and hiding one with `lg:hidden` would mount two copies of it.
 *
 * The left filter tree gets the same treatment in `ResourceCategorySidebar`,
 * which is what the pages actually render.
 */

import { type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useThemeClasses } from '@/context/ThemeContext';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { useIsCompact } from '@/hooks/useMediaQuery';

// ============================================================================
// Root
// ============================================================================

interface ResourceExplorerLayoutProps {
  children: ReactNode;
  className?: string;
  /** data-onboarding attribute for walkthrough targets */
  'data-onboarding'?: string;
}

function Root({ children, className, ...props }: ResourceExplorerLayoutProps) {
  return (
    <div
      // `h-full`, not `h-screen`. This renders *inside* AppShell's <main>,
      // which already starts below the app header and carries its own padding,
      // so a full-viewport height overflowed the main by ~88px — and, worse,
      // sized the Body's inner scroller against the whole viewport, so it
      // measured itself as fitting and never scrolled while its last 88px sat
      // off-screen. On a 393px-tall landscape phone that is 22% of the page
      // you could neither see nor reach.
      className={cn('h-full min-h-0 flex flex-col bg-background', className)}
      {...props}
    >
      {children}
    </div>
  );
}

// ============================================================================
// Header
// ============================================================================

interface HeaderProps {
  children: ReactNode;
  className?: string;
}

function Header({ children, className }: HeaderProps) {
  const { borderDefault } = useThemeClasses();

  return (
    <div className={cn('flex-shrink-0 border-b', borderDefault, className)}>
      {children}
    </div>
  );
}

// ============================================================================
// Body — flex row container for sidebar + content + detail panel
// ============================================================================

interface BodyProps {
  children: ReactNode;
  className?: string;
}

function Body({ children, className }: BodyProps) {
  return (
    <div className={cn('flex-1 flex overflow-hidden', className)}>
      {children}
    </div>
  );
}

// ============================================================================
// Sidebar
// ============================================================================

interface SidebarProps {
  children: ReactNode;
  /** Tailwind width class. Default: 'w-56' */
  width?: string;
  className?: string;
}

function Sidebar({ children, width = 'w-56', className }: SidebarProps) {
  const { borderDefault } = useThemeClasses();

  return (
    <div
      className={cn(
        width,
        'flex-shrink-0 border-r overflow-y-auto bg-muted/30',
        borderDefault,
        className,
      )}
    >
      {children}
    </div>
  );
}


// ============================================================================
// Content
// ============================================================================

interface ContentProps {
  children: ReactNode;
  className?: string;
}

function Content({ children, className }: ContentProps) {
  return (
    <div className={cn('flex-1 overflow-auto', className)}>
      {children}
    </div>
  );
}

// ============================================================================
// DetailPanel
// ============================================================================

interface DetailPanelProps {
  children: ReactNode;
  /** Whether the panel is open. Below `lg` this drives a bottom sheet. */
  open: boolean;
  /** Tailwind width class when shown as a column. Default: 'w-96' */
  width?: string;
  className?: string;
  /** Enables a close control (and sheet dismissal below `lg`). */
  onOpenChange?: (open: boolean) => void;
  /** Accessible name for the sheet. */
  label?: string;
}

function DetailPanel({
  children,
  open,
  width = 'w-96',
  className,
  onOpenChange,
  label = 'Details',
}: DetailPanelProps) {
  const { borderDefault } = useThemeClasses();
  const compact = useIsCompact();

  if (compact) {
    // A bottom sheet rather than a side one: detail content is tall and narrow
    // — labels, conditions, YAML — and on a phone the useful axis is vertical.
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="bottom" className="h-[85vh] overflow-y-auto p-0">
          <VisuallyHidden>
            <SheetTitle>{label}</SheetTitle>
          </VisuallyHidden>
          {children}
        </SheetContent>
      </Sheet>
    );
  }

  if (!open) return null;

  return (
    <div
      className={cn(
        width,
        'flex-shrink-0 border-l overflow-y-auto bg-card',
        borderDefault,
        className,
      )}
    >
      {/* Above `lg` the panel is a column with no scrim to dismiss it, so it
          needs its own close affordance when the caller can accept one. */}
      {onOpenChange && (
        <div className="flex justify-end p-2 pb-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label="Close details"
            onClick={() => onOpenChange(false)}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}
      {children}
    </div>
  );
}

// ============================================================================
// SidebarSection — titled group within the sidebar
// ============================================================================

interface SidebarSectionProps {
  title: string;
  children: ReactNode;
  className?: string;
}

function SidebarSection({ title, children, className }: SidebarSectionProps) {
  return (
    <div className={cn('mt-4', className)}>
      <div className="text-xs font-medium uppercase tracking-wider px-3 mb-2 text-muted-foreground/70">
        {title}
      </div>
      {children}
    </div>
  );
}

// ============================================================================
// SidebarFilterItem — reusable filter button
// ============================================================================

interface SidebarFilterItemProps {
  icon: React.ElementType;
  label: string;
  count?: number;
  selected: boolean;
  onClick: () => void;
  /** Icon color class when not selected. Default: 'text-current' */
  iconColor?: string;
  className?: string;
}

function SidebarFilterItem({
  icon: Icon,
  label,
  count,
  selected,
  onClick,
  iconColor,
  className,
}: SidebarFilterItemProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors mb-0.5 border-l-2',
        selected
          ? 'bg-primary/10 text-primary font-medium border-l-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50 border-l-transparent',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className={cn('h-4 w-4', selected ? 'text-primary' : iconColor)} />
        <span>{label}</span>
      </div>
      {count !== undefined && (
        <Badge variant={selected ? 'outline' : 'secondary'} className="text-xs">
          {count}
        </Badge>
      )}
    </button>
  );
}

// ============================================================================
// Compound Export
// ============================================================================

/**
 * ResourceExplorerLayout — compound component for master-detail pages.
 *
 * @example
 * ```tsx
 * <ResourceExplorerLayout data-onboarding="k8s-page">
 *   <ResourceExplorerLayout.Header>
 *     <ResourcePageHeader ... />
 *   </ResourceExplorerLayout.Header>
 *   <ResourceExplorerLayout.Body>
 *     <ResourceExplorerLayout.Sidebar width="w-56">
 *       <SidebarFilterItem icon={Layers} label="All" count={42} selected onClick={...} />
 *     </ResourceExplorerLayout.Sidebar>
 *     <ResourceExplorerLayout.Content>
 *       <ResourceTable ... />
 *     </ResourceExplorerLayout.Content>
 *     <ResourceExplorerLayout.DetailPanel open={!!selected} width="w-96">
 *       <DetailView ... />
 *     </ResourceExplorerLayout.DetailPanel>
 *   </ResourceExplorerLayout.Body>
 * </ResourceExplorerLayout>
 * ```
 */
const ResourceExplorerLayout = Object.assign(Root, {
  Header,
  Body,
  Sidebar,
  Content,
  DetailPanel,
  SidebarSection,
  SidebarFilterItem,
});

export { ResourceExplorerLayout, SidebarFilterItem, SidebarSection };
export type { SidebarFilterItemProps, SidebarSectionProps, DetailPanelProps };
