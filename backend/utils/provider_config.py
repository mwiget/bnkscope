"""Cloud-provider string handling.

This file used to generate OpenTofu/Terraform provider blocks for EKS, AKS,
GKE and ROKS. Those went with the deployment pipeline (bnkscope Phase 1) —
nothing generates infrastructure any more. What survives is the one thing the
cluster routes still need: a canonical spelling for the provider name.
"""


def normalize_cloud_provider(value: str | None) -> str | None:
    """Canonicalize a cloud_provider string to lowercase so 'IBM' == 'ibm'.

    cloud_provider values are stored and compared lowercase by convention;
    normalize on write (and defensively on compare) so case never matters.
    Returns None for empty/blank input.
    """
    if not value:
        return None
    return value.strip().lower() or None
