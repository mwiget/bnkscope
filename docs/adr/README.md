# Architecture Decision Records

Per-decision files: one file, one decision. There is no separate roll-up index —
this directory listing is the index, and each filename carries the ID and title.

Two ID prefixes appear here, both live:

- **`D-NNN`** — decisions carried over from bnk-forge and continued here. Numbering is sequential and never reused; `D-005` onward are per-file (currently through `D-037`). `D-001`..`D-004` predate the per-file format and were never split out.
- **`ADR-NNN`** — newer records numbered after the GitHub issue they resolve, created by `scripts/new-adr.sh --issue N --title "..."`.

## Format

Each file is one decision: ID, title, status, context, decision (the deeper
shape), consequences, references. Loosely MADR — see the existing files for the
exact shape.

## Statuses

- **Proposed** — no commitment yet. Anyone can pick one up and transition it.
- **Accepted** — work has started or is queued.
- **Deferred** — accepted in spirit, parked behind a dependency. The ADR documents the resume trigger.
- **Rejected** — the load-bearing reason is recorded so a future review doesn't re-suggest the same thing.
- **Superseded by D-NNN / ADR-NNN** — replaced; keep the file and mark the supersession.

## Vocabulary

Module / Interface / Implementation / Depth / Seam / Adapter / Leverage /
Locality. Apply the deletion test: if removing the abstraction costs nothing,
it was never a seam. One adapter is a hypothetical seam; two is a real one.

## When transitioning a Proposed ADR

1. Read the ADR end-to-end.
2. Re-run the deletion test against the current code — code shifts, and the ADR may be stale.
3. Open (or claim) the GitHub issue that tracks the work; issues are the source of truth for *what to work on*.
4. Bump the status to `Accepted` and add a `Tracking:` line pointing at the issue or PR.
