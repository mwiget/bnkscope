"""
QKView routes — proxy BNK CWC QKView API through bnkscope.

Collection runs through an ephemeral curl pod scheduled on the cluster. The
operator-dispatch path went with the operator agent (bnkscope Phase 2).

Provides endpoints to create, list, monitor, download, and delete
QKView diagnostic tarballs from F5 BNK clusters.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.errors import handle_route_errors
from database import get_db
from services.kubernetes_service import KubernetesService
from services.qkview_service import (
    QKViewError,
    cleanup_client_pods,
)
from services.qkview_service import (
    cancel_qkview as legacy_cancel_qkview,
)
from services.qkview_service import (
    check_cwc_available as legacy_check_cwc_available,
)
from services.qkview_service import (
    check_setup_status as legacy_check_setup_status,
)
from services.qkview_service import (
    create_qkview as legacy_create_qkview,
)
from services.qkview_service import (
    delete_qkview as legacy_delete_qkview,
)
from services.qkview_service import (
    download_qkview as legacy_download_qkview,
)
from services.qkview_service import (
    get_qkview as legacy_get_qkview,
)
from services.qkview_service import (
    get_qkview_status as legacy_get_qkview_status,
)
from services.qkview_service import (
    list_qkviews as legacy_list_qkviews,
)
from services.qkview_service import (
    setup_cwc_api_certs as legacy_setup_cwc_api_certs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qkview", tags=["qkview"])

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class QKViewCreateRequest(BaseModel):
    cluster_id: int
    namespace: str | None = None
    timeout: str | None = None
    filename: str | None = None
    pod_patterns: list[str] | None = None
    include_core_files: bool = False
    core_files_max: int = 2
    core_files_since: str | None = None

class QKViewClusterRequest(BaseModel):
    cluster_id: int

class QKViewCheckResponse(BaseModel):
    """Response from GET /api/qkview/check."""
    available: bool
    message: str

    class Config:
        extra = "allow"

class QKViewListResponse(BaseModel):
    """Response from GET /api/qkview/list."""
    qkviews: list[dict[str, Any]]
    error: str | None = None

class QKViewCreateResponse(BaseModel):
    """Response from POST /api/qkview/create."""
    id: str | None = None
    filename: str | None = None
    status: str | None = None

    class Config:
        extra = "allow"

class QKViewDeleteResponse(BaseModel):
    """Response from DELETE /api/qkview/{qkview_id}."""
    deleted: bool | None = None
    success: bool | None = None

    class Config:
        extra = "allow"

class QKViewCancelResponse(BaseModel):
    """Response from POST /api/qkview/{qkview_id}/cancel."""
    cancelled: bool | None = None
    success: bool | None = None

    class Config:
        extra = "allow"

class QKViewCleanupResponse(BaseModel):
    """Response from POST /api/qkview/cleanup-pods."""
    cleaned: bool

    class Config:
        extra = "allow"

class QKViewGetResponse(BaseModel):
    """Response from GET /api/qkview/{qkview_id}."""
    id: str | None = None
    status: str | None = None
    filename: str | None = None

    class Config:
        extra = "allow"

class QKViewStatusResponse(BaseModel):
    """Response from GET /api/qkview/{qkview_id}/status."""
    status: str
    progress: int | None = None

    class Config:
        extra = "allow"

# ---------------------------------------------------------------------------
# Operator dispatch helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/check",
    response_model=QKViewCheckResponse,
)
async def check_cwc(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Check if the CWC QKView API is available on the cluster."""
    k8s_service = KubernetesService(db)
    return check_cwc_available(k8s_service, cluster_id)

# Keep the original function names as module-level aliases for mock.patch targets
# in integration tests (tests mock "routes.qkview.<name>")
check_cwc_available = legacy_check_cwc_available
check_setup_status = legacy_check_setup_status
setup_cwc_api_certs = legacy_setup_cwc_api_certs
setup_qkview_certs = legacy_setup_cwc_api_certs
list_qkviews = legacy_list_qkviews
create_qkview = legacy_create_qkview
get_qkview = legacy_get_qkview
get_qkview_status = legacy_get_qkview_status
download_qkview = legacy_download_qkview
delete_qkview = legacy_delete_qkview
cancel_qkview = legacy_cancel_qkview

@router.get(
    "/list",
    response_model=QKViewListResponse,
)
async def list_qkviews_endpoint(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """List all QKView jobs on the cluster."""
    k8s_service = KubernetesService(db)
    try:
        qkviews = list_qkviews(k8s_service, cluster_id)
        return {"qkviews": qkviews}
    except QKViewError as e:
        return {"qkviews": [], "error": str(e)}

@router.post(
    "/create",
    response_model=QKViewCreateResponse,
)
async def create_qkview_endpoint(
    request: QKViewCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a new QKView diagnostic collection."""
    k8s_service = KubernetesService(db)
    options: dict = {}
    if request.namespace:
        options["namespace"] = request.namespace
    if request.filename:
        options["filename"] = request.filename
    if request.pod_patterns:
        options["pod_patterns"] = request.pod_patterns
    if request.include_core_files:
        core_opts: dict = {"max_files": request.core_files_max}
        if request.core_files_since:
            core_opts["since"] = request.core_files_since
        options["core_files"] = core_opts

    result = create_qkview(k8s_service, request.cluster_id, options)
    return result

@router.get(
    "/{qkview_id}",
    response_model=QKViewGetResponse,
)
async def get_qkview_endpoint(
    qkview_id: str,
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Get details of a specific QKView."""
    k8s_service = KubernetesService(db)
    return get_qkview(k8s_service, cluster_id, qkview_id)

@router.get(
    "/{qkview_id}/status",
    response_model=QKViewStatusResponse,
)
async def get_qkview_status_endpoint(
    qkview_id: str,
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Get the status of a specific QKView job."""
    k8s_service = KubernetesService(db)
    return get_qkview_status(k8s_service, cluster_id, qkview_id)

@router.get("/{qkview_id}/download")
async def download_qkview_endpoint(
    qkview_id: str,
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Download the QKView tarball."""
    k8s_service = KubernetesService(db)
    data = download_qkview(k8s_service, cluster_id, qkview_id)
    return Response(
        content=data,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="qkview-{qkview_id}.tar.gz"',
        },
    )

@router.delete(
    "/{qkview_id}",
    response_model=QKViewDeleteResponse,
)
async def delete_qkview_endpoint(
    qkview_id: str,
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Delete a specific QKView."""
    k8s_service = KubernetesService(db)
    try:
        return delete_qkview(k8s_service, cluster_id, qkview_id)
    except QKViewError as e:
        # In-progress jobs raise QKViewError(409); surface the real status code
        # rather than falling through to a generic 500 (FEAT-0343 / ERR-0027).
        raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e

@router.post(
    "/{qkview_id}/cancel",
    response_model=QKViewCancelResponse,
)
async def cancel_qkview_endpoint(
    qkview_id: str,
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Cancel a running QKView job."""
    k8s_service = KubernetesService(db)
    try:
        return cancel_qkview(k8s_service, cluster_id, qkview_id)
    except QKViewError as e:
        # In-progress jobs raise QKViewError(409); surface the real status code
        # rather than falling through to a generic 500 (FEAT-0343 / ERR-0027).
        raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e

@router.post(
    "/cleanup-pods",
    response_model=QKViewCleanupResponse,
)
@handle_route_errors("cleanup qkview client pods")
def cleanup_pods_endpoint(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Clean up all qkview client (ephemeral curl) pods on the cluster."""
    k8s_service = KubernetesService(db)
    return cleanup_client_pods(k8s_service, cluster_id)
