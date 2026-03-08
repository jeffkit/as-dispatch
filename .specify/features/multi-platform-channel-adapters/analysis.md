# Specification Analysis Report

**Feature**: Multi-Platform IM ChannelAdapter Unification  
**Analyzed**: 2026-03-02  
**Branch**: `feature/im-integration`  
**Analyzer**: speckit-analyze (read-only)

---

## Executive Summary

- **Total Findings**: 11
- **Critical**: 0
- **High**: 2 ⚠️
- **Medium**: 6
- **Low**: 3

**Overall Status**: ⚠️ **CAUTION**

Two HIGH-severity inconsistencies should be resolved before or during implementation. They do not block starting work but will cause a success-criteria gap (SC-006 Lark images) and a potential spec-plan contract conflict (FR-022 vs T012) that reviewers are likely to flag.

---

## Findings

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| F1 | Inconsistency | HIGH | spec.md SC-006, plan.md Phase-0 table | SC-006 requires "at least one image **URL** in the `images` field" for all four platforms, but the plan explicitly stores Lark `image_key` (not a URL) as an MVP deferral. SC-006 will **not** be satisfied for Lark at release. | Either (a) weaken SC-006 to say "image reference (URL or key)" for Lark, explicitly noting the deferral, or (b) add a task to resolve Lark image_key to a download URL before marking Phase 3 complete. Also update T020 to mark SC-006 as partially deferred rather than fully ✅. |
| F2 | Inconsistency | HIGH | spec.md FR-022, tasks.md T012, plan.md Complexity Tracking | FR-022 states existing Discord/Telegram/Lark/Slack routes "MUST remain operational and **unchanged**". T012 explicitly rewrites the `handle_discord_message` body. The plan justifies this in Complexity Tracking, but the spec text says "unchanged", creating a contract conflict that reviewers can challenge. | Add a one-sentence addendum to spec.md FR-022: "The `handle_discord_message` implementation may be updated to delegate to the unified pipeline; the route path and WebSocket lifecycle are considered the operative 'unchanged' scope." This closes the gap between the spec MUST and the documented plan deviation. |
| F3 | Inconsistency | MEDIUM | spec.md FR-010, plan.md §7, plan.md Phase-0 table | FR-010 uses the phrase "Discord's **interaction webhook** payload format" — Discord interactions are a separate mechanism (slash commands). What the feature actually implements is the **WebSocket gateway** (discord.py `on_message`). Using "interaction webhook" in the spec may mislead future readers or cause misalignment with Discord API documentation. | Revise FR-010 to: "The system MUST parse Discord gateway `Message` objects (received via WebSocket) into `InboundMessage`." |
| F4 | Inconsistency | MEDIUM | tasks.md SC Traceability table, row SC-008 | SC-008 traceability lists "T013/T014 (Discord)" for bot-message filtering. T013 is `forward_service/app.py` adapter registration — it performs no filtering. The correct task reference for Discord bot filtering is T012 (`routes/discord.py` update, which includes the `if message.author.bot: return` guard). | Change SC-008 Discord reference in the traceability table from "T013/T014" to "T012/T014". |
| F5 | Coverage Gap | MEDIUM | spec.md Edge Cases §1, tasks.md (all phases) | Spec Edge Case 1: "The system must **de-duplicate** to avoid sending the AI pipeline the same message twice." Slack handles this via `X-Slack-Retry-Num` (FR-016 / T015). However, no requirement or task addresses retry/deduplication for **Telegram, Lark, or Discord**. | Either (a) add FR-027 and a corresponding task for platform-agnostic message-ID deduplication (e.g., an in-memory or Redis set of recent `message_id`s), or (b) explicitly note in the spec edge case that per-platform retry headers are the only mechanism and Telegram/Lark/Discord are accepted as "best-effort" in this release. |
| F6 | Underspecification | MEDIUM | tasks.md T020, plan.md Project Structure | T020 references `docs/MULTI_PLATFORM_ROADMAP.md` for a completion update, but this file path does not appear in the plan's Project Structure section or in the spec. It is unclear whether this file already exists, where it lives in the repo, or what its format is. | Add the file path to plan.md Project Structure (e.g., `docs/MULTI_PLATFORM_ROADMAP.md — MODIFY`) and confirm it exists before T020 is executed. If it does not exist yet, T020 should read "CREATE" not "MODIFY". |
| F7 | Inconsistency | MEDIUM | plan.md §3 (TelegramAdapter module structure comment) | The TelegramAdapter private helper description reads: `_extract_message(raw_data) → **discord.Message** dict or None`. This is a copy-paste error from the Discord adapter design; Telegram has no `discord.Message` type. The actual return type should be "Telegram `message` dict or `None`". | Correct to: `_extract_message(raw_data) → Telegram message dict or None`. This is documentation only but will confuse any developer reading the plan. |
| F8 | Inconsistency | LOW | tasks.md header | The tasks.md header declares **"Total Tasks: 22"** but the file defines exactly **20 tasks** (T001–T020 across 6 phases: 3+4+3+4+3+3). The count is off by 2. | Update the header to "Total Tasks: 20" or add two missing tasks if they were accidentally omitted. |
| F9 | Underspecification | LOW | tasks.md T019, spec.md SC-001–SC-004 | T019 (end-to-end smoke verification) is described as "manual or scripted" with no code deliverable. Success criteria SC-001 (all 5 platforms), SC-002 (≤ 30 s reply), and SC-004 (error isolation) are verified only by this ad-hoc task. No automated integration test exists to prevent regressions in future PRs. | Consider adding an `integration/` test directory with a scripted smoke test (pytest with live mocks or a `conftest.py` that replays captured payloads), so T019 produces an artifact that the CI pipeline can run. This is optional for this release but should be noted as a follow-up. |
| F10 | Coverage Gap | LOW | spec.md Edge Cases §2, tasks.md (all phases) | Spec Edge Case 2: "When the AI backend is temporarily unavailable, the adapter returns an error response... **no message is silently dropped**." No task explicitly tests or documents this behavior. The pipeline's error-handling path likely covers this, but it is not verified by any task acceptance criterion. | Add a unit-test case in T007/T010/T014/T017 (or a shared integration test in T019) that mocks `process_message()` to raise an exception and confirms the adapter returns a non-200 response and logs at ERROR level. |
| F11 | Inconsistency | LOW | plan.md §5 DiscordAdapter `_get_bot_client`, plan.md Risks table | `DiscordAdapter._get_bot_client()` contains a lazy import: `from ..routes.discord import discord_bots`. This creates a runtime circular dependency (`channel.discord` ↔ `routes.discord`). The lazy import avoids a module-load error, but the coupling is not mentioned in the Risks table, where only the "bot instance not running" scenario is documented. | Add to the Risks table: "Circular import between `channel/discord.py` and `routes/discord.py` | Low | Low | Lazy import inside `_get_bot_client()` prevents module-load failure; validate with `import forward_service.channel.discord` in a clean interpreter before merging." |

---

## Coverage Summary

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| FR-001 (Telegram parse) | ✓ | T005 | |
| FR-002 (Telegram bot filter) | ✓ | T005, T007 | |
| FR-003 (Telegram images) | ✓ | T004, T005 | |
| FR-004 (Telegram client delegation) | ✓ | T005 | |
| FR-005 (Lark event structure) | ✓ | T008 | |
| FR-006 (Lark AES decryption) | ✓ | T008, T010 | |
| FR-007 (Lark URL verification) | ✓ | T003, T008 | |
| FR-008 (Lark images) | ✓ | T008 | ⚠️ Stores image_key not URL — see F1 |
| FR-009 (Lark client delegation) | ✓ | T008 | |
| FR-010 (Discord parse) | ✓ | T011 | ⚠️ "Interaction webhook" terminology — see F3 |
| FR-011 (Discord self-message filter) | ✓ | T011, T012, T014 | |
| FR-012 (Discord images) | ✓ | T011, T014 | |
| FR-013 (Discord client delegation) | ✓ | T011 | |
| FR-014 (Slack parse) | ✓ | T015 | |
| FR-015 (Slack URL verification) | ✓ | T003, T015 | |
| FR-016 (Slack retry ignore) | ✓ | T002, T015 | |
| FR-017 (Slack bot filter) | ✓ | T015, T017 | |
| FR-018 (Slack images) | ✓ | T015 | |
| FR-019 (Slack client delegation) | ✓ | T015 | |
| FR-020 (Register all adapters) | ✓ | T006, T009, T013, T016 | |
| FR-021 (Registry-based dispatch) | ✓ | T001 | |
| FR-022 (Existing routes unchanged) | ✓ (partial) | T019 | ⚠️ T012 modifies Discord handler — see F2 |
| FR-023 (WeComAdapter unchanged) | ✓ | T001 + all checkpoints | |
| FR-024 (All 5 adapter members) | ✓ | T005, T008, T011, T015 | |
| FR-025 (Per-adapter error isolation) | ✓ | T005, T008, T011, T015 | |
| FR-026 (Structured logging) | ✓ | T005, T008, T011, T015 | No explicit log-format test |

**Coverage Metrics**:
- Total Requirements: 26
- Requirements with Tasks: 26 (100% coverage)
- Requirements without Tasks: 0
- Requirements with partial/quality gaps: 3 (FR-008, FR-010, FR-022)

---

## Success Criteria Traceability (Corrected)

| SC | Description | Verified By | Status |
|----|-------------|-------------|--------|
| SC-001 | All 5 platforms end-to-end | T019 | ✓ |
| SC-002 | AI reply ≤ 30 s | T019 (timed) | ✓ |
| SC-003 | Zero WeChat regression | Checkpoints + T019 | ✓ |
| SC-004 | Error isolation | T019 + T007/T010/T014/T017 | ✓ |
| SC-005 | Unit test coverage per adapter | T007, T010, T014, T017 | ✓ |
| SC-006 | Image forwarding all platforms | T007 (Telegram), T010 (Lark⚠️), T014 (Discord), T017 (Slack) | ⚠️ Lark stores image_key not URL |
| SC-007 | URL challenges < 3 s | T003, T010, T017 | ✓ |
| SC-008 | Bot-message filtering | T007 (Telegram), **T012/T014** (Discord, corrected), T017 (Slack) | ✓ (traceability table error noted) |

---

## Constitution Alignment

The plan's Constitution Check section (plan.md §3) correctly evaluates all 10 principles. The only nuance not covered is:

| Principle | Finding | Location | Severity |
|-----------|---------|----------|----------|
| P9 (No Breaking Changes) | T012 modifies existing `routes/discord.py` handler; plan documents this in Complexity Tracking but spec FR-022 says "unchanged" | plan.md Complexity Tracking vs spec.md FR-022 | See F2 (HIGH) |
| P7 (Use existing clients) | `_get_bot_client()` in DiscordAdapter lazy-imports from `routes.discord` creating circular coupling; risk not documented | plan.md §5 | See F11 (LOW) |

✓ All other 10 constitution principles are correctly verified in the plan.

---

## Unmapped Tasks

✓ All 20 tasks map to user stories or functional requirements.

| Task | Requirement/Story | Notes |
|------|-------------------|-------|
| T018 | US5 | Package `__init__.py` exports — useful housekeeping, no specific FR |
| T019 | US5 / SC-001–SC-004 | Manual verification — see F9 |
| T020 | US5 | Roadmap documentation — see F6 |

---

## Metrics

- **Total Functional Requirements**: 26
- **Total User Stories**: 5
- **Total Tasks (actual)**: 20 *(header incorrectly states 22 — see F8)*
- **Requirements Coverage**: 100% (26/26 with ≥1 task)
- **Ambiguity Count**: 1 (FR-010 "interaction webhook" terminology)
- **Duplication Count**: 0
- **Critical Issues**: 0
- **High Issues**: 2
- **Medium Issues**: 6
- **Low Issues**: 3

---

## Next Actions

### ⚠️ PROCEED WITH CAUTION

No CRITICAL issues. Two HIGH-priority inconsistencies should be addressed before or during Phase 3 implementation (Lark Adapter).

**Recommended actions before implementation starts:**

1. **F1 (HIGH)** — Choose one path for SC-006 / Lark image handling:
   - Option A: Relax SC-006 to accept `image_key` as a valid image reference for Lark (update spec.md SC-006 wording and add a note to T010)
   - Option B: Add a new task (T021) to resolve Lark `image_key` → download URL via Lark's image download API before Phase 3 is considered done

2. **F2 (HIGH)** — Patch spec.md FR-022 to acknowledge the Discord handler modification:
   > Add: "For Discord, the `handle_discord_message` implementation may be updated to delegate to the unified pipeline; the route path and WebSocket lifecycle are the operative definition of 'unchanged'."

**Can be addressed during implementation (non-blocking):**

3. **F3** — Correct FR-010 Discord terminology from "interaction webhook" to "WebSocket gateway message"
4. **F4** — Fix SC-008 traceability table (T013 → T012 for Discord)
5. **F5** — Decide deduplication scope: add task or explicitly annotate as out-of-scope for Telegram/Lark/Discord
6. **F6** — Verify `docs/MULTI_PLATFORM_ROADMAP.md` exists; add to plan structure
7. **F7** — Fix copy-paste error in plan.md §3 TelegramAdapter structure comment
8. **F8** — Correct task count header from 22 to 20

---

## Remediation Assistance

Would you like concrete edit suggestions for any of the above findings?

Priority recommendations:

### For F1 (HIGH) — SC-006 Lark Image Gap

**File**: spec.md  
**Current SC-006**:
> "Image messages from all four new platforms are correctly forwarded to the AI pipeline with at least one image URL in the images field."

**Suggested replacement**:
> "Image messages from all four new platforms are correctly forwarded to the AI pipeline. For Telegram, Discord, and Slack, at least one image URL is included in the `images` field. For Lark, the `image_key` is included as an image reference (URL resolution via Lark's download API is deferred to Phase 2 of the roadmap)."

---

### For F2 (HIGH) — FR-022 Discord Deviation

**File**: spec.md  
**Current FR-022**:
> "The existing independent routes for Telegram, Lark, Discord, and Slack MUST remain operational and unchanged for backward compatibility."

**Suggested replacement**:
> "The existing independent routes for Telegram, Lark, Discord, and Slack MUST remain operational for backward compatibility. Route paths MUST NOT be renamed or removed. For Discord, the `handle_discord_message` WebSocket handler implementation may be updated to delegate to the unified pipeline; the route path, WebSocket lifecycle, and user-visible behavior are the operative definition of 'unchanged'. The Telegram, Lark, and Slack independent routes are not modified by this feature."

---

### For F4 (MEDIUM) — SC-008 Traceability Table Correction

**File**: tasks.md  
**Current row**:
```
| SC-008 | Bot-message filtering | T007 (Telegram), T013/T014 (Discord), T017 (Slack) |
```

**Corrected row**:
```
| SC-008 | Bot-message filtering | T007 (Telegram), T012/T014 (Discord), T017 (Slack) |
```
