/**
 * Unified Notification Utility
 *
 * Every notification persists to the bell (the notification centre).
 * There is no transient/toast channel — the bell is the only path.
 */

import { notificationsApi } from './api/notifications';
import { queryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { parseApiError } from './error-handler';
import type { ParseApiErrorContext } from './error-handler';

// ============================================================================
// Types
// ============================================================================

export type NotificationSeverity = 'success' | 'error' | 'warning' | 'info';

export interface NotifyOptions {
  /** Notification title */
  title: string;
  /** Notification message/description */
  message?: string;
  /** Severity level */
  severity: NotificationSeverity;
  /** Resource type for bell notification (e.g., 'deployment', 'module') */
  resourceType?: string;
  /** Resource ID for bell notification */
  resourceId?: number;
  /** Notification category (e.g. 'general', 'credentials', 'deployment') */
  category?: string;
  /** Deep-link URL stored on the bell entry */
  action_url?: string;
  /** Deduplicate key — backend drops duplicate if already unread */
  dedupe_key?: string;
}

// ============================================================================
// Bell Notification API
// ============================================================================

async function createBellNotification(
  type: NotificationSeverity,
  title: string,
  message: string,
  resourceType?: string,
  resourceId?: number,
  category?: string,
  action_url?: string,
  dedupe_key?: string,
): Promise<void> {
  try {
    await notificationsApi.createNotification({
      type,
      severity: type,
      title,
      message,
      resource_type: resourceType,
      resource_id: resourceId,
      category: category ?? 'general',
      action_url,
      dedupe_key,
    });
    // Invalidate bell + unread-count so UI updates immediately (no wait for poll interval).
    // Fire-and-forget — we do NOT await here; a cache miss just falls back to the next poll.
    queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
  } catch {
    // CRITICAL: must NOT call notify.error / notifyError here — that would cause infinite recursion.
    // Just warn to the console and swallow so callers never see a rejection.
    console.warn('[notify] Failed to create bell notification — will retry on next poll');
  }
}

// ============================================================================
// Main Notification Function
// ============================================================================

/**
 * Persist a notification to the bell (notification centre).
 *
 * @example
 * notify({ title: 'Settings saved', severity: 'success' });
 */
export function notify(options: NotifyOptions): void {
  const {
    title,
    message,
    severity,
    resourceType,
    resourceId,
    category,
    action_url,
    dedupe_key,
  } = options;

  createBellNotification(
    severity,
    title,
    message || title,
    resourceType,
    resourceId,
    category,
    action_url,
    dedupe_key,
  );
}

// ============================================================================
// Convenience Methods
// ============================================================================

/**
 * Success notification
 */
notify.success = function (
  title: string,
  message?: string,
  opts?: Partial<Omit<NotifyOptions, 'title' | 'message' | 'severity'>>
): void {
  notify({ title, message, severity: 'success', ...opts });
};

/**
 * Error notification
 */
notify.error = function (
  title: string,
  message?: string,
  opts?: Partial<Omit<NotifyOptions, 'title' | 'message' | 'severity'>>
): void {
  notify({ title, message, severity: 'error', ...opts });
};

/**
 * Warning notification
 */
notify.warning = function (
  title: string,
  message?: string,
  opts?: Partial<Omit<NotifyOptions, 'title' | 'message' | 'severity'>>
): void {
  notify({ title, message, severity: 'warning', ...opts });
};

/**
 * Info notification
 */
notify.info = function (
  title: string,
  message?: string,
  opts?: Partial<Omit<NotifyOptions, 'title' | 'message' | 'severity'>>
): void {
  notify({ title, message, severity: 'info', ...opts });
};

// ============================================================================
// Error Handling Utility
// ============================================================================

/**
 * Parse and display an API error as a bell notification.
 *
 * Uses the error-handler to parse errors; when the parsed error includes a
 * route action, it is surfaced as the bell entry's deep-link (action_url).
 *
 * @param error - The error object from API call
 * @param context - Optional context about the operation (e.g., 'deploying module')
 * @param errorContext - Optional parser context
 */
export function notifyError(
  error: unknown,
  _context?: string,
  errorContext?: ParseApiErrorContext,
): void {
  // Skip auth errors — the API interceptor already handles the redirect to /login.
  const axiosCode = (error as { response?: { data?: { error?: { code?: string } } } })
    ?.response?.data?.error?.code;
  if (axiosCode === 'UNAUTHORIZED') return;

  const parsed = parseApiError(error, errorContext);

  const title = parsed.title;

  const message = parsed.suggestion
    ? `${parsed.message}\n${parsed.suggestion}`
    : parsed.message;

  const severityMap: Record<string, NotificationSeverity> = {
    error: 'error',
    warning: 'warning',
    info: 'info',
  };

  // Surface the parsed route as the bell entry's deep-link.
  const actionUrl = parsed.action?.route;

  // Infer category from action route for common patterns.
  const category = actionUrl === '/auth-templates' ? 'credentials' : 'general';

  notify({
    title,
    message,
    severity: severityMap[parsed.severity] || 'error',
    action_url: actionUrl,
    category,
  });
}

// ============================================================================
// Deployment-Specific Notifications
// ============================================================================

