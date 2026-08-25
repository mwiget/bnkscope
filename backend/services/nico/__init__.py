"""
NICo (NVIDIA Infra Controller) service package.

Detection, data collection and health analysis for a NICo deployment: the
nico-api control plane and its LB provider operators, plus the tenants, VPCs,
network segments and load balancer services NICo holds behind its Forge gRPC
API.

Modules:
    constants   — labels, ports, secret names, timeouts
    forge       — reflective gRPC client for the Forge API (no vendored proto)
    fetch       — the only I/O module: Kubernetes reads + Forge calls
    health      — health aggregation (pure analysis)
"""

from services.nico.fetch import (
    detect_nico,
    fetch_all_nico_data,
    fetch_nico_deployment,
    fetch_nico_inventory,
)
from services.nico.forge import ForgeClient, ForgeError
from services.nico.health import analyze_nico_health, inventory_counts

__all__ = [
    "ForgeClient",
    "ForgeError",
    "analyze_nico_health",
    "detect_nico",
    "fetch_all_nico_data",
    "fetch_nico_deployment",
    "fetch_nico_inventory",
    "inventory_counts",
]
