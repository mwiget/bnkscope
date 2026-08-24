/**
 * Shared API client configuration
 * All domain-specific API modules import this client
 */
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type { ApiError } from '@/types';

// Use relative URL for portability - requests go through the proxy which forwards /api/ to backend
// This allows the app to work when accessed from any host (not just localhost)
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** Maximum retries for transient server errors */
const MAX_RETRIES = 2;

/** Base delay for exponential backoff (ms) */
const RETRY_BASE_DELAY = 1000;

/** Status codes worth retrying (transient server/gateway errors) */
const RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor (handle errors with retry for transient failures)
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ error: ApiError }>) => {
    const config = error.config as InternalAxiosRequestConfig & { _retryCount?: number };
    const status = error.response?.status;

    // Retry transient server errors with exponential backoff, but NOT when the
    // response body carries a structured domain-error envelope. A 502/503/504
    // with `{ error: { code, message } }` means the backend deliberately mapped
    // a downstream failure to that status — retrying just delays the user from
    // seeing the actionable error message.
    // Structured ApiError envelopes are surfaced immediately; transport/proxy HTML errors still retry.
    const hasStructuredError = typeof error.response?.data?.error?.code === 'string' && error.response.data.error.code.length > 0;
    if (config && status && RETRYABLE_STATUS_CODES.has(status) && !hasStructuredError) {
      const retryCount = config._retryCount ?? 0;
      if (retryCount < MAX_RETRIES) {
        config._retryCount = retryCount + 1;
        const delay = RETRY_BASE_DELAY * Math.pow(2, retryCount);
        await new Promise(resolve => setTimeout(resolve, delay));
        return apiClient(config);
      }
    }

    // No auth interceptor: bnkscope is a single-user local tool with no login.
    // What stood here redirected to /login on an UNAUTHORIZED envelope -- a
    // route that does not exist, so the app blanked instead of showing the
    // error. Nothing raises UnauthorizedError either.

    // Don't show toast here - let individual hooks handle error display
    // This prevents duplicate error messages and allows for context-specific error handling

    return Promise.reject(error);
  }
);
