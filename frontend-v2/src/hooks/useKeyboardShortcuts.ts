import { useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

export interface KeyboardShortcut {
    key: string;
    ctrl?: boolean;
    meta?: boolean;
    shift?: boolean;
    alt?: boolean;
    action: (e: KeyboardEvent) => void;
    description?: string;
    /** If true, shortcut fires even when user is in an input/textarea (default: false) */
    allowInInput?: boolean;
}

/**
 * Global keyboard shortcuts hook with input-awareness.
 * By default, shortcuts are suppressed when the user is typing in an input,
 * textarea, or contentEditable element. Set allowInInput to override.
 *
 * Usage:
 * useKeyboardShortcuts([
 *   { key: 'k', meta: true, action: openCommandPalette, description: 'Open command palette' },
 *   { key: '/', action: focusSearch, description: 'Focus search', allowInInput: true },
 * ]);
 */
export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[], enabled: boolean = true) {
    const handleKeyDown = useCallback(
        (event: KeyboardEvent) => {
            if (!enabled) return;

            for (const shortcut of shortcuts) {
                if (!event.key) continue;
                const metaMatch = shortcut.meta ? (event.metaKey || event.ctrlKey) : true;
                const ctrlMatch = shortcut.ctrl ? event.ctrlKey : true;
                const shiftMatch = shortcut.shift ? event.shiftKey : true;
                const altMatch = shortcut.alt ? event.altKey : true;
                const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase();

                if (metaMatch && ctrlMatch && shiftMatch && altMatch && keyMatch) {
                    // Don't trigger if user is typing in an input (unless allowed)
                    const target = event.target as HTMLElement | null;
                    const isInput =
                        target?.tagName === 'INPUT' ||
                        target?.tagName === 'TEXTAREA' ||
                        target?.isContentEditable;

                    if (isInput && !shortcut.allowInInput) {
                        return;
                    }

                    event.preventDefault();
                    event.stopPropagation();
                    shortcut.action(event);
                    return;
                }
            }
        },
        [shortcuts, enabled]
    );

    useEffect(() => {
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [handleKeyDown]);
}

/**
 * Two-key sequence shortcuts (e.g., G then D = Go to Dashboard).
 *
 * After pressing the leader key (G), a 1-second window opens for the
 * follow-up key. If no follow-up arrives, the sequence resets silently.
 */
export function useSequenceShortcuts(
    sequences: Array<{
        leader: string;
        followUp: string;
        action: () => void;
        description: string;
    }>,
    enabled: boolean = true
) {
    const leaderRef = useRef<string | null>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const handleKeyDown = useCallback(
        (event: KeyboardEvent) => {
            if (!enabled) return;

            // Skip if user is in an input
            const target = event.target as HTMLElement | null;
            const isInput =
                target?.tagName === 'INPUT' ||
                target?.tagName === 'TEXTAREA' ||
                target?.isContentEditable;
            if (isInput) return;

            // Skip if modifier keys are pressed (these are for useKeyboardShortcuts)
            if (event.metaKey || event.ctrlKey || event.altKey) return;

            if (!event.key) return;
            const key = event.key.toLowerCase();

            if (leaderRef.current) {
                // We're in a sequence — check for follow-up
                const leader = leaderRef.current;
                leaderRef.current = null;
                if (timerRef.current) {
                    clearTimeout(timerRef.current);
                    timerRef.current = null;
                }

                for (const seq of sequences) {
                    if (seq.leader.toLowerCase() === leader && seq.followUp.toLowerCase() === key) {
                        event.preventDefault();
                        seq.action();
                        return;
                    }
                }
                // No match — ignore
                return;
            }

            // Check if this key is a leader for any sequence
            const isLeader = sequences.some(s => s.leader.toLowerCase() === key);
            if (isLeader) {
                leaderRef.current = key;
                // Auto-reset after 1 second
                timerRef.current = setTimeout(() => {
                    leaderRef.current = null;
                    timerRef.current = null;
                }, 1000);
            }
        },
        [sequences, enabled]
    );

    useEffect(() => {
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    }, [handleKeyDown]);
}

/**
 * Every navigable destination, and the `g`-sequence key that reaches it.
 *
 * One table, three consumers: the live bindings, the modifier list and the
 * help modal. They used to be three separate literals, and when the routes
 * changed nine of the thirteen shortcuts pointed at pages that no longer
 * existed — `/projects`, `/fleet`, `/operators`, `/tasks`, `/helm` — while the
 * help dialog went on advertising all of them. The tests never caught it
 * because they asserted the shape of the list and its length, never that a
 * destination was somewhere you could actually go.
 *
 * `__tests__/useKeyboardShortcuts.test.ts` now checks each `path` against the
 * router, so a deleted route breaks the build instead of the shortcut.
 */
export const NAV_SHORTCUTS = [
    { key: 'd', path: '/', label: 'Overview' },
    { key: 'k', path: '/kubernetes', label: 'Clusters' },
    { key: 'b', path: '/bnk', label: 'BNK Health' },
    { key: 't', path: '/tmm-live', label: 'TMM Live' },
    { key: 'l', path: '/logs', label: 'Logs' },
    { key: 'c', path: '/cnf', label: 'CNF Resources' },
    { key: 'a', path: '/observability/ai-gateway', label: 'AI Gateway' },
    { key: 's', path: '/system', label: 'System' },
    { key: 'm', path: '/mcp-server', label: 'MCP' },
] as const;

/**
 * Hook for common navigation shortcuts
 */
export function useNavigationShortcuts() {
    const navigate = useNavigate();

    // G-then-X sequences — vim-style navigation without modifier keys.
    //
    // There is deliberately no Cmd/Ctrl navigation pair any more. The old set
    // bound Meta+D, Meta+P and Meta+E, which are Bookmark, Print and the
    // browser's own in every one of them; the sequences collide with nothing.
    useSequenceShortcuts(
        NAV_SHORTCUTS.map(({ key, path, label }) => ({
            leader: 'g',
            followUp: key,
            action: () => navigate(path),
            description: `Go to ${label}`,
        })),
    );
}

/**
 * Get all available keyboard shortcuts
 */
export function getAvailableShortcuts(): KeyboardShortcut[] {
    return [
        {
            key: 'k',
            meta: true,
            action: () => { },
            description: 'Open command palette',
        },
        {
            key: '/',
            meta: true,
            action: () => { },
            description: 'Show keyboard shortcuts',
        },
    ];
}

/**
 * Get all available sequence shortcuts for display
 */
export function getSequenceShortcuts(): Array<{ keys: string; description: string }> {
    return NAV_SHORTCUTS.map(({ key, label }) => ({
        keys: `G → ${key.toUpperCase()}`,
        description: `Go to ${label}`,
    }));
}

/**
 * Format shortcut for display
 */
export function formatShortcut(shortcut: KeyboardShortcut): string {
    const parts: string[] = [];

    if (shortcut.meta) parts.push('⌘');
    if (shortcut.ctrl) parts.push('Ctrl');
    if (shortcut.shift) parts.push('⇧');
    if (shortcut.alt) parts.push('⌥');

    parts.push(shortcut.key.toUpperCase());

    return parts.join('');
}
