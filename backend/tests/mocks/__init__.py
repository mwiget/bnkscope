"""
Shared mocks for bnkscope backend tests.

Provides reusable mock objects for external services that should not
be called during unit/integration tests:
- Subprocess (helm, kubectl CLI calls)
- Kubernetes (kr8s, kubernetes client)
- Cache (the in-process cache service)
"""

from tests.mocks.cache_mock import MockCacheService
from tests.mocks.kubernetes_mock import (
    MockKubernetesService,
    mock_kr8s_api,
    mock_kubernetes_client,
)
from tests.mocks.subprocess_mock import (
    mock_helm_subprocess,
    mock_kubectl_subprocess,
)

__all__ = [
    # Subprocess
    "mock_helm_subprocess",
    "mock_kubectl_subprocess",
    # Kubernetes
    "mock_kubernetes_client",
    "mock_kr8s_api",
    "MockKubernetesService",
    # Cache
    "MockCacheService",
]
