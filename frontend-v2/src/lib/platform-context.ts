import type {
  K8sCluster,
  ManagementBoundary,
  PlatformProfile,
} from '@/types';

const PLATFORM_LABELS: Record<PlatformProfile, string> = {
  generic_onprem: 'Generic On-Prem',
  eks: 'Amazon EKS',
  aks: 'Azure AKS',
  gke: 'Google GKE',
  roks: 'IBM ROKS',
  ocp: 'OpenShift / OKD',
  unknown: 'Unknown',
};

const MANAGEMENT_BOUNDARY_LABELS: Record<ManagementBoundary, string> = {
  customer_managed_cluster: 'Customer-managed cluster',
  forge_managed_components_only: 'Forge-managed components only',
  unknown: 'Unknown management boundary',
};

export function getPlatformProfileLabel(profile?: PlatformProfile | null): string {
  if (!profile) return PLATFORM_LABELS.unknown;
  return PLATFORM_LABELS[profile] ?? PLATFORM_LABELS.unknown;
}

export function getManagementBoundaryLabel(boundary?: ManagementBoundary | null): string | null {
  if (!boundary) return null;
  return MANAGEMENT_BOUNDARY_LABELS[boundary] ?? MANAGEMENT_BOUNDARY_LABELS.unknown;
}

export function getClusterDetectedPlatform(cluster?: K8sCluster | null): PlatformProfile {
  return cluster?.detected_platform_profile ?? 'unknown';
}


export function shouldShowDetectManagedClustersFromContext(
  targetPlatformProfile?: PlatformProfile | null,
  cloudProvider?: string | null,
): boolean {
  return (
    targetPlatformProfile === 'eks'
    || targetPlatformProfile === 'roks'
    || targetPlatformProfile === 'aks'
    || targetPlatformProfile === 'gke'
    || cloudProvider === 'aws'
    || cloudProvider === 'eks'
    || cloudProvider === 'ibm'
    || cloudProvider === 'roks'
    || cloudProvider === 'azure'
    || cloudProvider === 'aks'
    || cloudProvider === 'gcp'
    || cloudProvider === 'gke'
  );
}

export const shouldShowDetectEksFromContext = shouldShowDetectManagedClustersFromContext;
