"""BNK version detection — pure reads over already-fetched scan data.

Extracted from the (deleted) BNK upgrade service in bnkscope Phase 1. Deciding
*which* version to upgrade to was a deployment concern and went with the
pipeline; knowing *which version is running right now* is diagnosis, and stays.

Both functions are pure: no I/O, no DB, no cluster access.
"""

import re


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a FLO version string to a comparable numeric tuple.

    Handles formats like::

        v1.198.4-0.1.36  -> (1, 198, 4, 0, 1, 36)
        1.198.4          -> (1, 198, 4)
        v2.0.0           -> (2, 0, 0)
    """
    v = v.lstrip("v")
    result: list[int] = []
    for part in re.split(r"[-.]", v):
        try:
            result.append(int(part))
        except ValueError:
            break
    return tuple(result) if result else (0,)


def detect_current_bnk_version(bnk_install: dict) -> str | None:
    """Detect the currently-installed BNK version, install-shape-aware (#389).

    Resolution order (first hit wins):

    1. FLO pod image version (the FLO/deploy-flow install).
    2. Helm release chart version string, e.g. ``"f5ingress-2.21.13"`` ->
       ``"2.21.13"`` (``"{chart_name}-{chart_version}"`` per
       ``scanner/fetch.py:_fetch_helm_releases``).

    The controller/tmm ``.version`` fields carry raw image tags (e.g.
    ``v14.59.1-0.0.70``), not chart versions, so they cannot be compared against
    BNK release versions. Callers treat ``None`` as "version unknown".
    """
    flo_info = bnk_install.get("flo", {})
    flo_version = flo_info.get("version")
    if flo_version:
        return flo_version

    helm_release = flo_info.get("helm_release") or {}
    chart = helm_release.get("chart") or ""
    match = re.search(r"-(\d+\.\d+\.\d+(?:-[\d.]+)?)$", chart)
    if match:
        return match.group(1)

    return None
