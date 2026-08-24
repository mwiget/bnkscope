/**
 * Tests for error-handler.ts
 *
 * Covers: maps known error patterns to correct suggestions and actions,
 * handles unknown errors gracefully.
 */
import { describe, it, expect } from 'vitest';
import { AxiosError } from 'axios';
import { parseApiError } from '@/lib/error-handler';

// Helper to create mock AxiosError
function createAxiosError(
  status: number,
  data?: Record<string, unknown>,
  message?: string
): AxiosError {
  const error = new AxiosError(
    message || `Request failed with status code ${status}`,
    status === 0 ? 'ERR_NETWORK' : undefined,
    undefined,
    undefined,
    {
      status,
      data: data || {},
      statusText: '',
      headers: {},
      config: {} as never,
    } as never
  );
  return error;
}

describe('parseApiError', () => {
  // =========================================================================
  // HTTP Status Code Handling
  // =========================================================================

  it('handles 401 Unauthorized', () => {
    const error = createAxiosError(401);
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Authentication Required');
    expect(parsed.severity).toBe('warning');
    // The action button used to navigate here; the page was deleted with
    // the pipeline, so a button that lands on NotFound is worse than none.
    expect(parsed.action).toBeUndefined();
  });

  it('maps downstream K8S_API_ERROR unauthorized to actionable EKS guidance', () => {
    const error = createAxiosError(401, {
      error: {
        code: 'K8S_API_ERROR',
        detail: 'Kubernetes API Unauthorized: the server has asked for the client to provide credentials',
      },
    });
    const parsed = parseApiError(error, {
      detectedPlatformProfile: 'eks',
    });

    expect(parsed.title).toBe('Cluster Authentication Expired');
    expect(parsed.message).toContain('AWS/EKS cluster access credentials');
    expect(parsed.suggestion).toContain('Refresh kubeconfig');
    expect(parsed.action?.route).toBe('/kubernetes');
    expect(parsed.severity).toBe('warning');
  });

  it('maps downstream K8S_API_ERROR unauthorized to platform-neutral guidance outside EKS context', () => {
    const error = createAxiosError(401, {
      error: {
        code: 'K8S_API_ERROR',
        detail: 'Kubernetes API Unauthorized: the server has asked for the client to provide credentials',
      },
    });
    const parsed = parseApiError(error, {
      detectedPlatformProfile: 'generic_onprem',
    });

    expect(parsed.title).toBe('Cluster Authentication Expired');
    expect(parsed.message).toBe('Cluster access credentials appear to be expired or invalid.');
    expect(parsed.suggestion).toBe('Refresh kubeconfig for this cluster, then retry the operation.');
    expect(parsed.action?.route).toBe('/kubernetes');
    expect(parsed.severity).toBe('warning');
  });

  it('does not remap generic 401s without K8S_API_ERROR code', () => {
    const error = createAxiosError(401, {
      error: {
        code: 'UNAUTHORIZED',
        message: 'Unauthorized',
      },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Authentication Required');
    expect(parsed.action).toBeUndefined();
  });

  it('maps OCP SCC-related failures to platform-aware remediation guidance', () => {
    const error = createAxiosError(403, {
      error: {
        code: 'K8S_API_ERROR',
        detail: 'forbidden: unable to validate against any security context constraint',
      },
    });

    const parsed = parseApiError(error, {
      detectedPlatformProfile: 'ocp',
      platformCapabilities: { scc: true },
    });

    expect(parsed.title).toBe('OpenShift Security Binding Required');
    expect(parsed.message).toContain('rejected by OpenShift security constraints');
    expect(parsed.suggestion).toContain('security binding');
    expect(parsed.action?.route).toBe('/kubernetes');
    expect(parsed.severity).toBe('warning');
  });

  it('maps OCP ingress/operator-managed networking failures to platform-aware guidance', () => {
    const error = createAxiosError(403, {
      error: {
        code: 'K8S_API_ERROR',
        detail: 'admission webhook denied ingress: operator-managed route required',
      },
    });

    const parsed = parseApiError(error, {
      detectedPlatformProfile: 'ocp',
      platformCapabilities: { openshift_routes: true },
    });

    expect(parsed.title).toBe('OpenShift Networking Path Required');
    expect(parsed.message).toContain('rejected for the detected OpenShift context');
    expect(parsed.suggestion).toContain('Route/operator networking path');
    expect(parsed.action?.route).toBe('/kubernetes');
    expect(parsed.severity).toBe('warning');
  });

  it('does not remap generic OCP ingress RBAC failures to operator-managed networking guidance', () => {
    const error = createAxiosError(403, {
      error: {
        code: 'K8S_API_ERROR',
        detail: 'forbidden: User "dev" cannot create resource "ingresses" in API group "networking.k8s.io" in the namespace "default"',
      },
    });

    const parsed = parseApiError(error, {
      detectedPlatformProfile: 'ocp',
      platformConstraints: { operator_required_for_networking: true },
    });

    expect(parsed.title).toBe('Permission Denied');
    expect(parsed.action?.route).toBe('/system');
  });

  it('handles 403 Forbidden', () => {
    const error = createAxiosError(403);
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Permission Denied');
    expect(parsed.severity).toBe('error');
    expect(parsed.action?.route).toBe('/system');
  });

  it('handles 404 Not Found', () => {
    const error = createAxiosError(404);
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Not Found');
    expect(parsed.severity).toBe('warning');
  });

  it('handles 409 Conflict', () => {
    const error = createAxiosError(409, {
      error: { message: 'Project name already taken' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Conflict');
    expect(parsed.severity).toBe('warning');
  });

  it('handles 422 Validation Error', () => {
    const error = createAxiosError(422, {
      error: { message: 'Invalid field values' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Validation Error');
    expect(parsed.severity).toBe('error');
  });

  it('handles 500 Server Error', () => {
    const error = createAxiosError(500);
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Server Error');
    expect(parsed.severity).toBe('error');
    // The action button used to navigate here; the page was deleted with
    // the pipeline, so a button that lands on NotFound is worse than none.
    expect(parsed.action).toBeUndefined();
  });

  it('handles 503 Service Unavailable', () => {
    const error = createAxiosError(503);
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Service Unavailable');
    expect(parsed.severity).toBe('warning');
    expect(parsed.action?.route).toBe('/system');
  });

  // =========================================================================
  // Network & Timeout Errors
  // =========================================================================

  it('handles network error', () => {
    const error = new AxiosError('Network Error', 'ERR_NETWORK');
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Network Error');
    expect(parsed.severity).toBe('error');
    expect(parsed.action?.route).toBe('/system');
  });

  it('handles timeout error', () => {
    const error = new AxiosError('timeout of 30000ms exceeded', 'ECONNABORTED');
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Request Timeout');
    expect(parsed.severity).toBe('warning');
    expect(parsed.action).toBeUndefined();
  });

  // =========================================================================
  // Domain-Specific Error Patterns
  // =========================================================================

  it('maps dependency errors correctly', () => {
    const error = createAxiosError(400, {
      error: { message: 'Module depends on vpc which has not been applied' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Dependency Error');
    expect(parsed.suggestion).toContain('dependencies');
  });

  it('maps "already exists" errors', () => {
    // Use status 400 (not 409) since 409 is caught by the status-specific handler first
    const error = createAxiosError(400, {
      error: { message: 'Resource already exists' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Resource Exists');
    expect(parsed.severity).toBe('warning');
  });

  it('maps credentials/AccessDenied errors', () => {
    const error = createAxiosError(400, {
      error: { message: 'credentials verification failed: AccessDenied' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Credentials Error');
    // The action button used to navigate here; the page was deleted with
    // the pipeline, so a button that lands on NotFound is worse than none.
    expect(parsed.action).toBeUndefined();
  });

  it('maps cluster offline errors', () => {
    const error = createAxiosError(502, {
      error: { message: 'cluster is offline or unreachable' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Cluster Offline');
    // The action button used to navigate here; the page was deleted with
    // the pipeline, so a button that lands on NotFound is worse than none.
    expect(parsed.action).toBeUndefined();
  });

  it('maps operator disconnected errors', () => {
    const error = createAxiosError(502, {
      error: { message: 'operator not connected' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Operator Disconnected');
    expect(parsed.action).toBeUndefined();
  });

  it('maps metrics-server errors', () => {
    const error = createAxiosError(400, {
      error: { message: 'metrics-server not installed' },
    });
    const parsed = parseApiError(error);

    expect(parsed.title).toBe('Metrics Unavailable');
    expect(parsed.severity).toBe('info');
    // The action button used to navigate here; the page was deleted with
    // the pipeline, so a button that lands on NotFound is worse than none.
    expect(parsed.action).toBeUndefined();
  });

  // =========================================================================
  // Edge Cases
  // =========================================================================

  it('handles null/undefined error', () => {
    const parsed = parseApiError(null);
    expect(parsed.title).toBe('Operation Failed');
    expect(parsed.severity).toBe('error');
  });

  it('handles string error', () => {
    const parsed = parseApiError('Something went wrong');
    expect(parsed.message).toBe('Something went wrong');
  });

  it('handles plain Error instance', () => {
    const parsed = parseApiError(new Error('Generic error'));
    expect(parsed.message).toBe('Generic error');
  });

  it('handles unknown error shape', () => {
    const parsed = parseApiError({ weird: 'object' });
    expect(parsed.title).toBe('Operation Failed');
  });
});

