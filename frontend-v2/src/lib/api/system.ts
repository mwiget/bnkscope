/**
 * System Administration API methods
 */
import { apiClient } from './client';
import type {
  SystemHealth,
  ProcessMetrics,
  PerformanceMetrics,
  ErrorsList,
  DatabaseStats,
  VacuumResult,
  VersionInfo,
  UpgradeResponse,
  UpgradeState,
  UpgradeVerification,
} from '@/types/system';

export const systemApi = {
  // System Administration & Monitoring
  getSystemHealth: () =>
    apiClient.get<SystemHealth>('/api/system/health').then((res) => res.data),

  getProcessMetrics: () =>
    apiClient.get<ProcessMetrics>('/api/system/process-metrics').then((res) => res.data),

  getPerformanceMetrics: () =>
    apiClient.get<PerformanceMetrics>('/api/system/performance').then((res) => res.data),

  getRecentErrors: (limit = 10) =>
    apiClient.get<ErrorsList>(`/api/system/errors?limit=${limit}`).then((res) => res.data),

  // `/api/database/stats`, not `/api/system/database/stats` — this one hangs
  // off the api router, not the system router. The prefix was wrong, so the
  // card 404'd on System's default tab.
  getDatabaseStats: () =>
    apiClient.get<DatabaseStats>('/api/database/stats').then((res) => res.data),

  vacuumDatabase: () =>
    apiClient.post<VacuumResult>('/api/system/database/vacuum').then((res) => res.data),


  // System Version & Upgrade
  getSystemVersion: () =>
    apiClient.get<VersionInfo>('/api/system/version').then((res) => res.data),

  triggerSystemUpgrade: () =>
    apiClient.post<UpgradeResponse>('/api/system/upgrade').then((res) => res.data),

  /** UP-011: Post-upgrade verification — checks all services, version, migrations */
  verifyPostUpgrade: () =>
    apiClient.get<UpgradeVerification>('/api/system/upgrade/verify').then((res) => res.data),

  /** UP-003: Get persisted upgrade state for recovery after page refresh */
  getUpgradeStatus: () =>
    apiClient.get<UpgradeState>('/api/system/upgrade/status').then((res) => res.data),

  // MCP Server
  getMCPStatus: () =>
    apiClient.get<MCPStatusResponse>('/api/system/mcp/status').then((res) => res.data),
};

// MCP types (co-located since they're only used here + the page)
export interface MCPTool {
  name: string;
  description: string;
}

export interface MCPToolCategory {
  category: string;
  icon: string;
  tools: MCPTool[];
}

export interface MCPStatusResponse {
  status: 'healthy' | 'degraded' | 'offline';
  latency_ms: number | null;
  error: string | null;
  endpoint: string;
  port: number;
  transport: string;
  total_tools: number;
  tool_catalog: MCPToolCategory[];
}
