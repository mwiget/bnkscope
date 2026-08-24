"""Read the operator's own kubeconfig and split it into per-context candidates.

bnkscope runs on the machine that already talks to these clusters, so the
cluster list should not have to be typed in — ``~/.kube/config`` already has it.
This module is the parsing half of that: it finds the local kubeconfig files,
merges them the way ``kubectl`` does, and turns each context into a standalone,
self-contained kubeconfig that can be stored and used from inside the container.

Two things make that non-trivial.

**File references.** A real kubeconfig is full of paths — ``client-key:
/home/you/.minikube/client.key``, ``certificate-authority: /etc/rancher/...``.
Those paths mean nothing inside a container, so each one is read and inlined as
its ``*-data`` twin. A path that cannot be read is not fatal: the context is
still reported, carrying the reason it cannot be adopted. That is the whole
point of listing candidates rather than importing blindly — the operator gets
told *why* their minikube context did not come across.

**exec plugins.** ``exec: aws eks get-token`` cannot run here; the image ships
no CLI tools. For AWS and GCP that does not matter, because the token can be
minted natively (see ``services/kubernetes/_base.py``). For anything else it
does, and the candidate is reported as needing a bearer token instead.

Read-only throughout. Nothing in this module writes to the host.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)

# Where the host's kubeconfig is mounted. The compose file binds ~/.kube here
# read-only; override for a non-standard layout.
DEFAULT_KUBECONFIG_PATH = "/host/.kube/config"

# exec plugins whose token bnkscope can mint itself, in Python, with no binary:
#   aws / aws-iam-authenticator  -> boto3 SigV4-presigned STS (k8s-aws-v1 token)
#   gke-gcloud-auth-plugin       -> google-auth OAuth2 access token
# `kubelogin` (AKS) has no equivalent and is deliberately absent — see
# _AUTH_UNSUPPORTED below for what the operator is told.
MINTABLE_EXEC_COMMANDS: frozenset[str] = frozenset(
    {"aws", "aws-iam-authenticator", "gke-gcloud-auth-plugin"}
)

# cluster.server hostname suffixes that identify a managed provider. Used only
# as a hint for token minting; a wrong guess costs a fallback, not a failure.
_SERVER_SUFFIX_PROVIDER: tuple[tuple[str, str], ...] = (
    (".eks.amazonaws.com", "eks"),
    (".azmk8s.io", "aks"),
    (".gke.goog", "gke"),
)

_EXEC_PROVIDER: dict[str, str] = {
    "aws": "eks",
    "aws-iam-authenticator": "eks",
    "gke-gcloud-auth-plugin": "gke",
    "kubelogin": "aks",
}

_AUTH_UNSUPPORTED = (
    "This context authenticates with `{command}`, which bnkscope cannot run: "
    "the image ships no CLI tools. Replace the exec auth with a bearer token "
    "(`kubectl create token <serviceaccount>`) and add the cluster manually."
)


@dataclass
class DiscoveredContext:
    """One context from the local kubeconfig, ready to probe or explain away."""

    name: str
    """The context name, as ``kubectl config get-contexts`` shows it."""

    api_server: str | None
    cloud_provider: str
    region: str | None
    """Cloud region. Not cosmetic for EKS — the STS token is signed per-region
    and the API server rejects one signed for the wrong one."""

    namespace: str
    auth_method: str
    """``token`` | ``client-certificate`` | ``exec:<command>`` | ``anonymous``."""

    source_path: str
    """Which kubeconfig file this came from — a laptop often has several."""

    kubeconfig: str | None = None
    """Self-contained single-context YAML, or None when it could not be built."""

    blockers: list[str] = field(default_factory=list)
    """Why this context cannot be adopted. Empty means it can."""

    @property
    def adoptable(self) -> bool:
        return self.kubeconfig is not None and not self.blockers


def kubeconfig_paths() -> list[Path]:
    """The kubeconfig files to read, in kubectl's precedence order.

    ``$KUBECONFIG`` wins when set (colon-separated, like ``$PATH``), otherwise
    the single mounted default. Non-existent entries are dropped quietly —
    ``$KUBECONFIG`` routinely lists files that are not there.
    """
    raw = os.getenv("KUBECONFIG") or os.getenv("BNKSCOPE_KUBECONFIG")
    candidates = (
        [Path(p) for p in raw.split(os.pathsep) if p]
        if raw
        else [Path(DEFAULT_KUBECONFIG_PATH)]
    )
    return [p for p in candidates if p.is_file()]


def discover_contexts() -> list[DiscoveredContext]:
    """Every context in the local kubeconfig(s), self-contained where possible.

    Never raises: a kubeconfig that will not parse is logged and skipped. This
    runs at startup, and an unreadable file on the host must not stop bnkscope
    from coming up.
    """
    contexts: list[DiscoveredContext] = []
    seen: set[str] = set()

    for path in kubeconfig_paths():
        try:
            doc = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Skipping unreadable kubeconfig %s: %s", path, exc)
            continue
        if not isinstance(doc, dict):
            logger.warning("Skipping kubeconfig %s: not a YAML mapping", path)
            continue

        for entry in doc.get("contexts") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            # kubectl's merge rule: first file to define a name wins.
            if not name or name in seen:
                continue
            seen.add(name)
            contexts.append(_build_context(doc, entry, path))

    return contexts


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_context(doc: dict, entry: dict, path: Path) -> DiscoveredContext:
    """Assemble one DiscoveredContext, collecting blockers rather than raising."""
    name = entry["name"]
    body = entry.get("context") or {}
    cluster_entry = _find_named(doc.get("clusters"), body.get("cluster"))
    user_entry = _find_named(doc.get("users"), body.get("user"))

    cluster_body = dict((cluster_entry or {}).get("cluster") or {})
    user_body = dict((user_entry or {}).get("user") or {})

    api_server = cluster_body.get("server")
    blockers: list[str] = []

    if cluster_entry is None:
        blockers.append(
            f"Context '{name}' names cluster '{body.get('cluster')}', which is not "
            f"in {path.name}."
        )
    elif not api_server:
        blockers.append(f"Context '{name}' has no API server URL.")

    # Inline every file reference relative to the kubeconfig's own directory,
    # which is how kubectl resolves relative paths.
    blockers += _inline_paths(cluster_body, _CLUSTER_FILE_FIELDS, path.parent)
    blockers += _inline_paths(user_body, _USER_FILE_FIELDS, path.parent)

    auth_method, auth_blocker = _classify_auth(user_body)
    if auth_blocker:
        blockers.append(auth_blocker)

    return DiscoveredContext(
        name=name,
        api_server=api_server,
        cloud_provider=_infer_provider(api_server, user_body),
        region=_infer_region(api_server, user_body),
        namespace=body.get("namespace") or "default",
        auth_method=auth_method,
        source_path=str(path),
        kubeconfig=(
            None
            if cluster_entry is None
            else _render_single_context(name, body, cluster_body, user_body)
        ),
        blockers=blockers,
    )


def _find_named(entries: Any, name: str | None) -> dict | None:
    if not name or not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


# (path field, inline field). Order matters only for the error message.
_CLUSTER_FILE_FIELDS = (("certificate-authority", "certificate-authority-data"),)
_USER_FILE_FIELDS = (
    ("client-certificate", "client-certificate-data"),
    ("client-key", "client-key-data"),
    ("tokenFile", None),  # tokenFile holds the token itself, not base64 of it
)


def _inline_paths(
    body: dict, fields: tuple[tuple[str, str | None], ...], base_dir: Path
) -> list[str]:
    """Replace file references with their inline equivalents, in place.

    Returns a blocker per file that could not be read. When the inline form is
    already present the path is simply dropped — ``*-data`` wins, same
    precedence rule the normalizer uses.
    """
    blockers: list[str] = []
    for path_field, data_field in fields:
        raw = body.get(path_field)
        if not raw:
            continue
        if data_field and body.get(data_field):
            body.pop(path_field, None)  # already inlined
            continue

        resolved = Path(raw)
        if not resolved.is_absolute():
            resolved = base_dir / resolved
        try:
            content = resolved.read_bytes()
        except OSError:
            blockers.append(
                f"Cannot read `{path_field}: {raw}` — it is outside the paths "
                f"mounted into bnkscope. Flatten this context "
                f"(`kubectl config view --flatten --minify --raw`) and add it manually."
            )
            continue

        body.pop(path_field, None)
        if data_field is None:
            # tokenFile: the file's contents ARE the bearer token.
            body["token"] = content.decode("utf-8", "replace").strip()
        else:
            body[data_field] = base64.b64encode(content).decode("ascii")
    return blockers


def _classify_auth(user_body: dict) -> tuple[str, str | None]:
    """Name the auth method, and say so if bnkscope cannot use it."""
    exec_block = user_body.get("exec")
    if isinstance(exec_block, dict):
        command = str(exec_block.get("command") or "")
        # A plugin invoked by an absolute path is still that plugin.
        base = os.path.basename(command)
        if base not in MINTABLE_EXEC_COMMANDS:
            return f"exec:{base}", _AUTH_UNSUPPORTED.format(command=base or "an exec plugin")
        return f"exec:{base}", None

    if user_body.get("token"):
        return "token", None
    if user_body.get("client-certificate-data"):
        return "client-certificate", None
    if user_body.get("username") and user_body.get("password"):
        return "basic", None
    return "anonymous", None


def _infer_provider(api_server: str | None, user_body: dict) -> str:
    """Best guess at the cloud provider, used to pick a token-minting path."""
    exec_block = user_body.get("exec")
    if isinstance(exec_block, dict):
        command = os.path.basename(str(exec_block.get("command") or ""))
        if command in _EXEC_PROVIDER:
            return _EXEC_PROVIDER[command]

    host = (urlparse(api_server).hostname or "") if api_server else ""
    for suffix, provider in _SERVER_SUFFIX_PROVIDER:
        if host.endswith(suffix):
            return provider
    return "on-prem"


def _infer_region(api_server: str | None, user_body: dict) -> str | None:
    """Pull the cloud region out of the context, EKS first.

    This matters more than it looks. ``_generate_eks_token`` signs against the
    *regional* STS endpoint, and EKS rejects a token signed for a different
    region with a bare 401 — so a wrong region here looks exactly like bad
    credentials. Two sources, most explicit first:

      1. the exec plugin's own ``--region <r>`` argument, which is what
         ``aws eks update-kubeconfig`` writes;
      2. the API server hostname, ``https://<id>.<az>.<region>.eks.amazonaws.com``.
    """
    exec_block = user_body.get("exec")
    if isinstance(exec_block, dict):
        args = [str(a) for a in (exec_block.get("args") or [])]
        for flag in ("--region", "-r"):
            if flag in args:
                index = args.index(flag) + 1
                if index < len(args):
                    return args[index]
        for arg in args:
            if arg.startswith("--region="):
                return arg.split("=", 1)[1]
        # `aws eks get-token` also honours AWS_REGION from the plugin's env block.
        for item in exec_block.get("env") or []:
            if isinstance(item, dict) and item.get("name") in ("AWS_REGION", "AWS_DEFAULT_REGION"):
                return item.get("value")

    host = (urlparse(api_server).hostname or "") if api_server else ""
    if host.endswith(".eks.amazonaws.com"):
        parts = host.split(".")
        # <id>.<az-letter>.<region>.eks.amazonaws.com
        if len(parts) >= 5:
            return parts[-4]
    return None


def _render_single_context(
    name: str, body: dict, cluster_body: dict, user_body: dict
) -> str:
    """A minimal kubeconfig holding exactly this one context.

    Stored per cluster rather than keeping a reference into the host file: the
    host file changes, and a cluster that worked yesterday should not stop
    working because an unrelated context was edited.
    """
    cluster_name = body.get("cluster") or name
    user_name = body.get("user") or name
    doc: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": name,
        "clusters": [{"name": cluster_name, "cluster": cluster_body}],
        "contexts": [
            {
                "name": name,
                "context": {
                    "cluster": cluster_name,
                    "user": user_name,
                    **({"namespace": body["namespace"]} if body.get("namespace") else {}),
                },
            }
        ],
        "users": [{"name": user_name, "user": user_body}] if user_body else [],
    }
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True)


