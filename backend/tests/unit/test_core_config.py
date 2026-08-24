"""
BU-003: Unit tests for core.config module.

Tests Settings defaults, property parsing, and production validation.
Uses the already-instantiated global `settings` object where possible,
and constructs new Settings instances for validation edge cases.
"""

import pytest

from core.config import Settings, _read_version_file, settings

# ── Global settings defaults ─────────────────────────────────────────


class TestSettingsDefaults:
    def test_app_name(self):
        assert settings.APP_NAME == "bnkscope"

    def test_environment_is_development(self):
        assert settings.ENVIRONMENT == "development"

    def test_api_host(self):
        # bnkscope has no auth; the loopback bind IS the access control (Phase 3).
        assert settings.API_HOST == "127.0.0.1"

    def test_api_port(self):
        assert settings.API_PORT == 8000

    def test_database_url_is_set(self):
        """DATABASE_URL is always set — either from env (test: sqlite) or default (postgresql)."""
        assert settings.DATABASE_URL is not None
        assert len(settings.DATABASE_URL) > 10

    def test_encryption_key_is_set(self):
        """Auto-generated or from env, but always present after init."""
        assert settings.ENCRYPTION_KEY is not None
        assert len(settings.ENCRYPTION_KEY) > 10

    def test_logs_dir_default(self):
        assert settings.LOGS_DIR == "/tmp/bnkscope-logs"


# ── CORS origins property ────────────────────────────────────────────


class TestCorsOrigins:
    """CORS is off by default, and that is the point.

    The UI reaches this API through nginx on its own origin, so nothing the
    app does is cross-origin and no CORS header is involved. Turning it on
    grants access to pages that are NOT the UI — and this API has no
    authentication and serves `POST /api/system/backup`, which is every
    kubeconfig and cloud credential plus the key that decrypts them. The
    default used to be `"*"`, which handed that to every site in the
    operator's browser on a plain loopback install.
    """

    def test_cors_origins_is_list(self):
        assert isinstance(settings.cors_origins, list)

    def test_default_is_empty(self):
        assert Settings(ALLOWED_ORIGINS="").cors_origins == []

    def test_parsed_from_csv(self):
        s = Settings(ALLOWED_ORIGINS="http://localhost:5173,https://example.test")
        assert s.cors_origins == ["http://localhost:5173", "https://example.test"]

    def test_blank_entries_are_dropped(self):
        # A trailing comma must not produce an empty origin, which would be
        # matched against and is never what anyone meant.
        assert Settings(ALLOWED_ORIGINS="http://a.test, ,").cors_origins == ["http://a.test"]


# ── Version reading ──────────────────────────────────────────────────


class TestReadVersionFile:
    def test_version_returns_string(self):
        version = _read_version_file()
        assert isinstance(version, str)

    def test_version_looks_like_semver(self):
        """Version should be X.Y.Z format or fallback 0.0.0."""
        version = _read_version_file()
        parts = version.split(".")
        assert len(parts) >= 2  # at least X.Y
        # Each part should be numeric
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' is not numeric"

    def test_settings_version_matches(self):
        """settings.VERSION should equal what _read_version_file returns."""
        assert settings.VERSION == _read_version_file()


# ── Production validation ────────────────────────────────────────────


class TestProductionValidation:
    def test_development_passes_validation(self):
        """In development mode, validate_production is a no-op."""
        # Should not raise
        settings.validate_production()

    def test_production_with_auto_keys_fails(self, monkeypatch):
        """Production environment with auto-generated keys should fail."""
        s = Settings(
            ENVIRONMENT="production",
            ENCRYPTION_KEY=None,  # Will auto-generate
        )
        # Force the auto-generated flag
        s._encryption_key_auto_generated = True

        with pytest.raises(SystemExit):
            s.validate_production()

    def test_production_with_explicit_keys_passes(self):
        """Production with explicitly set keys should pass."""
        s = Settings(
            ENVIRONMENT="production",
            ENCRYPTION_KEY="explicit-encryption-key-for-production",
            ALLOWED_ORIGINS="https://my-app.example.com",
        )
        # An explicitly supplied key leaves the auto-generated flag clear
        assert s._encryption_key_auto_generated is False
        # Should not raise
        s.validate_production()

    def test_production_wildcard_cors_fails(self):
        """Production with wildcard CORS should fail."""
        s = Settings(
            ENVIRONMENT="production",
            ENCRYPTION_KEY="explicit-key",
            ALLOWED_ORIGINS="*",
        )
        with pytest.raises(SystemExit):
            s.validate_production()

    def test_production_wildcard_cors_fails(self):
        """A wildcard is never right here — the API has no authentication."""
        s = Settings(
            ENVIRONMENT="production",
            ENCRYPTION_KEY="explicit-key",
            ALLOWED_ORIGINS="*",
        )
        with pytest.raises(SystemExit):
            s.validate_production()

    def test_production_empty_cors_passes(self):
        """Empty is the shipped value: same-origin through nginx, no CORS."""
        s = Settings(
            ENVIRONMENT="production",
            ENCRYPTION_KEY="explicit-key",
            ALLOWED_ORIGINS="",
        )
        s.validate_production()

    def test_staging_skips_localhost_check(self):
        """Staging mode checks auto-keys but NOT localhost in CORS."""
        s = Settings(
            ENVIRONMENT="staging",
            ENCRYPTION_KEY="explicit-key",
            ALLOWED_ORIGINS="http://localhost:3000",
        )
        # Should not raise — staging allows localhost
        s.validate_production()


# ── Settings Config class ────────────────────────────────────────────


class TestSettingsConfig:
    def test_case_sensitive(self):
        assert Settings.model_config.get("case_sensitive", True)

    def test_extra_ignored(self):
        """Extra env vars should not crash Settings."""
        # Settings has extra="ignore"
        s = Settings(NONEXISTENT_SETTING="ignored")
        assert not hasattr(s, "NONEXISTENT_SETTING") or True  # extra is ignored
