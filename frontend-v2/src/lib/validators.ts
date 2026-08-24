/**
 * Common validation functions for form inputs
 */

export interface ValidationResult {
  isValid: boolean;
  error?: string;
}

/**
 * Validate port number (1-65535)
 */
export function validatePort(value: string | number): ValidationResult {
  const port = typeof value === 'string' ? parseInt(value) : value;

  if (isNaN(port)) {
    return { isValid: false, error: 'Port must be a number' };
  }

  if (port < 1 || port > 65535) {
    return { isValid: false, error: 'Port must be between 1 and 65535' };
  }

  return { isValid: true };
}

/**
 * Validate Kubernetes resource name (RFC 1123)
 */
export function validateK8sResourceName(value: string): ValidationResult {
  if (!value) {
    return { isValid: false, error: 'Resource name is required' };
  }

  // RFC 1123: lowercase alphanumeric, hyphens, max 253 chars
  const k8sNameRegex = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;

  if (value.length > 253) {
    return { isValid: false, error: 'Resource name must be at most 253 characters' };
  }

  if (!k8sNameRegex.test(value)) {
    return {
      isValid: false,
      error: 'Invalid format. Use lowercase letters, numbers, and hyphens only',
    };
  }

  return { isValid: true };
}

