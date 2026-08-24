"""Maintenance mode — in-process flag with a TTL safety net.

This used to be a Redis key with an EXPIRE. Phase 4 moved it in-process; the
TTL survived because the failure it guards against (a restore that dies without
clearing the flag, leaving the API permanently refusing requests) did not.
"""

import time

import pytest

from core import maintenance


@pytest.fixture(autouse=True)
def _clean_flag():
    maintenance.clear_maintenance_mode()
    yield
    maintenance.clear_maintenance_mode()


class TestMaintenanceFlag:
    def test_starts_clear(self):
        assert maintenance.is_maintenance_mode() is False
        assert maintenance.get_maintenance_status() is None

    def test_set_then_clear(self):
        maintenance.set_maintenance_mode("Restoring from backup")
        assert maintenance.is_maintenance_mode() is True

        status = maintenance.get_maintenance_status()
        assert status is not None
        assert status["message"] == "Restoring from backup"
        assert status["started_at"]

        maintenance.clear_maintenance_mode()
        assert maintenance.is_maintenance_mode() is False

    def test_default_message(self):
        maintenance.set_maintenance_mode()
        status = maintenance.get_maintenance_status()
        assert status is not None
        assert "maintenance" in status["message"].lower()

    def test_status_is_a_copy(self):
        """Callers must not be able to mutate the stored flag."""
        maintenance.set_maintenance_mode("original")
        status = maintenance.get_maintenance_status()
        assert status is not None
        status["message"] = "tampered"

        again = maintenance.get_maintenance_status()
        assert again is not None
        assert again["message"] == "original"


class TestTTLSafetyNet:
    def test_expires_without_an_explicit_clear(self, monkeypatch):
        """A restore that dies mid-flight must not wedge the API forever."""
        monkeypatch.setattr(maintenance, "MAINTENANCE_TTL_SECONDS", 0.05)
        maintenance.set_maintenance_mode("crashed restore")
        assert maintenance.is_maintenance_mode() is True

        time.sleep(0.1)
        assert maintenance.is_maintenance_mode() is False
        assert maintenance.get_maintenance_status() is None

    def test_expiry_frees_the_slot_for_a_new_operation(self, monkeypatch):
        monkeypatch.setattr(maintenance, "MAINTENANCE_TTL_SECONDS", 0.05)
        maintenance.set_maintenance_mode("first")
        time.sleep(0.1)
        assert maintenance.is_maintenance_mode() is False

        monkeypatch.setattr(maintenance, "MAINTENANCE_TTL_SECONDS", 600)
        maintenance.set_maintenance_mode("second")
        status = maintenance.get_maintenance_status()
        assert status is not None
        assert status["message"] == "second"
