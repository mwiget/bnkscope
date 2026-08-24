# AGENTS.md — Coding Agent Reference

> Optional. This file exists for coding agents; nothing in this repo requires
> you to use one. Humans should read **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**
> (build, test, architecture, style, gotchas) and
> **[CONTRIBUTING.md](CONTRIBUTING.md)** (contribution process) instead — those
> are the source of truth, and this file only adds agent-specific framing on top.

**Agents: read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) first.** It carries the
build/lint/test commands, architecture, project structure, code style, testing
conventions, key gotchas, and git workflow. The sections below are the extra
context an autonomous agent needs and a human does not.

---

## Roadmap & Tracking — what to work on

**GitHub issues are the source of truth.** The shared roadmap (`docs/ROADMAP.md`,
its generated HTML view, and the `bin/roadmap-*.py` generators) belonged to
bnk-forge's release process and went with it. New decisions still flow
**ADR → GitHub issue → PR**; ADRs live in `docs/adr/`.

---

## Behavioral Guidelines

Bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- Check whether it already exists. Grep for the capability by name and by what it shells out to (`docker`/`buildx`, `helm`, `kubectl`, Make targets) before writing new code — extend the existing path, don't fork a parallel one.
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: *"Would a senior engineer say this is overcomplicated?"* If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports / variables / functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### 5. Rigorous Code & PR Review Framework

When reviewing Pull Requests, look beyond syntax and passing unit tests. Systematically check for runtime edge cases:

1. **Infrastructure & Container Lifecycle**:
   - **Container Creation Order**: Does a Docker Compose `subpath:` or volume mount require a file to exist at `docker create` time before any entrypoint runs?
   - **Cross-UID Permissions**: Are shared volume files accessible across container UIDs? Are file modes explicitly set via `chmod` or dedicated volumes?

2. **Credential & Token Lifecycles**:
   - **Renewal Window**: Do token validation steps enforce an early renewal buffer (e.g. `exp - now < 30d`) so credentials don't expire mid-flight?
   - **Daemon Hot-Reloading**: Do long-running agents or background daemons re-read rotated tokens from disk on reconnect/retry loops?

3. **File Permission Invariants**:
   - **POSIX Mode Retention**: Does writing to existing files retain restrictive permissions (`0600`) unless `os.chmod()` is explicitly called post-write?

4. **Static Test Blindspot Auditing**:
   - Ask: *"What ordering or environment condition does this unit test assume?"* (e.g. writer running before reader, pre-created directories, fresh DB sessions).

5. **Loopback & Proxy Security Protocols (PR #150)**:
   - **Verification over Local Tunnels**: When traffic is routed through SSH tunnels or local proxies (`127.0.0.1:<port>`), check if TLS verification was disabled (`insecure-skip-tls-verify`). Enforce protocol mechanisms (e.g. `tls-server-name` in kubeconfig) to keep CA verification enabled while dialling loopback endpoints.
   - **Fail-Safe Preserving**: Security hardening must preserve explicit user choices (e.g. explicitly unverified setups remain unverified, while setups with valid CAs restore TLS verification).

6. **Interrupted Workflows & Fail-Closed Resource Teardowns (PR #151)**:
   - **Interrupted Worker Recovery**: Assume background tasks/workers can die at any point (SIGKILL/OOM). Ensure interrupted transitional states (`applying`, `destroying`) do not bypass teardown handlers and leave orphaned external resources (cloud infrastructure, IAM roles).
   - **Fail-Closed Teardowns**: When choosing between fast DB deletion and full destruction tasks, **fail closed**. Only states positively known to hold zero external resources (`NO_INFRA_STATUSES`) may skip destruction.

---

