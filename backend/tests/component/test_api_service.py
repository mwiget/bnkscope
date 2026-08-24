"""
BC-034: Component tests for ApiService — core API service layer.

Tests cover: get_provider_summary, get_sync_status, get_settings,
update_setting, batch_update_settings, set_aws_auth_method,
get_aws_auth_method, get_database_stats, _upsert_setting.
Uses real SQLite DB via `db` fixture.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BadRequestError, NotFoundError
from models import ApplicationSetting
from services.api_service import ApiService

# ── Helpers ──────────────────────────────────────────────────────────

def _create_setting(db, key, value, category="general", is_encrypted=False):
    setting = ApplicationSetting(
        key=key, value=value, category=category,
        description=f"Setting {key}", is_encrypted=is_encrypted,
    )
    db.add(setting)
    db.flush()
    return setting

# ── get_settings / update_setting ────────────────────────────────────

class TestSettings:
    def test_get_settings_empty(self, db):
        svc = ApiService(db)
        result = svc.get_settings()
        assert result["settings"] == {}

    def test_get_settings_grouped_by_category(self, db):
        _create_setting(db, "aws.region", "us-east-1", category="aws")
        _create_setting(db, "general.theme", "dark", category="general")

        svc = ApiService(db)
        result = svc.get_settings()
        assert "aws" in result["settings"]
        assert "general" in result["settings"]

    def test_deprecated_settings_excluded(self, db):
        _create_setting(db, "old.key", "value", category="deprecated")

        svc = ApiService(db)
        result = svc.get_settings()
        assert "deprecated" not in result["settings"]

    def test_update_existing_setting(self, db):
        _create_setting(db, "aws.region", "us-east-1", category="aws")

        svc = ApiService(db)
        result = svc.update_setting("aws.region", "eu-west-1")
        assert result["key"] == "aws.region"
        assert result["value"] == "eu-west-1"

    def test_update_nonexistent_setting_raises(self, db):
        svc = ApiService(db)
        with pytest.raises(NotFoundError):
            svc.update_setting("nonexistent.key", "value")

# ── batch_update_settings ────────────────────────────────────────────

class TestBatchUpdateSettings:
    def test_update_existing(self, db):
        _create_setting(db, "a.key", "old")

        svc = ApiService(db)
        result = svc.batch_update_settings({"a.key": "new"})
        assert result["success"] is True
        assert "a.key" in result["updated"]

    def test_create_new_setting(self, db):
        svc = ApiService(db)
        result = svc.batch_update_settings({"new.key": "value"})
        assert "new.key" in result["updated"]

    def test_mixed_update_and_create(self, db):
        _create_setting(db, "existing", "old")

        svc = ApiService(db)
        result = svc.batch_update_settings({
            "existing": "updated",
            "brand_new": "fresh",
        })
        assert len(result["updated"]) == 2

# ── set_aws_auth_method ──────────────────────────────────────────────


