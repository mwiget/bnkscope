"""Maintenance mode for backup/restore operations.

This lived in Redis so multiple worker processes agreed on the flag. bnkscope
is one process (Phase 4), so the flag is a module-level value guarded by a lock.

The 10-minute TTL is kept deliberately: it is the safety net for a restore that
crashes without clearing the flag, and that failure mode did not go away just
because the storage did.
"""

import logging
import threading
import time
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

MAINTENANCE_TTL_SECONDS = 600  # 10 minutes safety timeout

_lock = threading.Lock()
# (expires_at_monotonic, {"message": ..., "started_at": ...}) or None
_state: tuple[float, dict[str, str]] | None = None


def set_maintenance_mode(message: str = "System maintenance in progress") -> None:
    """Enable maintenance mode for at most ``MAINTENANCE_TTL_SECONDS``."""
    global _state
    with _lock:
        _state = (
            time.monotonic() + MAINTENANCE_TTL_SECONDS,
            {"message": message, "started_at": datetime.now(UTC).isoformat()},
        )
    logger.warning("Maintenance mode ENABLED: %s", message)


def clear_maintenance_mode() -> None:
    """Disable maintenance mode."""
    global _state
    with _lock:
        _state = None
    logger.info("Maintenance mode CLEARED")


def get_maintenance_status() -> dict[str, str] | None:
    """Return ``{message, started_at}`` while in maintenance, else ``None``.

    Runs from maintenance_middleware on every request, so it must never raise.
    """
    global _state
    with _lock:
        if _state is None:
            return None
        expires_at, data = _state
        if expires_at <= time.monotonic():
            _state = None
            logger.warning("Maintenance mode expired via TTL — clearing")
            return None
        return dict(data)


def is_maintenance_mode() -> bool:
    """Check if the system is in maintenance mode."""
    return get_maintenance_status() is not None
