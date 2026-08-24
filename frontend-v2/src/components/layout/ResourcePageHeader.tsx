import React, { useRef } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, RefreshCw } from 'lucide-react';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useIsShort } from '@/hooks/useMediaQuery';

interface Cluster {
  id: number;
  name: string;
  status?: string;
}

interface ResourcePageHeaderProps {
  title?: string;
  subtitle?: React.ReactNode;
  clusters: Cluster[];
  selectedClusterId: number | null;
  onClusterChange: (id: number) => void;
  // Namespace and search are optional: not every page that needs a cluster
  // picker also filters by namespace or by text. TMM Live embeds a dashboard
  // that carries its own controls, so it passes neither, and rendering an
  // inert namespace dropdown next to it would be furniture.
  /** Rendered first in the control row — the category-drawer trigger. */
  leading?: React.ReactNode;
  namespaces?: { name: string }[] | string[];
  selectedNamespace?: string;
  onNamespaceChange?: (ns: string) => void;
  searchQuery?: string;
  onSearchChange?: (query: string) => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  children?: React.ReactNode;
  className?: string;
}

export function ResourcePageHeader({
  title,
  subtitle,
  leading,
  clusters,
  selectedClusterId,
  onClusterChange,
  namespaces,
  selectedNamespace,
  onNamespaceChange,
  searchQuery,
  onSearchChange,
  onRefresh,
  isRefreshing,
  children,
  className,
}: ResourcePageHeaderProps) {
  const searchInputRef = useRef<HTMLInputElement>(null);

  useKeyboardShortcuts([
    {
      key: '/',
      action: (e) => {
        e.preventDefault();
        searchInputRef.current?.focus();
      },
      allowInInput: true,
    },
  ]);

  // Normalize namespaces to strings
  const namespaceList = (namespaces ?? []).map(ns => typeof ns === 'string' ? ns : ns.name);
  const showNamespaces = !!onNamespaceChange;
  const showSearch = !!onSearchChange;
  const short = useIsShort();

  return (
    <div className={cn(
      'sticky top-0 z-20 flex flex-col border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/75',
      // Vertical space is the scarce resource on a short viewport: an iPhone in
      // landscape is 393px tall and this header was taking 240px of it.
      short ? 'gap-2 px-4 py-2' : 'gap-4 px-6 py-4',
      className
    )}>
      {/* Page title. Dropped on a short viewport — the app header already
          names the page, so h1 + subtitle is 68px of duplication in the one
          place where 68px is most of what the content has left. */}
      {title && !short && (
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
          {subtitle && (
            <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
          )}
        </div>
      )}

      {/* Selector + search + actions row.
          `flex-wrap` was already here, but every child had a fixed pixel width,
          so it wrapped into a tall stack of full-width controls rather than
          fitting. The widths are now capped by the viewport. */}
      <div className="flex items-center gap-2 md:gap-3 flex-wrap">
        {/* Opens the page's category drawer. Renders below `lg` only. */}
        {leading}

        {/* Cluster Selector */}
        <Select
          value={selectedClusterId?.toString() || ''}
          onValueChange={(value) => onClusterChange(parseInt(value))}
          disabled={!clusters.length}
        >
          <SelectTrigger className="h-9 w-[46vw] max-w-[200px] sm:w-[200px]">
            <SelectValue placeholder="Select Cluster" />
          </SelectTrigger>
          <SelectContent>
            {clusters.length === 0 ? (
               <div className="p-2 text-xs text-muted-foreground text-center">No clusters found</div>
            ) : (
              clusters.map((cluster) => (
                <SelectItem key={cluster.id} value={cluster.id.toString()}>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={cn(
                      'h-2 w-2 rounded-full flex-shrink-0',
                      cluster.status === 'active' ? 'bg-success' : 'bg-muted-foreground'
                    )} />
                    <span className="truncate">{cluster.name}</span>
                  </div>
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>

        {/* The separator only reads as one when the two selects are on the
            same line, which below `sm` they are not. */}
        {showNamespaces && (
          <span className="hidden text-lg font-light text-muted-foreground/50 sm:inline">/</span>
        )}

        {/* Namespace Selector */}
        {showNamespaces && (
        <Select
          value={selectedNamespace}
          onValueChange={onNamespaceChange}
          disabled={!selectedClusterId}
        >
          <SelectTrigger className="h-9 w-[46vw] max-w-[180px] font-medium sm:w-[180px]">
             <span className="truncate">
                {selectedNamespace === 'all' ? 'All Namespaces' : selectedNamespace}
             </span>
          </SelectTrigger>
          <SelectContent>
            {/* "All Namespaces" removed from the dropdown intentionally — it's
                an expensive cluster-wide fetch and should be opt-in via the
                explicit "Load all namespaces" button in the K8s sidebar. The
                currently-active "all" state is still displayed if set. */}
            {selectedNamespace === 'all' && (
              <SelectItem value="all" className="font-semibold text-warning">
                All Namespaces (cluster-wide)
              </SelectItem>
            )}
            {namespaceList.map((ns) => (
              <SelectItem key={ns} value={ns}>
                {ns}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        )}

        {/* Search Input */}
        {showSearch ? (
        <div className="relative w-full min-w-0 flex-1 sm:w-auto sm:min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            ref={searchInputRef}
            placeholder="Search... (/)"
            aria-label="Search resources"
            value={searchQuery}
            onChange={(e) => onSearchChange?.(e.target.value)}
            className="pl-9 h-9 transition-all focus:w-full"
          />
        </div>
        ) : (
          <div className="flex-1" />
        )}

        {/* Actions Area */}
        <div className="flex items-center gap-2">
          {children}

          {onRefresh && (
            <Button
              variant="outline"
              size="sm"
              className="h-9 w-9 p-0"
              onClick={onRefresh}
              disabled={isRefreshing || !selectedClusterId}
              title="Refresh Resources"
              aria-label="Refresh resources"
            >
              <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
