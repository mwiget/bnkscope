/**
 * Shared cluster-scan primitives.
 *
 * These lived under `migration/` alongside the proxy/CIS migration cards until
 * migration went with the pipeline (bnkscope Phase 1). What is left is the
 * generic scan-result presentation used by ClusterScanResults.
 */

export { ScanCard, StatusBadge, StatusDot, statusConfig } from './ScanCard';
export { StatRow } from './StatRow';
export type { PrereqStatus } from './ScanCard';
