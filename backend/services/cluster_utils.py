"""
Shared Kubernetes Cluster Utilities

DRY utilities for cluster operations used by multiple services
(kubernetes_service.py, helm_service.py, etc.)
"""
import logging
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from core.encryption import decrypt_value
from models import KubernetesCluster
from services.kubeconfig_normalizer import (
    NormalizationSource,
    normalize_kubeconfig,
)

logger = logging.getLogger(__name__)


def _try_backfill_kubeconfig_from_source_module(
    cluster: KubernetesCluster, db: Session
) -> bool:
    """If an auto-registered cluster has no kubeconfig, try to read one from
    its source module's terraform outputs. Returns True if the cluster was
    updated (caller should commit).

    Also corrects ``cluster.context`` to match the kubeconfig's
    current-context — the auto-register path used to default it to the
    cluster's display name, which doesn't match the IBM-issued context.
    """
    meta = cluster.meta_data or {}
    source_module_id = meta.get("source_module_id")
    if not source_module_id:
        return False

    from core.encryption import encrypt_value
    from models import ProjectModule
    from services.cluster_management_service import ClusterManagementService

    module = db.query(ProjectModule).filter(ProjectModule.id == int(source_module_id)).first()
    if module is None:
        return False

    yaml_text = ClusterManagementService._decode_module_kubeconfig_output(module.outputs or {})
    if not yaml_text:
        return False

    # Assert invariant — module outputs must be portable; hard-fail if not so the
    # bug surfaces loudly (kubeconfig_invariant_violation).
    try:
        yaml_text = normalize_kubeconfig(yaml_text, source=NormalizationSource.MODULE_OUTPUT)
    except Exception as norm_exc:
        logger.error(
            "kubeconfig_invariant_violation: module %s outputs contain non-portable kubeconfig "
            "for cluster %s: %s",
            source_module_id, cluster.name, norm_exc,
        )
        raise

    cluster.kubeconfig_encrypted = encrypt_value(yaml_text)
    new_context = ClusterManagementService._kubeconfig_default_context(yaml_text)
    if new_context:
        cluster.context = new_context
    logger.info(
        "Backfilled kubeconfig for cluster %s (id=%s) from module %s outputs",
        cluster.name, cluster.id, source_module_id,
    )
    return True


def get_cluster(db: Session, cluster_id: int) -> KubernetesCluster:
    """
    Get cluster configuration from database.

    Args:
        db: Database session
        cluster_id: Cluster ID

    Returns:
        KubernetesCluster object

    Raises:
        ValueError: If cluster not found
    """
    cluster = db.query(KubernetesCluster).filter(
        KubernetesCluster.id == cluster_id
    ).first()
    if not cluster:
        raise ValueError(f"Cluster {cluster_id} not found")
    return cluster


@contextmanager
def kubeconfig_for_cluster(
    cluster: KubernetesCluster, db: Session
) -> Generator[str, None, None]:
    """
    Context manager that creates a temporary kubeconfig file and guarantees cleanup.

    Usage:
        with kubeconfig_for_cluster(cluster, db) as kubeconfig_path:
            api = kr8s.api(kubeconfig=kubeconfig_path)
            # ... use api ...
        # temp file is automatically deleted here

    Yields:
        str: Path to the temporary kubeconfig file
    """
    kubeconfig_path = _write_kubeconfig(cluster, db)
    try:
        yield kubeconfig_path
    finally:
        _cleanup_kubeconfig(kubeconfig_path)




def _write_kubeconfig(cluster: KubernetesCluster, db: Session) -> str:
    """
    Internal: write kubeconfig to a temp file and return the path.
    Sets up SSH tunnels and AWS credentials as needed.

    Returns:
        str: Path to the temporary kubeconfig file. Caller must delete.
    """
    if not cluster.kubeconfig_encrypted:
        if _try_backfill_kubeconfig_from_source_module(cluster, db):
            db.commit()
            db.refresh(cluster)
        if not cluster.kubeconfig_encrypted:
            raise ValueError(f"Cluster {cluster.name} has no kubeconfig configured")

    # Decrypt kubeconfig
    kubeconfig_content = decrypt_value(cluster.kubeconfig_encrypted)
    if not kubeconfig_content:
        raise ValueError("Failed to decrypt kubeconfig")

    # Defense-in-depth: assert portability before writing to disk.
    # A KubeconfigUnportableError here means a legacy DB row survived pre-fix;
    # the error message instructs the user to re-upload.
    kubeconfig_content = normalize_kubeconfig(
        kubeconfig_content, source=NormalizationSource.INTERNAL_REREAD
    )

    # For EKS/AWS clusters, set AWS credentials in environment
    # The kubeconfig's 'aws eks get-token' command will use these
    if cluster.cloud_provider in ["eks", "aws"]:
        from services.credentials_service import get_cloud_credentials_env
        aws_env = get_cloud_credentials_env(cluster, db)

        # Set AWS credentials in current process environment
        for key, value in aws_env.items():
            if key.startswith('AWS_'):
                os.environ[key] = value

        logger.info(f"Set AWS credentials for EKS cluster {cluster.name}")

    # For GKE/GCP clusters, mint an OAuth access token via google-auth and
    # rewrite the kubeconfig user to a static bearer token.  Required for
    # shell-out clients (helm, kubectl) — they don't share the in-process
    # rewrite done by KubernetesService, so they hit the kubeconfig's
    # `gke-gcloud-auth-plugin` exec block which isn't installed in the
    # backend container.  Mirrors the EKS token-rewrite path on KubernetesService.
    if cluster.cloud_provider in ["gke", "gcp"]:
        from services.credentials_service import get_gcp_service_account_info
        sa_info = get_gcp_service_account_info(cluster, db)
        if not sa_info:
            logger.warning(
                "No GCP service-account credentials configured for cluster %s; "
                "shell-out clients will fail without gke-gcloud-auth-plugin in "
                "the container",
                cluster.name,
            )
        else:
            try:
                token = _generate_gcp_token(sa_info)
                if token:
                    import yaml as yaml_lib
                    kubeconfig_dict = yaml_lib.safe_load(kubeconfig_content)
                    for user_entry in kubeconfig_dict.get("users", []):
                        user_entry["user"] = {"token": token}
                    kubeconfig_content = yaml_lib.dump(
                        kubeconfig_dict, default_flow_style=False
                    )
                    logger.info(
                        "Injected google-auth-generated bearer token into "
                        "kubeconfig for GKE cluster %s", cluster.name,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to generate google-auth GCP token for %s, "
                    "falling back to exec plugin: %s", cluster.name, e,
                )

    # Create temporary kubeconfig file
    fd, kubeconfig_path = tempfile.mkstemp(suffix='.yaml', prefix='kubeconfig-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(kubeconfig_content)
    except Exception:
        # If write fails, clean up the file descriptor
        try:
            os.close(fd)
        except OSError:
            pass
        _cleanup_kubeconfig(kubeconfig_path)
        raise
    return kubeconfig_path


def _cleanup_kubeconfig(kubeconfig_path: str | None) -> None:
    """Safely delete a temporary kubeconfig file."""
    if kubeconfig_path:
        try:
            os.unlink(kubeconfig_path)
        except OSError:
            pass


def _generate_gcp_token(sa_info: dict) -> str | None:
    """
    Mint a GKE-compatible OAuth access token from a GCP service-account key dict.

    Python-native equivalent of `gke-gcloud-auth-plugin`.  Returns a Google
    OAuth2 access token (~1h TTL) with the cloud-platform scope, which GKE
    accepts as a bearer.  Returns None if google-auth is not importable.

    Kept module-private; KubernetesServiceBase has its own copy because the
    in-process Python-client rewrite predates this shared utility.  The two
    are intentionally identical — collapse later if a refactor warrants it.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError:
        logger.warning("google-auth not available — cannot generate GCP token natively")
        return None

    credentials = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(Request())
    return credentials.token


