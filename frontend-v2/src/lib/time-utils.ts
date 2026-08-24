/**
 * Centralized time formatting utilities
 *
 * Consolidates duplicate time calculations from 11 files into a single source of truth.
 * Provides consistent output formats across the application.
 */

/**
 * Format timestamp as compact age (e.g., "5d", "3h", "10m")
 * Use for tables, badges, and compact displays
 *
 * @param timestamp - ISO timestamp string, null, or undefined
 * @returns Compact age string or 'Unknown' if invalid
 */
export function formatAge(timestamp: string | null | undefined): string {
  if (!timestamp) return 'Unknown';

  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return 'Unknown';

  const diff = Date.now() - date.getTime();
  if (diff < 0) return 'just now'; // Future timestamps

  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d`;
  if (hours > 0) return `${hours}h`;
  if (minutes > 0) return `${minutes}m`;
  return 'just now';
}

/**
 * Format timestamp as relative time with "ago" suffix (e.g., "5d ago", "3h ago")
 * Use for activity feeds, history lists, and task displays
 *
 * @param timestamp - ISO timestamp string, null, or undefined
 * @returns Relative time string with "ago" suffix, or empty string if invalid
 */
export function formatTimeAgo(timestamp: string | null | undefined): string {
  if (!timestamp) return '';

  const age = formatAge(timestamp);
  if (age === 'Unknown') return '';
  if (age === 'just now') return age;
  return `${age} ago`;
}

