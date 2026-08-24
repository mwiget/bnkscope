"""bnkscope MCP tools — organized by domain.

Each module registers its tools with the FastMCP server instance.

**Read-only.** Every tool here resolves to a GET on a route the backend
actually serves, with one deliberate exception: `tmm_configview` POSTs, because
the endpoint takes a request body — `routes/k8s/tmm_debug.py` states that all
of its endpoints are read-only diagnostics.

That is not decoration. bnkscope is documented as read-only in the README, the
User Guide and the sidebar, and it used to ship 22 tools that contradicted all
three — delete_cluster, drain_node, delete_resource, and bnk-forge holdovers
like delete_project — with no confirmation gate anywhere. Anything that writes
belongs in the UI, where a human is looking at it.

The iac_operations, helm, config_management and cloud_auth modules were
removed outright: every path they called had already been deleted from the
backend, so all 94 of their tools answered 404.
"""

from .bnk_operations import register as register_bnk_operations
from .cluster_management import register as register_cluster_management
from .diagnostics_fleet import register as register_diagnostics_fleet
from .system import register as register_system

__all__ = [
    "register_system",
    "register_cluster_management",
    "register_bnk_operations",
    "register_diagnostics_fleet",
]
