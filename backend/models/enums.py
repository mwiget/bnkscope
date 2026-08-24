"""String enums for the status values bnkscope stores.

`StrEnum` members *are* strings, so they serialise to the same bare values
already in the database's `String(50)` columns:

    ClusterStatus.ACTIVE == "active"            # True
    ClusterStatus.ACTIVE.value                  # "active"
    json.dumps({"s": ClusterStatus.ACTIVE})     # '{"s": "active"}'

This file carried 35 enums when it was inherited; 30 described a pipeline that
no longer exists — modules, tasks, stacks, drift checks, benchmarks, bare-metal
deployments — and had no reader outside their own definitions.
"""

from enum import StrEnum

# ---------------------------------------------------------------------------
# ClusterStatus — status of a K8s cluster connection
# ---------------------------------------------------------------------------

class ClusterStatus(StrEnum):
    """Status values for ``K8sCluster.status``."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    CONNECTING = "connecting"

# ---------------------------------------------------------------------------
# AlertStatus — status of an alert notification
# ---------------------------------------------------------------------------

class AlertStatus(StrEnum):
    """Status values for ``AlertHistory.status``."""

    SENT = "sent"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"

# ---------------------------------------------------------------------------
# HealthSeverity — canonical operational health (PLAT-REL-001)
# ---------------------------------------------------------------------------

class HealthSeverity(StrEnum):
    """Canonical health severity for any operational entity.

    Answers: "How broken is this thing right now?"

    Ordering (worst → best): unhealthy < degraded < unknown < healthy

    Replaces ad-hoc strings in:
    - BNK health (was: critical/warning/healthy/unknown)
    - Fleet status (was: critical/warning/healthy/offline)
    - System health (was: healthy/degraded/offline)
    - DPF health (was: healthy/partial/degraded/no_devices/not_installed)
    """

    HEALTHY = "healthy"      # All components functional
    DEGRADED = "degraded"    # Partially functional, some impaired
    UNHEALTHY = "unhealthy"  # Non-functional or critically impaired
    UNKNOWN = "unknown"      # Cannot determine (no data, not configured)

    @classmethod
    def ordering(cls) -> dict["HealthSeverity", int]:
        """Return severity ordering map (lower = worse)."""
        return {
            cls.UNHEALTHY: 0,
            cls.DEGRADED: 1,
            cls.UNKNOWN: 2,
            cls.HEALTHY: 3,
        }

    @classmethod
    def worst(cls, severities: list["HealthSeverity | str"]) -> "HealthSeverity":
        """Return the worst severity from a list (like rollup_severity)."""
        if not severities:
            return cls.UNKNOWN
        order = cls.ordering()
        return min(
            (cls(s) for s in severities),
            key=lambda s: order.get(s, 2),
        )

    @classmethod
    def from_counts(cls, healthy: int, total: int) -> "HealthSeverity":
        """Derive severity from healthy/total counts (like calc_severity)."""
        if total == 0:
            return cls.UNKNOWN
        if healthy == total:
            return cls.HEALTHY
        if healthy == 0:
            return cls.UNHEALTHY
        return cls.DEGRADED

# ---------------------------------------------------------------------------
# ConnectivityStatus — canonical network reachability (PLAT-REL-001)
# ---------------------------------------------------------------------------

class ConnectivityStatus(StrEnum):
    """Canonical connectivity status for network-reachable targets.

    Answers: "Can we reach this target over the network?"

    Ordering (worst → best): unreachable < partial < reachable < unknown < connected

    Replaces ad-hoc strings in:
    - Connectivity probe (was: healthy/reachable/port_blocked/unreachable/unknown/error)
    """

    CONNECTED = "connected"      # Network open, API responsive
    REACHABLE = "reachable"      # Network open, API not responding
    PARTIAL = "partial"          # Some paths work, others blocked
    UNREACHABLE = "unreachable"  # No network path
    UNKNOWN = "unknown"          # Not checked or unable to determine

    @classmethod
    def ordering(cls) -> dict["ConnectivityStatus", int]:
        """Return connectivity ordering map (lower = worse)."""
        return {
            cls.UNREACHABLE: 0,
            cls.PARTIAL: 1,
            cls.REACHABLE: 2,
            cls.UNKNOWN: 3,
            cls.CONNECTED: 4,
        }

    @classmethod
    def worst(cls, statuses: list["ConnectivityStatus | str"]) -> "ConnectivityStatus":
        """Return the worst connectivity status from a list."""
        if not statuses:
            return cls.UNKNOWN
        order = cls.ordering()
        return min(
            (cls(s) for s in statuses),
            key=lambda s: order.get(s, 3),
        )

# ---------------------------------------------------------------------------
# ReleaseSourceType — provenance of a BnkRelease row
# ---------------------------------------------------------------------------

class ReleaseSourceType(StrEnum):
    """How the BnkRelease row was populated."""

    CLOUDDOCS = "clouddocs"  # F5 clouddocs release notes / support matrix
    OCI = "oci"              # Derived from live OCI registry tag observation
    OBSERVED = "observed"    # Observed on a live cluster (flo_version + manifest_version)
    MANUAL = "manual"        # Hand-entered by an admin

