/**
 * FU-002: lib/validators — all validation functions
 */
import { describe, it, expect, vi } from 'vitest';
import {
  validatePort,
  validateK8sResourceName,
} from '../validators';

describe('validatePort()', () => {
  it('validates correct ports', () => {
    expect(validatePort(80)).toEqual({ isValid: true });
    expect(validatePort('443')).toEqual({ isValid: true });
    expect(validatePort(1)).toEqual({ isValid: true });
    expect(validatePort(65535)).toEqual({ isValid: true });
  });

  it('rejects non-numeric', () => {
    expect(validatePort('abc')).toEqual({ isValid: false, error: 'Port must be a number' });
  });

  it('rejects out-of-range', () => {
    expect(validatePort(0)).toEqual({ isValid: false, error: 'Port must be between 1 and 65535' });
    expect(validatePort(65536)).toEqual({ isValid: false, error: 'Port must be between 1 and 65535' });
  });
});

describe('validateK8sResourceName()', () => {
  it('validates correct names', () => {
    expect(validateK8sResourceName('my-app')).toEqual({ isValid: true });
    expect(validateK8sResourceName('nginx123')).toEqual({ isValid: true });
    expect(validateK8sResourceName('a')).toEqual({ isValid: true });
  });

  it('rejects empty value', () => {
    expect(validateK8sResourceName('')).toEqual({ isValid: false, error: 'Resource name is required' });
  });

  it('rejects uppercase', () => {
    expect(validateK8sResourceName('MyApp')).toEqual({
      isValid: false,
      error: 'Invalid format. Use lowercase letters, numbers, and hyphens only',
    });
  });

  it('rejects leading hyphen', () => {
    expect(validateK8sResourceName('-my-app')).toEqual({
      isValid: false,
      error: 'Invalid format. Use lowercase letters, numbers, and hyphens only',
    });
  });

  it('rejects names over 253 chars', () => {
    const longName = 'a'.repeat(254);
    expect(validateK8sResourceName(longName)).toEqual({
      isValid: false,
      error: 'Resource name must be at most 253 characters',
    });
  });
});

