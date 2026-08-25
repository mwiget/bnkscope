/**
 * Kubernetes page sub-module barrel export
 * FE-002: Expanded with decomposed sub-components
 * K8S-UX-004: Added Helm components (releases table, chart browser)
 */

// Constants & helpers (pre-existing)
export { resourceTree, calculateAge, getStatusColor, getRestartCount, isHelmResourceType } from './k8s-constants';

// Status determination logic
export { getResourceStatus, isResourceUnhealthy } from './k8s-status';

// Sub-components
export { K8sSidebar } from './K8sSidebar';
export { K8sResourceTable } from './K8sResourceTable';
export type { ResourceAction } from './K8sResourceTable';
export { K8sDetailPanel } from './K8sDetailPanel';
export { K8sDialogs, K8sClusterScanView, K8sDpfInfraView, K8sNicoView, useK8sDialogs } from './K8sDialogs';

// K8S-UX-004: Helm integration
