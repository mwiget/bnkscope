/**
 * API module barrel.
 *
 * Prefer importing the domain module you need —
 * `import { kubernetesApi } from '@/lib/api/kubernetes'` — over the combined
 * `api` object below, which pulls every domain into the bundle.
 */

// Re-export the client for direct use
export { apiClient } from './client';

// Re-export domain-specific APIs
export { kubernetesApi } from './kubernetes';
export { systemApi } from './system';
export { alertsApi } from './alerts';
export { recoveryApi } from './recovery';
export { qkviewApi } from './qkview';
export { tmmDebugApi } from './tmm-debug';
export { logsApi } from './logs';
export { tmmscopeApi } from './tmmscope';
export { notificationsApi } from './notifications';
export { settingsApi } from './settings';
export { backupApi } from './backup';
export { llmObservabilityApi } from './llmObservability';

// Import all for the unified api object
import { kubernetesApi } from './kubernetes';
import { systemApi } from './system';
import { alertsApi } from './alerts';
import { recoveryApi } from './recovery';
import { qkviewApi } from './qkview';
import { tmmDebugApi } from './tmm-debug';
import { logsApi } from './logs';
import { tmmscopeApi } from './tmmscope';

/**
 * One object carrying every domain API, for callers that want a single import.
 */
export const api = {

  // Kubernetes & F5 BNK
  ...kubernetesApi,

  // System
  ...systemApi,

  // Alerts
  ...alertsApi,

  // Recovery (K8s cert rotation & cluster recovery)
  ...recoveryApi,

  // QKView (BNK diagnostics)
  ...qkviewApi,

  // TMM Debug (traffic management debugging)
  ...tmmDebugApi,

  // tmmscope (live TMM telemetry — read-only orchestration)
  ...tmmscopeApi,
  ...logsApi,
};
