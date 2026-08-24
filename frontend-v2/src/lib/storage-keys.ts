/**
 * Centralized localStorage key constants
 *
 * Single source of truth for all localStorage keys used in the application.
 * Prevents key collisions and typos, makes keys easy to find and update.
 *
 * Key naming convention: STORAGE_KEYS.CATEGORY_PURPOSE
 */

export const STORAGE_KEYS = {
  // Kubernetes & Cluster Management
  K8S_PROJECT: 'bnk-forge-k8s-project',
  // The cluster you are looking at, shared by every page. The per-page keys
  // below are superseded and read only as a one-time fallback — see
  // hooks/useSelectedCluster.ts.
  SELECTED_CLUSTER: 'bnkscope-selected-cluster',
  /** Logs page: collapse repeated lines. 'off' opts out; anything else is on. */
  LOGS_COLLAPSE: 'bnkscope-logs-collapse',
  K8S_CLUSTER: 'bnk-forge-k8s-cluster',
  K8S_NAMESPACE: 'bnk-forge-k8s-namespace',
  K8S_RESOURCE_TYPE: 'bnk-forge-k8s-resource-type',
  K8S_UNHEALTHY_ONLY: 'bnk-forge-k8s-unhealthy-only',
  K8S_VIEW_MODE: 'bnk-forge-k8s-view-mode',

  // Helm Package Management
  HELM_CLUSTER: 'bnk-forge-helm-cluster',

  // F5 BNK Management
  BNK_PROJECT: 'bnk-forge-bnk-project',
  BNK_CLUSTER: 'bnk-forge-bnk-cluster',

  // CNF Dashboard (Custom Resource browser)
  CNF_PROJECT: 'bnk-forge-cnf-project',
  CNF_CLUSTER: 'bnk-forge-cnf-cluster',

  // Authentication

  // Onboarding & First-time User Experience
  ONBOARDING_COMPLETE: 'bnk-forge-onboarding-complete',

  // UI Preferences
  MOCKUP_THEME: 'mockup-theme',
} as const;

/**
 * Type-safe storage key accessor
 * Ensures only valid keys can be used at compile time
 */
export type StorageKey = typeof STORAGE_KEYS[keyof typeof STORAGE_KEYS];
