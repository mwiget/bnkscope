/**
 * FU-025: lib/api/system — system API calls
 */
import { describe, it, expect } from 'vitest';
import { systemApi } from '../system';

describe('systemApi', () => {
  it('getSystemHealth returns health data', async () => {
    const health = await systemApi.getSystemHealth();
    expect(health.services.backend.status).toBe('healthy');
    expect(health.services.database.status).toBe('healthy');
  });

  it('getPerformanceMetrics returns metrics', async () => {
    const metrics = await systemApi.getPerformanceMetrics();
    expect(metrics).toBeDefined();
  });

  it('getSystemVersion returns version info', async () => {
    const version = await systemApi.getSystemVersion();
    expect(version).toHaveProperty('current_version');
  });
});
