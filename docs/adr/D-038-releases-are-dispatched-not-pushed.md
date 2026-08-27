# D-038: Releases are dispatched, not pushed

**Status:** Accepted
**Date:** 2026-08-27

---

## Context & Problem Statement

`release.yml` fired on every push to `main` that touched anything outside the
`paths-ignore` list. Merging was releasing: the workflow derived a bump from the
conventional-commit messages since the last `vX.Y.Z` tag, wrote `VERSION`,
inserted a `CHANGELOG.md` entry, committed `release: vX.Y.Z [skip ci]`, tagged,
pushed, cut a GitHub Release, and published images to GHCR. Nobody pressed
anything. A `guard` job existed solely to stop the release commit re-triggering
the workflow that wrote it.

That is bnk-forge's model, and it suited bnk-forge — a deployment platform whose
consumers wanted every merge available immediately.

It broke on 2026-08-27 while making this repository public. Purging a
credential-bearing blob from history meant deleting and recreating the GitHub
repository, and pushing the recovered history landed all 24 commits as a single
push to `main`. Release started alongside CI. It was cancelled before the
version-derivation step, so nothing was tagged or published — but had it run, a
fresh repository has no tags, so `LAST_FINAL` would have been empty and the
derivation would have walked back to bnk-forge's `feat:` root commit and cut a
**minor** release off someone else's changelog. `VERSION` was, and is, `0.1.0`
with an empty bnkscope changelog.

The near-miss is the symptom. The problem is that the trigger encodes a policy —
*every merge is a release* — that this project does not hold. bnkscope is a
single-user troubleshooting tool that people run from a git checkout. Nothing
downstream is waiting on a version bump, and a release that nobody chose is
noise at best.

## Decision

**`workflow_dispatch` only.** Releasing is a decision someone makes, not a side
effect of merging.

The bump comes from the dropdown (`patch`/`minor`/`major`) applied to `VERSION`.
Deriving it from commit messages was the automated path's job and went with it.

Removed as unreachable once the trigger was gone:

- `release-final` — the push-to-`main` path.
- `release-rc` — the pre-release path for non-`main` branches. Already dormant:
  the push trigger only ever listed `main`, so it had never fired.
- `guard` — it read `github.event.head_commit.message`, which does not exist in
  a `workflow_dispatch` payload. With no push to guard against, the loop it
  prevented cannot happen.
- `release_kind` — three values, one of them reachable.

## Consequences

**A release now requires two steps: push, then dispatch.** That is the point.

**CI must already be green for the exact commit you dispatch against.** Preflight
matches its CI run by SHA. This was true before, but the push trigger hid it —
the release rode in on the same push that started CI, so a matching run always
existed. Dispatching by hand has no such guarantee, and the sharp edge is a
**docs-only HEAD**: `ci.yml` skips those via `paths-ignore`, so the SHA has no CI
run and never will. Preflight used to poll the full 45-minute timeout to
discover this. It now fails after a 5-minute grace window with the actual reason,
because a run that has not appeared in five minutes is not coming.

**`scripts/compute_version_bump.sh` and `scripts/extract-breaking-changes.sh` are
deleted.** Both existed only to serve the automated path — deriving a bump from
commit subjects, and pulling `BREAKING CHANGE` blocks out of them for the
changelog entry. Nothing else called either one. They were briefly kept on the
argument that a future automated path would want them back, which is the
argument for every piece of dead code ever retained; `git log` holds them, and a
public repository should not ship a `scripts/` directory where a third of the
entries are unreachable.

**Restoring the old behaviour means restoring the guard with it.** The `release: `
+ `[skip ci]` filter is not optional decoration — without it the workflow's own
release commit re-triggers it. Recover the guard job, the two derivation scripts
and the `release-final` job together from the history, or not at all: the parts
only work as a set.

## References

- The cancelled run: `33077514953`, 2026-08-27.
- `.github/BRANCH_PROTECTION.md` — the operator-facing description.
- `paths-ignore` in `release.yml` and `ci.yml` had to stay identical while the
  push trigger existed, since preflight matched CI by SHA. With the trigger
  gone the coupling is one-way: CI's list still decides which commits *can* be
  released, because a commit CI skips is a commit preflight cannot verify.
