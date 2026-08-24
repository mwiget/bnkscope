"""
Conftest for backend component tests.

Component tests exercise service classes with a real database (SQLite in-memory).
They mock only external systems (AWS, K8s clusters, Redis, Celery).

Available fixtures (inherited from root conftest):
- db — transactional SQLite session (rolls back after each test)
- make_user, make_module_library, make_project_module
- make_task, make_stack_template, make_stack_instance, make_k8s_cluster
- mock_cache — MockCacheService
- mock_tofu — patched subprocess.run for OpenTofu

Additional fixtures defined here:
- project_with_modules — a project pre-loaded with 2 modules
- module_library — a set of 3 module library entries
"""

from unittest.mock import patch

import pytest


