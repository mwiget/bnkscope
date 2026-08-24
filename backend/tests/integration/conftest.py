"""
Conftest for backend integration tests.

Integration tests exercise the full HTTP stack: routes -> services -> DB.
They use FastAPI TestClient with real SQLite but mock external systems
(AWS, K8s, Celery workers, Redis).

Available fixtures (inherited from root conftest):
- client — FastAPI TestClient with DB override
- db — transactional SQLite session
- admin_headers, operator_headers, viewer_headers — JWT auth headers
- sample_user, sample_operator_user, sample_viewer_user — pre-created users
- All factory fixtures (make_user, etc.)
- mock_cache, mock_tofu

Additional fixtures defined here:
- sample_module — a module library entry + project module for testing module routes
- sample_task — a pre-created task for testing task routes
"""


import pytest


