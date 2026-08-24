/**
 * FU-007: lib/status-colors — status color mapping functions.
 *
 * D-020: assertions retuned from raw-palette names (`emerald`/`red`/`amber`/`slate`)
 * to the semantic tokens the module now emits (`success`/`destructive`/`warning`/`muted`/`info`).
 */
import { describe, it, expect } from 'vitest';
import {
  getResourceStatusColor,
} from '../status-colors';

describe('getResourceStatusColor()', () => {
  it('returns success for success states', () => {
    expect(getResourceStatusColor('Running')).toContain('success');
    expect(getResourceStatusColor('Ready')).toContain('success');
    expect(getResourceStatusColor('deployed')).toContain('success');
    expect(getResourceStatusColor('Active')).toContain('success');
    expect(getResourceStatusColor('Bound')).toContain('success');
  });

  it('returns destructive for error states', () => {
    expect(getResourceStatusColor('Failed')).toContain('destructive');
    expect(getResourceStatusColor('Error')).toContain('destructive');
    expect(getResourceStatusColor('CrashLoopBackOff')).toContain('destructive');
    expect(getResourceStatusColor('ImagePullBackOff')).toContain('destructive');
  });

  it('returns destructive for NotReady (before Ready match)', () => {
    expect(getResourceStatusColor('NotReady')).toContain('destructive');
  });

  it('returns warning for pending/warning states', () => {
    expect(getResourceStatusColor('Pending')).toContain('warning');
    expect(getResourceStatusColor('Waiting')).toContain('warning');
    expect(getResourceStatusColor('Unknown')).toContain('warning');
  });

  it('returns muted for terminating states', () => {
    expect(getResourceStatusColor('Terminating')).toContain('muted');
    expect(getResourceStatusColor('Deleting')).toContain('muted');
    expect(getResourceStatusColor('Uninstalling')).toContain('muted');
  });

  it('returns muted for empty/null status', () => {
    expect(getResourceStatusColor('')).toContain('muted');
  });

  it('returns muted for unrecognized status', () => {
    expect(getResourceStatusColor('SomeCustomStatus')).toContain('muted');
  });
});

