# bnkscope documentation

## Start here

| | |
|---|---|
| [User guide](USER_GUIDE.md) | every page, and what it answers |
| [Troubleshooting](TROUBLESHOOTING.md) | when bnkscope itself misbehaves |
| [Cloud authentication](CLOUD_AUTH.md) | EKS, GKE, AKS, and AWS SSO |
| [API reference](API_REFERENCE.md) | the HTTP surface — generated from `backend/openapi.json`, CI-checked |
| [Development guide](DEVELOPMENT.md) | build, test, architecture, style |
| [Testing](TESTING.md) | suites, fixtures, what is covered |
| [Docker](DOCKER.md) | images, compose layout, build |
| [Disk management](DISK_MANAGEMENT.md) | BuildKit cache growth, and keeping it bounded |
| [Backup & restore design](BACKUP_RESTORE_DESIGN.md) | what a backup contains, and why that matters |

## Decisions

[`adr/`](adr/) — one file per architecture decision, with its own
[README](adr/README.md) explaining the format, statuses and numbering.

## How bnkscope came from bnk-forge

| | |
|---|---|
| [The plan](BNKSCOPE_PLAN.md) | the eight phases of the reduction, and where the plan was wrong |
| [The baseline](BNKSCOPE_BASELINE.md) | what bnk-forge measured at, before any of it was removed |

Attribution and lineage live in the top-level [NOTICE](../NOTICE).

## Specs

[`specs/`](specs/) — cross-cutting contracts that code is expected to honour:
[status semantics](specs/STATUS_SEMANTICS.md),
[badge semantics](specs/BADGE_SEMANTICS.md),
[diagnostic payload shape](specs/DIAGNOSTIC_PAYLOAD.md),
[async state](specs/UX-OPS-001_ASYNC_STATE_STANDARD.md),
[diagnostic panel pattern](specs/UX-OPS-003_DIAGNOSTIC_PANEL_PATTERN.md),
[secret boundary review](specs/SEC-GOV-003_SECRET_BOUNDARY_REVIEW.md),
[operational risk surfacing](specs/PLAT-REL-004_OPERATIONAL_RISK_SURFACING.md),
[troubleshooting dashboard](specs/OBS-005_TROUBLESHOOTING_DASHBOARD.md).

## Engineering records (bnk-forge era)

These are working documents from bnk-forge, kept because the conventions they
set are still the ones the code follows. **They are dated records, not current
reference** — each is stamped `Version: 2.11.0`, which is bnk-forge's version
line and unrelated to this repository's `VERSION`. Where one names a file,
route, or tool, check that it still exists before relying on it.

- [OBS-002 — structured log schema](OBS-002_STRUCTURED_LOG_SCHEMA.md)
- [OBS-004 — error taxonomy](OBS-004_ERROR_TAXONOMY.md)
- [API-CONTRACT-006 — generated type strategy](API-CONTRACT-006_TYPE_GENERATION.md)
- [SEC-GOV-004 — new tool/endpoint safety review checklist](SEC-GOV-004_SAFETY_REVIEW_CHECKLIST.md)
- [UX-OPS-004 — information hierarchy review](UX-OPS-004_INFORMATION_HIERARCHY.md)
- [UX-OPS-005 — accessibility](UX-OPS-005_ACCESSIBILITY.md)
- [E2E-CRITICAL-004 — MCP end-to-end sanity plan](E2E-CRITICAL-004_MCP_SANITY.md)
