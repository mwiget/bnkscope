"""
NICo health analysis — aggregate the fetched picture into a summary.

Pure function (dict in → dict out) with no I/O.
"""

from typing import Any


def analyze_nico_health(data: dict[str, Any]) -> dict[str, Any]:
    """Roll the NICo picture up into the header the tab renders.

    The status ladder answers "can I trust what the rest of this page says":

    * ``not_installed`` — no nico-api pod. Nothing else was even attempted.
    * ``unreachable``   — nico-api runs, but its Forge API could not be dialled
      from here (unrouted endpoint, missing client cert). The deployment view
      is real; the inventory is absent, not empty.
    * ``degraded``      — a pod is down, a provider is failing, or a load
      balancer NICo accepted has not reached READY.
    * ``healthy``       — every pod ready and every LB programmed.
    """
    control = data.get("controlPlane") or {}
    endpoint = data.get("endpoint") or {}
    inventory = data.get("inventory") or {}
    providers = data.get("providers") or []
    dependencies = data.get("dependencies") or []

    api_pods = control.get("pods") or []
    api_ready = sum(1 for p in api_pods if _pod_ok(p))

    lbs = inventory.get("loadBalancers") or []
    lbs_ready = sum(1 for lb in lbs if lb.get("status") == "READY")
    tenants = inventory.get("tenants") or []
    vpcs = inventory.get("vpcs") or []

    provider_ready = sum(1 for p in providers if _pod_ok(p.get("pod") or {}))
    provider_errors = sum(1 for p in providers if p.get("recentErrors"))

    dep_total = sum(len(d.get("pods") or []) for d in dependencies)
    dep_ready = sum(
        1 for d in dependencies for p in (d.get("pods") or []) if _pod_ok(p)
    )

    cert = control.get("mtls") or {}
    days_left = cert.get("daysLeft")
    # cert-manager renews well before this, so a cert inside 30 days of expiry
    # means renewal is not happening — worth a warning while calls still work.
    cert_expiring = isinstance(days_left, int) and days_left < 30

    if not data.get("detected"):
        status = "not_installed"
    elif not endpoint.get("reachable") or not inventory:
        status = "unreachable"
    elif (
        api_ready < len(api_pods)
        or provider_ready < len(providers)
        or dep_ready < dep_total
        or lbs_ready < len(lbs)
        or provider_errors
        or cert_expiring
    ):
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "version": control.get("version"),
        "namespace": control.get("namespace"),
        "api": {"total": len(api_pods), "ready": api_ready},
        "providers": {
            "total": len(providers),
            "ready": provider_ready,
            "withErrors": provider_errors,
        },
        "dependencies": {"total": dep_total, "ready": dep_ready},
        "tenants": {"total": len(tenants)},
        "vpcs": {"total": len(vpcs)},
        "loadBalancers": {
            "total": len(lbs),
            "ready": lbs_ready,
            "programmedPods": sum(int(lb.get("programmedPods") or 0) for lb in lbs),
            "pools": sum(len(lb.get("pools") or []) for lb in lbs),
            "members": sum(
                len(pool.get("members") or [])
                for lb in lbs
                for pool in (lb.get("pools") or [])
            ),
        },
        "networkSegments": {"total": len(inventory.get("networkSegments") or [])},
        "certExpiring": cert_expiring,
        "dpus": data.get("dpf") or {"total": 0, "ready": 0},
        "errors": data.get("errors") or [],
    }


def _pod_ok(pod: dict[str, Any]) -> bool:
    """Running with every container ready."""
    containers = pod.get("containers") or 0
    return pod.get("phase") == "Running" and containers > 0 and pod.get("ready") == containers
