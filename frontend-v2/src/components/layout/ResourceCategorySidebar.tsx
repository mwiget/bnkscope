/**
 * ResourceCategorySidebar — the single in-page category-navigation idiom shared
 * by the three resource-explorer pages (Kubernetes, F5 BNK, CNF).
 *
 * D-020 Option A: a *quiet* sidebar. It recedes so the content + detail panel
 * are the visual focus. No card background, no tinted/bordered selection — the
 * selected item is just `text-primary font-medium`. Category headers are small
 * uppercase eyebrow labels. Per-item decorations (status dot, count, tag) are
 * optional so each page maps its own data onto one consistent shape.
 *
 * **Below `lg` it is a drawer.** As a column it is 224px of a viewport that may
 * only be 393px wide, and it sat next to a detail panel and a content area that
 * were all `flex-shrink-0` — so the page simply overflowed and you panned a
 * desktop layout around a phone. Below `lg` the same tree renders inside a
 * sheet, opened by `<ResourceCategorySidebarTrigger>`, and selecting an item
 * closes it: on a small screen you came here to change what you are looking at,
 * not to keep the tree on screen.
 */

import { type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { useIsCompact } from '@/hooks/useMediaQuery';
import { ChevronDown, ChevronRight, PanelLeft } from 'lucide-react';

export interface ResourceCategoryItem {
  key: string;
  label: string;
  icon?: React.ElementType;
  /** Small status dot color class, e.g. 'bg-success' / 'bg-destructive'. */
  dotColor?: string;
  /** Numeric count rendered quietly on the right. */
  count?: number;
  /** Render a loading shimmer instead of a count. */
  countLoading?: boolean;
  /** Small text tag, e.g. 'curated'. */
  tag?: string;
  /** Native title/tooltip. */
  title?: string;
}

export interface ResourceCategoryGroup {
  category: string;
  icon?: React.ElementType;
  items: ResourceCategoryItem[];
  /** Optional count shown faintly in the category header. */
  count?: number;
}

interface ResourceCategorySidebarProps {
  groups: ResourceCategoryGroup[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  expandedCategories: string[];
  onToggleCategory: (category: string) => void;
  /** Optional content rendered above the category list (e.g. a hint card). */
  header?: ReactNode;
  /**
   * Render items as one flat list without the collapsible eyebrow group
   * headers. Used when a parent tab already names the active category
   * (F5 BNK), so the group header would be redundant. expandedCategories /
   * onToggleCategory are ignored in this mode.
   */
  hideGroupHeaders?: boolean;
  /** Tailwind width class when shown as a column. Default: 'w-52'. */
  width?: string;
  className?: string;
  'aria-label'?: string;
  /**
   * Below `lg`, whether the drawer is open. Above it the sidebar is always
   * visible and these are ignored — pair with
   * `<ResourceCategorySidebarTrigger>`, which only renders where it applies.
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function ResourceCategorySidebar({
  groups,
  selectedKey,
  onSelect,
  expandedCategories,
  onToggleCategory,
  header,
  hideGroupHeaders = false,
  width = 'w-52',
  className,
  'aria-label': ariaLabel = 'Resource categories',
  open = false,
  onOpenChange,
}: ResourceCategorySidebarProps) {
  const compact = useIsCompact();

  const renderItem = (item: ResourceCategoryItem) => {
    const ItemIcon = item.icon;
    const isSelected = selectedKey === item.key;

    return (
      <button
        key={item.key}
        onClick={() => {
          onSelect(item.key);
          // In the drawer, picking an item is the end of the interaction —
          // leaving it open would cover what you just asked to see.
          if (compact) onOpenChange?.(false);
        }}
        title={item.title}
        className={cn(
          'flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors',
          isSelected
            ? 'font-medium text-primary'
            : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground',
        )}
      >
        {ItemIcon && <ItemIcon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
        <span className="flex-1 truncate text-left">{item.label}</span>
        {item.dotColor && (
          <span
            className={cn('h-2 w-2 flex-shrink-0 rounded-full', item.dotColor)}
            aria-hidden="true"
          />
        )}
        {item.tag && (
          <Badge variant="outline" className="h-4 px-1 text-[9px]">
            {item.tag}
          </Badge>
        )}
        {item.count !== undefined ? (
          <span className="min-w-[1.5rem] text-right text-[10px] tabular-nums text-muted-foreground/70">
            {item.count}
          </span>
        ) : item.countLoading ? (
          <span className="h-1 w-6 animate-pulse rounded bg-muted-foreground/20" />
        ) : null}
      </button>
    );
  };

  const body = hideGroupHeaders ? (
    <>
      {header && <div className="p-3 pb-0">{header}</div>}
      <nav className="space-y-0.5 p-3">
        {groups.flatMap((group) => group.items).map(renderItem)}
      </nav>
    </>
  ) : (
    <>
      {header && <div className="p-3 pb-0">{header}</div>}

      <nav className="space-y-3 p-3">
        {groups.map((group) => {
          const expanded = expandedCategories.includes(group.category);
          const GroupIcon = group.icon;
          const slug = group.category.toLowerCase().replace(/\s+/g, '-');

          return (
            <div key={group.category}>
              <button
                onClick={() => onToggleCategory(group.category)}
                aria-expanded={expanded}
                aria-controls={`rcs-group-${slug}`}
                className="flex w-full items-center gap-1.5 px-1 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70 transition-colors hover:text-muted-foreground"
              >
                {expanded ? (
                  <ChevronDown className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                )}
                {GroupIcon && <GroupIcon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
                <span className="flex-1 truncate text-left">{group.category}</span>
                {group.count !== undefined && (
                  <span className="text-[10px] font-normal tabular-nums">{group.count}</span>
                )}
              </button>

              {expanded && (
                <div id={`rcs-group-${slug}`} className="mt-1 space-y-0.5">
                  {group.items.map(renderItem)}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </>
  );

  if (compact) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="left" className="w-[85vw] max-w-xs overflow-y-auto p-0">
          <VisuallyHidden>
            <SheetTitle>{ariaLabel}</SheetTitle>
          </VisuallyHidden>
          <nav aria-label={ariaLabel}>{body}</nav>
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <aside
      aria-label={ariaLabel}
      className={cn(
        width,
        'flex-shrink-0 overflow-y-auto border-r border-border bg-background',
        className,
      )}
    >
      {body}
    </aside>
  );
}

/**
 * Opens the category drawer. Renders only below `lg` — above it the sidebar is
 * a visible column and a toggle for it would be a control that does nothing.
 *
 * `label` names what the drawer contains ("Resources", "Components"), because
 * on a narrow screen it is the only clue to what is behind it.
 */
export function ResourceCategorySidebarTrigger({
  onClick,
  label = 'Categories',
}: {
  onClick: () => void;
  label?: string;
}) {
  const compact = useIsCompact();
  if (!compact) return null;

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-9 gap-1.5"
      onClick={onClick}
      aria-label={`Open ${label.toLowerCase()}`}
    >
      <PanelLeft className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
    </Button>
  );
}
