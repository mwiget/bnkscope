"""
API Service — DB and business logic for general API endpoints.

Extracted from routes/api.py to separate HTTP handling from domain logic.

Covers:
- Application settings CRUD (get, update, batch update)
- AWS authentication method management
- Sync job status/history
- Cloud provider summary
- Database statistics
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.cache import cache
from core.encryption import encrypt_value
from core.errors import NotFoundError
from models import (
    ApplicationSetting,
)

logger = logging.getLogger(__name__)

# Keys that should be encrypted at rest
ENCRYPTED_SETTING_KEYS = {
    'aws.secret_access_key',
    'aws.session_token',
    'module_library.git_token',
}

class ApiService:
    """Service layer for general API operations."""

    def __init__(self, db: Session):
        self.db = db

    # ================================================================
    # Sync Status
    # ================================================================

    # ================================================================
    # Application Settings
    # ================================================================

    def get_settings(self) -> dict[str, Any]:
        """Get all application settings grouped by category."""
        settings = self.db.query(ApplicationSetting).order_by(
            ApplicationSetting.category, ApplicationSetting.key
        ).all()

        settings_by_category: dict[str, list] = {}
        for setting in settings:
            if setting.category == "deprecated":
                continue
            if setting.category not in settings_by_category:
                settings_by_category[setting.category] = []
            settings_by_category[setting.category].append({
                "key": setting.key,
                "value": setting.value,
                "value_type": setting.value_type,
                "description": setting.description,
                "is_encrypted": setting.is_encrypted
            })

        return {"settings": settings_by_category}

    def update_setting(self, key: str, value: str) -> dict[str, Any]:
        """Update a single application setting."""
        setting = self.db.query(ApplicationSetting).filter(
            ApplicationSetting.key == key
        ).first()
        if not setting:
            raise NotFoundError("setting", key)

        setting.value = value
        setting.updated_at = datetime.now(UTC)

        if "interval" in key:
            logger.info("Sync interval changed, scheduler restart may be required...")

        return {"message": "Setting updated successfully", "key": key, "value": value}

    def batch_update_settings(self, settings_dict: dict) -> dict[str, Any]:
        """Batch update multiple application settings."""
        updated = []
        errors = []

        for key, value in settings_dict.items():
            try:
                setting = self.db.query(ApplicationSetting).filter(
                    ApplicationSetting.key == key
                ).first()
                if setting:
                    setting.value = value
                    setting.updated_at = datetime.now(UTC)
                    updated.append(key)
                else:
                    category = key.split('.')[0] if '.' in key else "general"
                    new_setting = ApplicationSetting(
                        key=key, value=value, value_type="string",
                        description=f"Setting for {key}", category=category
                    )
                    self.db.add(new_setting)
                    updated.append(key)
            except Exception as e:
                errors.append({"key": key, "error": str(e)})

        self.db.flush()
        return {
            "success": True,
            "message": f"Updated {len(updated)} setting(s)",
            "updated": updated,
            "errors": errors
        }

    # ================================================================
    # AWS Auth Method
    # ================================================================

    def _upsert_setting(self, key: str, value: str, description: str = "",
                        category: str = "aws", should_encrypt: bool = False) -> None:
        """Upsert an ApplicationSetting row."""
        setting = self.db.query(ApplicationSetting).filter(
            ApplicationSetting.key == key
        ).first()
        stored_value = encrypt_value(value) if should_encrypt and value else value
        if setting:
            setting.value = stored_value
            if should_encrypt:
                setting.is_encrypted = True
        else:
            self.db.add(ApplicationSetting(
                key=key, value=stored_value, description=description,
                category=category, is_encrypted=should_encrypt
            ))


    # ================================================================
    # Database Stats
    # ================================================================

    def get_database_stats(self) -> dict[str, Any]:
        """Size on disk and row counts, per table (cached 2 min).

        The table list comes from the live ORM metadata rather than a literal
        UNION, which is how the previous version came to count `k8s_gateways`
        and `sync_jobs` — two tables nothing writes — while the UI above it
        asked for `tasks`, `deployment_logs` and `audit_logs`, none of which
        exist any more. Neither half could be right about the other.
        """
        cache_key = "database_stats"
        cached = cache.get(cache_key)
        if cached:
            return cached

        from models import Base

        tables: dict[str, dict[str, int]] = {}
        for name in sorted(Base.metadata.tables):
            try:
                rows = self.db.execute(
                    text(f'SELECT COUNT(*) FROM "{name}"')  # noqa: S608 — name is ORM metadata
                ).scalar()
            except Exception:  # noqa: BLE001 — a table the file predates is a skip
                logger.debug("Could not count rows in %s", name, exc_info=True)
                continue
            tables[name] = {"rows": int(rows or 0)}

        # SQLite reports its own size; page_count * page_size is exact and
        # needs no filesystem access, which matters because the database lives
        # on a volume the backend only knows by URL.
        try:
            page_count = self.db.execute(text("PRAGMA page_count")).scalar() or 0
            page_size = self.db.execute(text("PRAGMA page_size")).scalar() or 0
            size_mb = round((page_count * page_size) / (1024 * 1024), 2)
        except Exception:  # noqa: BLE001 — not SQLite, or PRAGMA unavailable
            size_mb = 0.0

        response = {
            "size_mb": size_mb,
            "tables": tables,
            "cached_at": datetime.now(UTC).isoformat() + "Z",
        }
        cache.set(cache_key, response, ttl_seconds=120)
        return response

