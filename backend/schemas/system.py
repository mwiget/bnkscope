"""
Pydantic schemas for the System / API domain.

Covers:
  - Application settings (batch update)
  - AWS authentication method configuration
  - System health, queue metrics, performance
"""

from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Settings
# =============================================================================

class SettingsBatchUpdate(BaseModel):
    """Request body for PUT /api/settings — batch update settings."""
    # Flat dict of key → value pairs
    # We accept Dict[str, Any] because setting values can be strings, bools, ints
    settings: dict[str, str] = Field(
        ..., description="Mapping of setting key → value"
    )




class SettingEntry(BaseModel):
    """Single setting entry in GET /api/settings response."""

    key: str
    value: str | None = None
    value_type: str | None = None
    description: str | None = None
    is_encrypted: bool = False


class SettingsResponse(BaseModel):
    """Response for GET /api/settings."""

    settings: dict[str, list[SettingEntry]] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    """Response for GET /api/system/version."""

    current_version: str
    latest_version: str
    update_available: bool
    commits_behind: int
    error: str | None = None





# =============================================================================
# System Health
# =============================================================================

class ServiceHealth(BaseModel):
    """Health status of an individual service.

    The ``workers`` / ``active_tasks`` fields went with Celery (Phase 4) — they
    were only ever populated for the queue.
    """
    status: str
    response_time_ms: float | None = None
    error: str | None = None


class SystemHealthResponse(BaseModel):
    """Response for GET /api/system/health."""
    services: dict[str, ServiceHealth]
    timestamp: str
    maintenance_mode: bool = False


# =============================================================================
# Config Import (from config_export.py)
# =============================================================================

# =============================================================================
# System Upgrade State (UP-003)
# =============================================================================

class UpgradeStateResponse(BaseModel):
    """Response for GET /api/system/upgrade/status — persisted upgrade state."""
    status: str = Field(description="in_progress | completed | failed | interrupted | none")
    old_version: str | None = None
    new_version: str | None = None
    started_at: str | None = Field(default=None, description="ISO 8601 timestamp")
    completed_at: str | None = Field(default=None, description="ISO 8601 timestamp, set on completion/failure")
    current_phase: str | None = Field(default=None, description="Current/last phase: start, pull, build, restart, migrate, verify, complete, failed")
    phase_label: str | None = Field(default=None, description="Human-readable phase label")
    pre_upgrade_commit: str | None = Field(default=None, description="Git commit SHA before upgrade (for rollback)")
    log: list[str] = Field(default_factory=list, description="Last N lines of upgrade output")


# =============================================================================
# Config Import (from config_export.py)
# =============================================================================

class ConfigImportRequest(BaseModel):
    """
    Request body for POST /api/clusters/{cluster_id}/bnk/import.

    Accepts a BNK configuration dict to import into a cluster.
    """
    config: dict[str, Any] = Field(
        ..., description="BNK configuration to import (from export YAML/JSON)"
    )
