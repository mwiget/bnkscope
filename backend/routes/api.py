"""
General API routes.

Thin HTTP handlers delegating to ApiService.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.config import settings
from core.errors import handle_route_errors
from database import get_db
from schemas.system import (
    SettingsBatchUpdate,
    SettingsResponse,
)
from services.api_service import ApiService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])

# ============================================================================
# Static / No-DB Endpoints
# ============================================================================

@router.get("/")
def root():
    """Root endpoint"""
    return {"message": "bnkscope API", "version": settings.VERSION, "docs": "/docs"}

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint with component status and warnings (PLAT-REL-004)."""
    return _build_health_response(db)

@router.get("/api/health")
def health_check_api(db: Session = Depends(get_db)):
    """Health check endpoint with component status and warnings (PLAT-REL-004)."""
    return _build_health_response(db)

def _build_health_response(db: Session) -> dict:
    """
    PLAT-REL-004: Enhanced health response with component checks and warnings.

    Returns operational status for monitoring integrations, including:
    - Individual component health
    - Warnings for degraded but non-fatal conditions

    Phase 4 left one component to check: the database. The broker and the
    worker pool this used to probe are in-process now — if they were down, so
    would be the process answering this request.
    """
    from sqlalchemy import text

    checks: dict[str, str] = {}
    warnings: list[dict[str, str]] = []
    overall = "healthy"

    # Check database
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unhealthy"
        overall = "unhealthy"

    response: dict = {
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(),
        "version": settings.VERSION,
        "checks": checks,
    }
    if warnings:
        response["warnings"] = warnings
    return response

# ============================================================================
# Service-Backed Endpoints
# ============================================================================

@router.get("/api/settings", response_model=SettingsResponse)
@handle_route_errors("get settings")
def get_settings(db: Session = Depends(get_db)):
    """Get all application settings"""
    return ApiService(db).get_settings()

@router.put("/api/settings/{key}")
@handle_route_errors("update setting")
def update_setting(key: str, value: str, db: Session = Depends(get_db)):
    """Update an application setting"""
    result = ApiService(db).update_setting(key, value)
    db.commit()
    return result

@router.put("/api/settings")
@handle_route_errors("batch update settings")
def batch_update_settings(body: SettingsBatchUpdate, db: Session = Depends(get_db)):
    """Batch update multiple application settings"""
    result = ApiService(db).batch_update_settings(body.settings)
    db.commit()
    return result


@router.get("/api/database/stats")
@handle_route_errors("get database stats")
def get_database_stats(db: Session = Depends(get_db)):
    """Get database statistics"""
    return ApiService(db).get_database_stats()
