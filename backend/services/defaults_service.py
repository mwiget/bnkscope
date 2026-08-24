"""
System Defaults Service

Manages application-wide default values stored in the database.
All configurable defaults are stored in ApplicationSetting table.

Sensible defaults are pre-populated on first run. Users can change them
via System > Defaults in the UI at any time.
"""
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from core.encryption import decrypt_value_or_none, encrypt_value
from models import ApplicationSetting

logger = logging.getLogger(__name__)

# Canonical upstream repository — where the update check looks for a newer
# VERSION. It used to point at f5devcentral/bnk-forge, so "an update is
# available" was answered by a different product's releases, one this tool
# shares no version line with.
#
# Forks and internal mirrors (e.g. a GitLab mirror behind a corporate network)
# override this with BNKSCOPE_REPO_URL so builds and version checks point at
# their own remote. The DB setting `system.update_repo_url` overrides both at
# runtime.
DEFAULT_REPO_URL = os.environ.get(
    "BNKSCOPE_REPO_URL", "https://github.com/mwiget/bnkscope"
)

#: Values that were once the default and are now wrong, keyed by setting. A
#: default is seeded once, so changing it here does nothing to a database that
#: already has a row — an install created before the fork would go on asking
#: bnk-forge whether bnkscope has an update, and be told yes, forever.
#: Rewritten on startup unless the operator has set something of their own.
SUPERSEDED_VALUES: dict[str, tuple[str, ...]] = {
    "system.update_repo_url": (
        "https://github.com/f5devcentral/bnk-forge",
        "https://github.com/f5devcentral/bnk-forge.git",
    ),
}

# ============================================================================
# Default Definitions
# ============================================================================
# These define ALL configurable defaults with sensible initial values.
# On first run, these are seeded into the database.
# Users can change them via System > Defaults in the UI.

SYSTEM_DEFAULTS = {
    # System Update Source
    "system.update_repo_url": {
        "value": DEFAULT_REPO_URL,
        "value_type": "string",
        "description": "GitHub repository URL for version checks (owner/repo format derived automatically)",
        "category": "system",
        "optional": True,
    },

    # Cloud Provider Default Regions
    "cloud.aws.default_region": {
        "value": "us-east-1",
        "value_type": "string",
        "description": "Fallback AWS region when a cluster and its stored credentials name none",
        "category": "cloud",
    },

    # Execution Settings
    "execution.max_retries": {
        "value": "3",
        "value_type": "int",
        "description": "Maximum retry attempts for failed operations",
        "category": "execution",
    },
    "execution.retry_delay": {
        "value": "5",
        "value_type": "int",
        "description": "Delay between retry attempts (seconds)",
        "category": "execution",
    },
}

def get_default(db: Session, key: str) -> Any:
    """
    Get a system default value from the database.

    Returns None if the setting is not found or empty.

    Args:
        db: Database session
        key: Setting key (e.g., "cloud.aws.default_region")

    Returns:
        The setting value (converted to appropriate type), or None if not configured
    """
    setting = db.query(ApplicationSetting).filter(
        ApplicationSetting.key == key
    ).first()

    if not setting or setting.value is None or setting.value == "":
        return None

    stored_value = setting.value
    if setting.is_encrypted and stored_value:
        stored_value = decrypt_value_or_none(stored_value) or ""
    if stored_value == "":
        return None

    # Get value type from definition
    value_type = "string"
    if key in SYSTEM_DEFAULTS:
        value_type = SYSTEM_DEFAULTS[key].get("value_type", "string")

    return _convert_value(stored_value, value_type)

def _convert_value(value: str, value_type: str) -> Any:
    """Convert string value to appropriate Python type."""
    if not value:
        return None
    if value_type == "int":
        return int(value)
    elif value_type == "float":
        return float(value)
    elif value_type == "bool":
        return value.lower() in ("true", "1", "yes")
    elif value_type == "json":
        import json
        return json.loads(value)
    return value

def get_all_defaults(db: Session) -> dict[str, Any]:
    """
    Get all system defaults organized by category.

    Returns:
        Dict with category -> settings mapping
    """
    # Get all settings from database
    settings = db.query(ApplicationSetting).filter(
        ApplicationSetting.key.in_(SYSTEM_DEFAULTS.keys())
    ).all()

    settings_map = {s.key: s for s in settings}

    result = {}
    for key, definition in SYSTEM_DEFAULTS.items():
        category = definition["category"]
        if category not in result:
            result[category] = {}

        # Get value from DB (decrypt if needed)
        db_setting = settings_map.get(key)
        value = db_setting.value if db_setting else ""
        if db_setting and db_setting.is_encrypted and value:
            value = decrypt_value_or_none(value) or ""

        # Convert value
        converted_value = _convert_value(value, definition.get("value_type", "string")) if value else None

        # Extract setting name from key
        setting_name = key.split(".", 1)[1].replace(".", "_") if "." in key else key

        # Check if optional
        is_optional = definition.get("optional", False)

        result[category][setting_name] = {
            "key": key,
            "value": converted_value,
            "raw_value": "" if definition.get("is_encrypted", False) else (value or ""),
            "value_type": definition.get("value_type", "string"),
            "description": definition["description"],
            "is_configured": bool(value),
            "is_optional": is_optional,
            "is_encrypted": bool(definition.get("is_encrypted", False)),
            "suggested_value": definition.get("suggested_value"),
        }

    return result

def set_default(db: Session, key: str, value: Any) -> bool:
    """
    Set a system default value.

    Args:
        db: Database session
        key: Setting key
        value: New value (will be converted to string for storage)

    Returns:
        True if successful
    """
    if key not in SYSTEM_DEFAULTS:
        logger.warning(f"Attempted to set unknown default: {key}")
        return False

    definition = SYSTEM_DEFAULTS[key]

    # Convert value to string for storage
    str_value = str(value) if value is not None else ""
    stored_value = str_value
    if definition.get("is_encrypted", False) and str_value:
        encrypted = encrypt_value(str_value)
        stored_value = encrypted or ""

    # Find or create setting
    setting = db.query(ApplicationSetting).filter(
        ApplicationSetting.key == key
    ).first()

    if setting:
        setting.value = stored_value
        setting.is_encrypted = bool(definition.get("is_encrypted", False))
        logger.info(f"Updated system default: {key}")
    else:
        setting = ApplicationSetting(
            key=key,
            value=stored_value,
            value_type=definition.get("value_type", "string"),
            description=definition["description"],
            category=definition["category"],
            is_encrypted=definition.get("is_encrypted", False),
        )
        db.add(setting)
        logger.info(f"Created system default: {key}")

    # ENG-006: No commit here — caller (route or batch) owns the transaction
    db.flush()
    return True

def set_defaults_batch(db: Session, updates: dict[str, Any]) -> dict[str, bool]:
    """
    Set multiple defaults at once.

    Args:
        db: Database session
        updates: Dict of key -> value pairs

    Returns:
        Dict of key -> success status
    """
    results = {}
    for key, value in updates.items():
        results[key] = set_default(db, key, value)
    return results

def seed_defaults(db: Session) -> int:
    """
    Seed default settings into database on first run.

    Creates settings with sensible defaults. Users can change them in the UI.
    Only creates settings that don't already exist.

    Args:
        db: Database session

    Returns:
        Number of settings seeded
    """
    seeded = 0
    corrected = 0

    for key, definition in SYSTEM_DEFAULTS.items():
        existing = db.query(ApplicationSetting).filter(
            ApplicationSetting.key == key
        ).first()

        if not existing:
            setting = ApplicationSetting(
                key=key,
                value=definition["value"],  # Empty string - user must configure
                value_type=definition.get("value_type", "string"),
                description=definition["description"],
                category=definition["category"],
                is_encrypted=definition.get("is_encrypted", False),
            )
            db.add(setting)
            seeded += 1
            logger.debug(f"Seeded default: {key}")
        elif existing.value in SUPERSEDED_VALUES.get(key, ()):
            # Not a user's choice — a stale default from before the fork.
            logger.info(
                "Replacing superseded default for %s: %s -> %s",
                key,
                existing.value,
                definition["value"],
            )
            existing.value = definition["value"]
            existing.description = definition["description"]
            corrected += 1

    if seeded or corrected:
        # ENG-006: Startup seed manages its own transaction
        db.commit()
        if seeded:
            logger.info(f"Seeded {seeded} system defaults")
        if corrected:
            logger.info(f"Corrected {corrected} superseded default(s)")

    return seeded

def check_required_configured(db: Session) -> dict[str, Any]:
    """
    Check if all required settings are configured.

    All settings are required EXCEPT those marked with optional=True.

    Args:
        db: Database session

    Returns:
        Dict with 'all_configured' bool and 'missing' list
    """
    missing = []

    for key, definition in SYSTEM_DEFAULTS.items():
        # Skip optional settings
        if definition.get("optional", False):
            continue

        setting = db.query(ApplicationSetting).filter(
            ApplicationSetting.key == key
        ).first()

        if not setting or not setting.value:
            missing.append({
                "key": key,
                "description": definition["description"],
                "category": definition["category"],
                "suggested_value": definition.get("suggested_value"),
            })

    return {
        "all_configured": len(missing) == 0,
        "missing": missing,
        "total_required": len([k for k, v in SYSTEM_DEFAULTS.items() if not v.get("optional", False)]),
        "configured_count": len([k for k, v in SYSTEM_DEFAULTS.items() if not v.get("optional", False)]) - len(missing),
    }
