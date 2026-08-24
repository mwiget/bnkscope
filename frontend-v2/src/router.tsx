import { createBrowserRouter } from 'react-router-dom';
import { lazy } from 'react';
import { AppShell } from '@/components/layout/AppShell';
import { ErrorBoundary, NotFound } from '@/components/ErrorBoundary';

// Lazy load route components for code splitting
const CommandCenter = lazy(() => import('@/pages/CommandCenter'));
const KubernetesV2 = lazy(() => import('@/pages/KubernetesV2'));
const F5BNK = lazy(() => import('@/pages/F5BNK'));
const CNF = lazy(() => import('@/pages/CNF'));
const TmmLive = lazy(() => import('@/pages/TmmLive'));
const Logs = lazy(() => import('@/pages/Logs'));
const System = lazy(() => import('@/pages/System'));
const MCP = lazy(() => import('@/pages/MCP'));
const LlmDashboard = lazy(() => import('@/pages/observability/LlmDashboard'));
const LlmLogs = lazy(() => import('@/pages/observability/LlmLogs'));

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <ErrorBoundary />,
    children: [
      {
        // Sorted by trouble, not by name: the question the home page answers is
        // "is anything wrong right now, and where?".
        index: true,
        element: <CommandCenter />,
      },
      {
        path: 'kubernetes',
        element: <KubernetesV2 />,
      },
      {
        path: 'bnk',
        element: <F5BNK />,
      },
      {
        path: 'cnf',
        element: <CNF />,
      },
      {
        path: 'logs',
        element: <Logs />,
      },
      {
        path: 'tmm-live',
        element: <TmmLive />,
      },
      {
        path: 'system',
        element: <System />,
      },
      {
        path: 'observability/ai-gateway',
        element: <LlmDashboard />,
      },
      {
        path: 'observability/ai-gateway/logs',
        element: <LlmLogs />,
      },
      {
        path: 'mcp-server',
        element: <MCP />,
      },
      {
        path: '*',
        element: <NotFound />,
      },
    ],
  },
], {
  future: {
    v7_relativeSplatPath: true,
  },
});
