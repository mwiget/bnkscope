"""
SQLAlchemy models for bnkscope.

Split into domain-specific files for maintainability. This barrel re-exports
them so `from models import X` works regardless of which file X lives in.
"""

# Re-export Base for Alembic and any direct users
from database import Base

# --- Alerts ---
from models.alert import (
    AlertChannel,
    AlertHistory,
)

# --- BNK release registry ---
from models.bnk_release import (
    BnkRelease,
)

# --- Status enums ---
from models.enums import (
    AlertStatus,
    ClusterStatus,
    ReleaseSourceType,
)

# --- Kubernetes and F5 BNK networking ---
from models.kubernetes import (
    KubernetesCluster,
)

# --- System: settings, credentials, notifications ---
from models.system import (
    ApplicationSetting,
    CloudCredentialTemplate,
    Notification,
)

__all__ = [
    "Base",
    # enums
    "AlertStatus",
    "ClusterStatus",
    "ReleaseSourceType",
    # kubernetes
    "KubernetesCluster",
    # system
    "ApplicationSetting",
    "CloudCredentialTemplate",
    "Notification",
    # alerts
    "AlertChannel",
    "AlertHistory",
    # bnk_release
    "BnkRelease",
]
