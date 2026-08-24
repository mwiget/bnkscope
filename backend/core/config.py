"""
Configuration management with Pydantic validation
Ensures all required environment variables are set and validated at startup

NOTE: Configurable settings (like cloud regions) should NOT have defaults here.
They should come from the database via services.defaults_service.get_default().
This file is for infrastructure/bootstrap settings only.
"""
import logging
import os
from collections.abc import Callable
from typing import Any, Literal

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# BE-007: Directory for persisting auto-generated keys across restarts
_KEYS_DIR = os.environ.get("KEYS_DIR", "/app/keys")


def _read_version_file() -> str:
    """Read version from VERSION file (source of truth)."""
    version_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION"),  # /app/VERSION
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION"),  # repo root
    ]
    for path in version_paths:
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    return "0.0.0"  # fallback if VERSION file not found


def _persist_or_load_key(filename: str, generate_fn: Callable[[], str]) -> tuple[str, bool]:
    """
    BE-007: Load a key from persistent storage, or generate and save a new one.
    Returns (key_value, was_auto_generated).
    """
    key_path = os.path.join(_KEYS_DIR, filename)
    try:
        if os.path.exists(key_path):
            with open(key_path) as f:
                key = f.read().strip()
            if key:
                return key, True  # Loaded from file (still auto-generated, not user-provided)
    except (OSError, PermissionError) as e:
        logger.warning(f"Could not read {key_path}: {e}")

    # Generate new key
    key = generate_fn()

    # Try to persist it
    try:
        os.makedirs(_KEYS_DIR, exist_ok=True)
        with open(key_path, "w") as f:
            f.write(key)
        os.chmod(key_path, 0o600)  # Read/write only by owner
        logger.info(f"Persisted auto-generated key to {key_path}")
    except (OSError, PermissionError) as e:
        logger.warning(f"Could not persist key to {key_path}: {e} — key will be lost on restart")

    return key, True  # Auto-generated


class Settings(BaseSettings):
    """Application settings with validation"""

    # Application
    APP_NAME: str = "bnkscope"
    VERSION: str = _read_version_file()
    ENVIRONMENT: str = "development"  # development, staging, production

    # Security - CORS.
    #
    # Empty by default, and that is the correct value for the shipped product:
    # the browser never talks to this API cross-origin. The UI uses relative
    # paths (`lib/api/client.ts` has no baseURL) and nginx proxies `/api/` to
    # here, so every request the app makes is same-origin and CORS never
    # applies to it.
    #
    # What CORS *would* do is let any other page the operator has open talk to
    # this API — which has no authentication, and serves an archive of every
    # kubeconfig and cloud credential plus the key that decrypts them
    # (`POST /api/system/backup`). The bind address is the access control, and
    # a wildcard here hands it to every site in the browser.
    #
    # Set it only to run a dev server against a container backend, e.g.
    # ALLOWED_ORIGINS=http://localhost:5173 for `vite dev`.
    ALLOWED_ORIGINS: str = ""

    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list, dropping blanks.

        An empty list means no CORS middleware at all — see `main.py`. That is
        not the same as `["*"]`, which allows everyone.
        """
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # API Configuration.
    # bnkscope has no authentication (Phase 3) — it is a local single-user
    # tool and the bind address IS the access control. See backend/Dockerfile.
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    # Database. SQLite in a single file under the state volume — bnkscope is a
    # single-process, single-user tool (Phase 4), so Postgres bought nothing but
    # a second container to run. Override for a different path or engine.
    DATABASE_URL: str = "sqlite:////app/data/bnkscope.db"

    # Paths
    LOGS_DIR: str = "/tmp/bnkscope-logs"

    # Encryption key for kubeconfigs and cloud credentials at rest.
    ENCRYPTION_KEY: str | None = None

    # LLM gateway observability — in-cluster Loki that carries the
    # per-request llm-gateway log stream. Queries are proxied through the
    # cluster's K8s API-server service-proxy, so Loki need not be exposed.
    LOKI_NAMESPACE: str = "llm-egress"
    LOKI_SERVICE: str = "loki"
    LOKI_PORT: int = 3100
    LOKI_SCHEME: Literal["http", "https"] = "http"

    _encryption_key_auto_generated: bool = False

    class Config:
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars (e.g. INFRACOST_API_KEY, HOST_REPO_PATH) without crashing

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # BE-007: Handle ENCRYPTION_KEY — persist to file so encrypted data survives restarts
        # NOTE: ENCRYPTION_KEY must be a valid Fernet key (44-byte base64-encoded)
        # Use Fernet.generate_key() to create valid keys
        if self.ENCRYPTION_KEY is None:
            from cryptography.fernet import Fernet
            key, auto = _persist_or_load_key("encryption.key", lambda: Fernet.generate_key().decode())
            self.ENCRYPTION_KEY = key
            self._encryption_key_auto_generated = auto
            if self.ENVIRONMENT == "development":
                logger.info("Using auto-generated ENCRYPTION_KEY (persisted to /app/keys/)")
        else:
            self._encryption_key_auto_generated = False

    def validate_production(self) -> None:
        """
        SEC-006: Validate production-specific requirements.
        In production/staging, FAIL FAST if critical security settings are missing.
        """
        if self.ENVIRONMENT not in ("staging", "production"):
            return

        issues = []

        # SEC-006: Auto-generated keys are not acceptable in production
        if self._encryption_key_auto_generated:
            issues.append(
                "ENCRYPTION_KEY was not explicitly set — set it as an environment variable"
            )

        # A wildcard is refused outright at startup (see main.py); this keeps
        # the production checklist honest about why.
        if "*" in self.ALLOWED_ORIGINS:
            issues.append(
                "ALLOWED_ORIGINS contains '*' (wildcard) — this API has no "
                "authentication; name the origins or leave it empty"
            )

        if issues:
            logger.error("=" * 60)
            logger.error("FATAL: Production configuration errors detected")
            logger.error("=" * 60)
            for issue in issues:
                logger.error(f"  ✗ {issue}")
            logger.error("")
            logger.error("To fix: set these as environment variables in docker-compose.yml.")
            logger.error("  ENCRYPTION_KEY=$(python3 -c \"import secrets; print(secrets.token_hex(16))\")")
            logger.error("See: docs/DEPLOYMENT.md")
            logger.error("=" * 60)
            raise SystemExit(1)

    def validate_all(self) -> None:
        """Run all validations"""
        logger.info(f"Configuration: env={self.ENVIRONMENT}, db={self.DATABASE_URL}, cors={self.cors_origins}")

        # SEC-006: Fail fast in production if security settings are missing
        self.validate_production()


# Create global settings instance
settings = Settings()

# Run validation on import
settings.validate_all()
