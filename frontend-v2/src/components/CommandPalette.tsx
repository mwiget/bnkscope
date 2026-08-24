import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandShortcut,
} from '@/components/ui/command';
import {
    Activity,
    Bot,
    Boxes,
    Layers,
    LayoutDashboard,
    Radio,
    ScrollText,
    Server,
    Shield,
} from 'lucide-react';
import { NAV_SHORTCUTS } from '@/hooks/useKeyboardShortcuts';

interface CommandPaletteProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
    const navigate = useNavigate();
    const [search, setSearch] = useState('');

    // Both the destinations and their key hints come from NAV_SHORTCUTS, the
    // same table the G-sequences and the shortcuts modal read. Hand-maintained
    // here, this list drifted: two of its six entries pointed at /fleet, a
    // route deleted with the pipeline, and it was missing five of the nine
    // pages. Its own test asserted "Fleet Overview" was present, so the suite
    // certified the bug.
    const ICONS: Record<string, React.ElementType> = {
        '/': LayoutDashboard,
        '/kubernetes': Boxes,
        '/bnk': Shield,
        '/tmm-live': Radio,
        '/logs': ScrollText,
        '/cnf': Layers,
        '/observability/ai-gateway': Activity,
        '/system': Server,
        '/mcp-server': Bot,
    };

    const navigationItems = NAV_SHORTCUTS.map((nav) => ({
        id: nav.path,
        label: nav.label,
        icon: ICONS[nav.path] ?? LayoutDashboard,
        shortcut: `G ${nav.key.toUpperCase()}`,
        action: () => navigate(nav.path),
    }));

    const handleSelect = (action: () => void) => {
        action();
        onOpenChange(false);
        setSearch('');
    };

    return (
        <CommandDialog open={open} onOpenChange={onOpenChange}>
            <CommandInput
                placeholder="Type a command or search..."
                value={search}
                onValueChange={setSearch}
            />
            <CommandList>
                <CommandEmpty>No results found.</CommandEmpty>


                {/* Navigation */}
                <CommandGroup heading="Navigation">
                    {navigationItems.map((item) => {
                        const Icon = item.icon;
                        return (
                            <CommandItem
                                key={item.id}
                                onSelect={() => handleSelect(item.action)}
                            >
                                <Icon className="mr-2 h-4 w-4" />
                                <span>{item.label}</span>
                                {item.shortcut && (
                                    <CommandShortcut>{item.shortcut}</CommandShortcut>
                                )}
                            </CommandItem>
                        );
                    })}
                </CommandGroup>


            </CommandList>
        </CommandDialog>
    );
}
