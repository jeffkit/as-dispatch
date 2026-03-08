<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0
This is the initial ratification of the as-dispatch project constitution.

Modified principles : N/A (initial creation)
Added sections      : All (Language & Runtime, Type Safety, Error Isolation,
                      Adapter Contract, Reference Implementation, Logging,
                      Dependencies, Testing Philosophy, No Breaking Changes,
                      Async I/O, Governance)
Removed sections    : N/A

Templates reviewed & updated:
  ✅  .specify/templates/plan-template.md   — Constitution Check gate already
                                              present; principles added inline
  ✅  .specify/templates/spec-template.md   — No structural changes required;
                                              FR pattern already compatible
  ✅  .specify/templates/tasks-template.md  — Phase structure compatible; no
                                              changes required
  ⚠   .specify/templates/commands/          — Directory does not exist yet;
                                              no command files to update

Deferred TODOs:
  - None; all fields resolved from repository context and user input
-->

# Project Constitution: as-dispatch (intelligent-bot branch)

**Version**: 1.0.0
**Ratification Date**: 2026-03-02
**Last Amended**: 2026-03-02
**Branch Scope**: `feature/im-integration` and all subsequent adapters in
`platform/as-dispatch/.worktrees/intelligent-bot/`

---

## Purpose

This constitution defines the non-negotiable engineering principles that govern
all development inside the `as-dispatch` service — a Python FastAPI
multi-platform IM bot dispatcher.

Every feature specification, implementation plan, and task list MUST be checked
against these principles before proceeding (see the "Constitution Check" gate
in `plan-template.md`). Violations require explicit written justification in
the Complexity Tracking table of the relevant plan.

---

## Principle 1 — Language & Runtime

**Name**: Python 3.11+ with FastAPI

All service code MUST be written in Python 3.11 or higher.
The web layer MUST use the FastAPI framework.
`async`/`await` MUST be used as the default execution model for all I/O-bound
operations; synchronous handler functions are not permitted in FastAPI route
definitions.

**Rationale**: Python 3.11 delivers significant performance improvements and
better async support. FastAPI provides first-class async support, automatic
OpenAPI documentation, and type-driven request validation that aligns with
Principle 2.

---

## Principle 2 — Type Safety

**Name**: Mandatory type annotations

Every function and method MUST carry explicit type annotations for all
parameters and the return type. This includes class methods, standalone
functions, and async coroutines. The use of `Any` is permitted only where
the type is genuinely unknown (e.g., raw platform payloads stored in
`raw_data: dict`), and MUST NOT be used as an escape hatch to avoid typing
effort.

**Rationale**: Type annotations are the primary form of documentation in this
codebase. They enable static analysis tooling (mypy, pyright) and reduce
integration bugs across adapter boundaries.

---

## Principle 3 — Error Isolation

**Name**: Per-adapter exception containment

All exceptions raised inside a platform adapter MUST be caught within that
adapter's own code paths. An unhandled exception in one adapter MUST NOT
propagate to the dispatcher pipeline or affect any other platform's message
processing.

Concretely:
- `parse_inbound()` MUST catch and log parsing errors, returning a safe
  fallback or re-raising as `ValueError` only after local logging.
- `send_outbound()` MUST wrap all send logic in `try/except` and return a
  `SendResult(success=False, error=...)` rather than raising.
- Route handlers MUST NOT let adapter exceptions bubble up as unhandled 500s.

**Rationale**: The dispatcher is a shared runtime. A misconfigured or
misbehaving adapter for Platform A must not degrade service for Platform B.

---

## Principle 4 — Adapter Contract

**Name**: ChannelAdapter interface compliance

Every new platform integration MUST be implemented as a subclass of
`ChannelAdapter` (defined in `forward_service/channel/base.py`).

All five members MUST be implemented:

| Member | Type | Description |
|---|---|---|
| `platform` | `@property` → `str` | Lowercase platform identifier |
| `parse_inbound()` | `async def` | Raw callback → `InboundMessage` |
| `send_outbound()` | `async def` | `OutboundMessage` → `SendResult` |
| `extract_bot_key()` | `def` | Extract bot identifier from raw request |
| `should_ignore()` | `def` | Filter non-actionable events (e.g., heartbeats) |

Partial implementations are not allowed. If a platform does not natively
support a concept (e.g., no `user_alias`), return a safe empty default (`""`).

**Rationale**: The unified adapter contract is what allows the pipeline
(`forward_service/pipeline.py`) to be platform-agnostic. Incomplete
implementations break runtime dispatch.

---

## Principle 5 — Reference Implementation

**Name**: WeComAdapter as canonical adapter pattern

`forward_service/channel/wecom.py` is the canonical reference implementation.
All new adapters MUST mirror its structure:

1. Module-level docstring describing the adapter's responsibilities.
2. Platform-specific constants block (`PLATFORM_MAX_MESSAGE_BYTES`, etc.).
3. Adapter class with `platform` property, then `should_ignore`,
   `extract_bot_key`, `parse_inbound`, `send_outbound` in that order.
4. Private helper methods grouped in a clearly delimited section
   (`# ===== 内部方法 =====` or English equivalent).
5. All network calls delegated to the corresponding client in
   `forward_service/clients/` (see Principle 7).

Deviations require a written note in the adapter module docstring explaining
why the deviation was necessary.

**Rationale**: Structural consistency reduces onboarding friction and makes
code review predictable.

---

## Principle 6 — Logging

**Name**: Structured per-module logging

Every module MUST declare a module-level logger using exactly:

```python
logger = logging.getLogger(__name__)
```

The following events MUST be logged at the appropriate level:

| Event | Level |
|---|---|
| Inbound message received (platform, bot_key, user, text snippet) | `INFO` |
| Outbound send attempt (platform, chat_id, message snippet) | `INFO` |
| Message ignored via `should_ignore()` | `DEBUG` |
| Parse failure or unexpected field | `WARNING` |
| Send failure, network error, API error | `ERROR` with `exc_info=True` |

Log messages MUST NOT include secrets (tokens, full API keys). Truncate
message content to ≤ 50 characters in log lines.

**Rationale**: Consistent logging is the primary observability mechanism.
Structured, predictable log lines enable automated alerting and debugging
without requiring access to platform-specific tooling.

---

## Principle 7 — Dependency Usage

**Name**: Use existing clients; do not create new ones

All network communication with external IM platform APIs MUST use the
pre-existing client modules located in `forward_service/clients/`:

- `forward_service/clients/telegram.py`
- `forward_service/clients/lark.py`
- `forward_service/clients/discord.py`
- `forward_service/clients/slack.py`
- `forward_service/clients/wecom_intelligent.py`

Adapters MUST NOT instantiate raw HTTP sessions (e.g., `httpx.AsyncClient`,
`aiohttp.ClientSession`) directly. If a new platform is introduced that truly
has no client yet, the client MUST be created in `forward_service/clients/`
first as a separate, independently reviewed change before the adapter is
written.

**Rationale**: Centralizing HTTP logic in clients allows rate-limiting, retry
policies, and authentication to be managed in one place and reused across
routes and adapters.

---

## Principle 8 — Testing Philosophy

**Name**: Independent adapter testability

Each adapter MUST be testable in isolation without requiring any other
platform's infrastructure to be running. Concretely:

- Unit tests for `parse_inbound()` and `extract_bot_key()` MUST use only
  in-process fixtures (plain dicts, no real network).
- Unit tests for `send_outbound()` MUST mock the corresponding client module.
- Tests MUST NOT depend on shared mutable state across adapter tests.

Test files MUST follow the path convention:
`tests/unit/test_channel_<platform>.py`

**Rationale**: Independent testability is what makes the error isolation
guarantee (Principle 3) provable, not just aspirational.

---

## Principle 9 — No Breaking Changes

**Name**: Purely additive adapter additions

New adapters MUST be registered in `forward_service/channel/registry.py`
without modifying any existing adapter registration. Existing API routes
(`/callback`, `/wecom/*`, etc.) MUST continue to function unchanged after
any new adapter is merged.

Specifically prohibited:
- Modifying `WeComAdapter` code to accommodate a new platform.
- Changing the signatures of `ChannelAdapter` abstract methods in a way that
  requires updates to existing concrete adapters.
- Removing or renaming existing route paths.

Any change to `forward_service/channel/base.py` that modifies abstract method
signatures requires a `MAJOR` version bump to this constitution and explicit
migration notes for all existing adapters.

**Rationale**: The dispatcher is in active production use. Regressions in
WeChat Work handling are high-severity incidents.

---

## Principle 10 — Async I/O

**Name**: Non-blocking event loop

All network calls MUST use `async`/`await`. Blocking I/O (synchronous HTTP
libraries, `time.sleep()`, blocking file reads on the critical path) is
forbidden in the main event loop.

Permitted async I/O libraries: `httpx` (AsyncClient), `aiohttp`, or
client wrappers already present in `forward_service/clients/`.

If a third-party SDK provides only a synchronous interface, it MUST be wrapped
using `asyncio.get_event_loop().run_in_executor()` and documented with a
`# SYNC-WRAPPED:` comment explaining why.

**Rationale**: FastAPI runs on an async event loop (uvicorn/asyncio). A single
blocking call can stall message dispatch for all concurrent users.

---

## Governance

### Amendment Procedure

1. Open a pull request targeting `feature/im-integration` with the proposed
   changes to this file and all affected templates.
2. Changes are accepted by the project lead (or designate) via PR approval.
3. `LAST_AMENDED_DATE` and `CONSTITUTION_VERSION` MUST be updated in the same
   commit as the principle changes.

### Versioning Policy

Semantic versioning applies to this document:

| Change type | Version bump |
|---|---|
| Principle removal, redefinition with incompatible semantics, or breaking change to adapter contract | **MAJOR** |
| New principle added, or existing principle materially expanded | **MINOR** |
| Wording clarification, typo fix, formatting | **PATCH** |

### Compliance Review

- Every plan.md "Constitution Check" section MUST explicitly pass or justify
  a deviation for each of the 10 principles above.
- Code review checkers MUST flag any new file in `forward_service/channel/`
  that does not subclass `ChannelAdapter`.
- Pre-merge checklist items for any adapter PR:
  - [ ] All 5 adapter contract members implemented (Principle 4)
  - [ ] Module-level logger declared (Principle 6)
  - [ ] All functions type-annotated (Principle 2)
  - [ ] `send_outbound()` returns `SendResult` on error, does not raise (Principle 3)
  - [ ] Existing routes verified unmodified (Principle 9)
  - [ ] No synchronous HTTP calls (Principle 10)
