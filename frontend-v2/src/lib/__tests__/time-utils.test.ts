/**
 * FU-004: lib/time-utils — all time formatting functions
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { formatAge, formatTimeAgo } from '../time-utils';

describe('formatAge()', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-02-25T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns "Unknown" for null/undefined', () => {
    expect(formatAge(null)).toBe('Unknown');
    expect(formatAge(undefined)).toBe('Unknown');
  });

  it('returns "Unknown" for invalid timestamp', () => {
    expect(formatAge('not-a-date')).toBe('Unknown');
  });

  it('returns "just now" for recent timestamps', () => {
    expect(formatAge('2026-02-25T11:59:50Z')).toBe('just now');
  });

  it('returns "just now" for future timestamps', () => {
    expect(formatAge('2026-02-25T13:00:00Z')).toBe('just now');
  });

  it('returns minutes', () => {
    expect(formatAge('2026-02-25T11:50:00Z')).toBe('10m');
  });

  it('returns hours', () => {
    expect(formatAge('2026-02-25T09:00:00Z')).toBe('3h');
  });

  it('returns days', () => {
    expect(formatAge('2026-02-23T12:00:00Z')).toBe('2d');
  });
});

describe('formatTimeAgo()', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-02-25T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns empty string for null/undefined', () => {
    expect(formatTimeAgo(null)).toBe('');
    expect(formatTimeAgo(undefined)).toBe('');
  });

  it('returns empty string for invalid timestamp', () => {
    expect(formatTimeAgo('not-a-date')).toBe('');
  });

  it('returns "just now" for recent', () => {
    expect(formatTimeAgo('2026-02-25T11:59:50Z')).toBe('just now');
  });

  it('returns "Xm ago" for minutes', () => {
    expect(formatTimeAgo('2026-02-25T11:50:00Z')).toBe('10m ago');
  });

  it('returns "Xh ago" for hours', () => {
    expect(formatTimeAgo('2026-02-25T09:00:00Z')).toBe('3h ago');
  });

  it('returns "Xd ago" for days', () => {
    expect(formatTimeAgo('2026-02-23T12:00:00Z')).toBe('2d ago');
  });
});

