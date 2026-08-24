"""
Base service class providing common database lookup helpers.

Common entity lookups shared by the cluster-facing services.
"""
from sqlalchemy.orm import Session

from core.errors import NotFoundError
from models import KubernetesCluster


class BaseService:
    """Base class for database-backed services.

    Provides DRY helper methods for common entity lookups.
    Subclass and pass a db session to __init__.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Common lookup helpers
    # ------------------------------------------------------------------

    def _get_cluster(self, cluster_id: int) -> KubernetesCluster:
        """Get a Kubernetes cluster by ID or raise NotFoundError."""
        cluster = self.db.query(KubernetesCluster).filter(
            KubernetesCluster.id == cluster_id,
        ).first()
        if not cluster:
            raise NotFoundError("cluster", cluster_id)
        return cluster
