/**
 * tmmscope API methods.
 */
import { apiClient } from './client';
import type { ClusterTelemetry, InjectionState, TmmscopeStatus } from '@/types/tmmscope';

export const tmmscopeApi = {
  getStatus: () =>
    apiClient.get<TmmscopeStatus>('/api/tmmscope/status').then((res) => res.data),

  getClusterTelemetry: (clusterId: number, theme: 'dark' | 'light') =>
    apiClient
      .get<ClusterTelemetry>(`/api/tmmscope/clusters/${clusterId}`, { params: { theme } })
      .then((res) => res.data),

  // null clears the binding and returns to automatic name matching.
  bindClusterLabel: (clusterId: number, label: string | null, theme: 'dark' | 'light') =>
    apiClient
      .put<ClusterTelemetry>(`/api/tmmscope/clusters/${clusterId}/label`, { label }, {
        params: { theme },
      })
      .then((res) => res.data),

  getInjection: (clusterId: number) =>
    apiClient
      .get<InjectionState>(`/api/tmmscope/clusters/${clusterId}/injection`)
      .then((res) => res.data),

  // No image, command or mounts: the sidecar spec is built server-side from a
  // pinned image (D-036). Only the series label and push URL are inputs.
  inject: (clusterId: number, body?: { cluster_label?: string; remote_write_url?: string }) =>
    apiClient
      .post<InjectionState>(`/api/tmmscope/clusters/${clusterId}/injection`, body ?? {})
      .then((res) => res.data),

  // Recreates the f5-tmm pods — the only way to clear an ephemeral container.
  removeInjection: (clusterId: number) =>
    apiClient
      .delete<InjectionState>(`/api/tmmscope/clusters/${clusterId}/injection`)
      .then((res) => res.data),
};
