#!/usr/bin/env python3
"""
Generate docs/API_REFERENCE.md from backend/openapi.json.

Usage:
    python scripts/gen-api-reference.py            # write docs/API_REFERENCE.md
    python scripts/gen-api-reference.py --check    # fail if the doc is stale

The previous API reference was written by hand. It drifted until 288 of the
289 endpoints it documented no longer existed, and it opened by telling the
reader that every endpoint required JWT authentication — which is the exact
opposite of the truth, and the most dangerous sentence in the file, since
bnkscope has no authentication at all and can be bound to 0.0.0.0.

A hand-written reference for a 132-endpoint API will always lose that race.
This one is derived, and CI checks it, so the failure mode is a red build
rather than a document that quietly lies.

Source of truth: backend/openapi.json (itself generated and freshness-checked
by scripts/generate-openapi.py).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(ROOT, "backend", "openapi.json")
OUT_PATH = os.path.join(ROOT, "docs", "API_REFERENCE.md")

METHODS = ("get", "post", "put", "patch", "delete")

# Human-facing section names and the order that matches how the UI is laid
# out, so the reference reads in the order an operator meets the features.
TAG_TITLES = {
    "system": "System",
    "connectivity": "Connectivity",
    "k8s-clusters": "Clusters",
    "k8s-resources": "Kubernetes Resources",
    "k8s-crds": "Custom Resource Definitions",
    "k8s-topology": "Topology",
    "k8s-f5bnk": "F5 BNK",
    "k8s-dpf": "NVIDIA DPF",
    "k8s-tmm-debug": "TMM Debug",
    "k8s-llm-observability": "LLM Observability",
    "k8s-recovery": "Cluster Recovery",
    "tmmscope": "tmmscope",
    "qkview": "qkview",
    "cloud-auth": "Cloud Authentication",
    "credential-templates": "Credential Templates",
    "container-registries": "Container Registries",
    "alert-channels": "Alert Channels",
    "notifications": "Notifications",
    "api": "Meta",
}
TAG_ORDER = list(TAG_TITLES)

HEADER = """# bnkscope — API Reference

> **Generated from `backend/openapi.json` by `scripts/gen-api-reference.py`.**
> Do not edit by hand — run `make api-docs` (or the script) instead.
> `--check` runs in CI, so this file cannot drift from the code.

bnkscope serves **{n_ops} operations** across **{n_paths} paths**.

Summaries are FastAPI's, derived from the handler name — they are terse
because the code is, not because the doc is abridged. A `—` under **Returns**
means the endpoint declares no `response_model`; {n_untyped} of {n_ops} do
not, so the shape there is whatever the handler returns.

## Authentication — there is none

**Every endpoint below is unauthenticated.** bnkscope is a single-user local
troubleshooting tool; authentication, users, roles and sessions were removed
deliberately.

This is safe *because of where it listens*, and only that:

| | |
|---|---|
| API (`bnkscope-backend`) | binds loopback only — not reachable off the host |
| UI (`bnkscope-frontend`) | binds `127.0.0.1` by default, and proxies `/api` to the API |
| `./bnkscope up --listen 0.0.0.0` | **exposes every operation below, unauthenticated, to your network** |

Nothing takes over when the bind widens — there is no token and no password to
add. Anyone who can reach the port gets a shell in any pod (`/ws/.../exec`), and
`POST /api/system/backup` hands back the database together with the key that
decrypts it, so every kubeconfig and cloud credential leaves in one request.
Traffic is plain HTTP, so all of it is readable and modifiable in flight.

Use it only on a network you would trust with all of that: a private lab
network, or a VPN (Tailscale/WireGuard) with `--listen` bound to the VPN
interface. Otherwise leave the bind at its loopback default and tunnel:

```sh
ssh -N -L 8080:localhost:8080 you@the-host
```

`--listen` governs the UI only. Prometheus (`9491`) always binds `0.0.0.0`,
because your clusters push to it; see
the README for what each exposes.

Interactive versions of this reference are served by the running backend at
`/docs` (Swagger UI) and `/redoc`.

---
"""


def load_spec():
    if not os.path.exists(SPEC_PATH):
        sys.exit(
            f"error: {SPEC_PATH} not found — run `python scripts/generate-openapi.py` first"
        )
    with open(SPEC_PATH) as fh:
        return json.load(fh)


def ref_name(schema):
    """Short model name for a $ref, or None."""
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    for key in ("items", "additionalProperties"):
        if key in schema:
            inner = ref_name(schema[key])
            if inner:
                return f"{inner}[]" if key == "items" else inner
    for key in ("anyOf", "oneOf", "allOf"):
        for alt in schema.get(key, []):
            inner = ref_name(alt)
            if inner:
                return inner
    return None


def body_model(op):
    content = (op.get("requestBody") or {}).get("content") or {}
    for media, spec in content.items():
        name = ref_name(spec.get("schema") or {})
        if name:
            return name
        if media == "multipart/form-data":
            return "form-data"
    return None


def response_model(op):
    for code in ("200", "201", "202"):
        resp = (op.get("responses") or {}).get(code)
        if not resp:
            continue
        content = resp.get("content") or {}
        for spec in content.values():
            name = ref_name(spec.get("schema") or {})
            if name:
                return name
        return "—"
    return "—"


def params(op):
    """Path and query parameters, path ones first, required ones marked."""
    out = []
    for p in op.get("parameters", []):
        if p.get("in") not in ("path", "query"):
            continue
        out.append((p["in"], p["name"], bool(p.get("required"))))
    out.sort(key=lambda t: (t[0] != "path", t[1]))
    bits = []
    for where, name, required in out:
        if where == "path":
            bits.append(f"`{{{name}}}`")
        else:
            bits.append(f"`{name}`" + ("" if required else "?"))
    return " ".join(bits) or "—"


def escape(text):
    return re.sub(r"([|<>])", r"\\\1", (text or "").strip())


def build(spec):
    paths = spec.get("paths", {})
    by_tag = {}
    n_ops = 0
    for path, item in sorted(paths.items()):
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            n_ops += 1
            tag = (op.get("tags") or ["api"])[0]
            by_tag.setdefault(tag, []).append((path, method, op))

    n_untyped = sum(
        1
        for ops in by_tag.values()
        for _, _, op in ops
        if response_model(op) == "—"
    )

    lines = [
        HEADER.format(n_ops=n_ops, n_paths=len(paths), n_untyped=n_untyped),
        "## Contents\n",
    ]

    ordered = [t for t in TAG_ORDER if t in by_tag]
    ordered += sorted(t for t in by_tag if t not in TAG_TITLES)

    for tag in ordered:
        title = TAG_TITLES.get(tag, tag)
        anchor = title.lower().replace(" ", "-")
        lines.append(f"- [{title}](#{anchor}) — {len(by_tag[tag])}")
    lines.append("")

    for tag in ordered:
        title = TAG_TITLES.get(tag, tag)
        lines.append(f"\n## {title}\n")
        lines.append("| Method | Path | Summary | Params | Body | Returns |")
        lines.append("|---|---|---|---|---|---|")
        for path, method, op in sorted(by_tag[tag], key=lambda t: (t[0], t[1])):
            summary = escape(op.get("summary") or "")
            lines.append(
                f"| `{method.upper()}` | `{path}` | {summary} | {params(op)} "
                f"| {body_model(op) or '—'} | {response_model(op)} |"
            )
        lines.append("")

    lines.append(
        "\n---\n\n*Schemas for every model named above are in "
        "`backend/openapi.json`, and rendered at `/redoc` on a running "
        "backend.*\n"
    )
    return "\n".join(lines)


def main():
    spec = load_spec()
    rendered = build(spec)

    if "--check" in sys.argv:
        if not os.path.exists(OUT_PATH):
            sys.exit(f"error: {OUT_PATH} missing — run scripts/gen-api-reference.py")
        with open(OUT_PATH) as fh:
            current = fh.read()
        if current != rendered:
            sys.exit(
                "error: docs/API_REFERENCE.md is stale.\n"
                "       Run: python scripts/gen-api-reference.py"
            )
        print("API_REFERENCE.md is up to date")
        return

    with open(OUT_PATH, "w") as fh:
        fh.write(rendered)
    n = rendered.count("\n| `")
    print(f"Generated {OUT_PATH} ({n} operations)")


if __name__ == "__main__":
    main()
