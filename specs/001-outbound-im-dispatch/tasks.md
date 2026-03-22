# Tasks: Outbound IM Dispatch

**Input**: Design documents from `/specs/001-outbound-im-dispatch/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Unit tests are included in Phase 5 (Integration & Testing) as specified in plan.md Phase E.

**Organization**: Tasks are grouped by implementation phase (A-E from plan.md), mapped to user stories US1 (Web-to-IM Forwarding) and US2 (IM Reply Routing). Phase F (P2-Story3 Scheduled Task) is deferred.

**Already Done**: OutboundMessageContext model, repository methods (`create_outbound_context`, `find_context_by_message_id`, `mark_context_replied`, `cleanup_expired_contexts`), migration, outbound_context_api.py, and initial callback.py `quoted_message_id` routing — all committed in `f02463b`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **as-dispatch** (Python): `forward_service/`, `tests/`
- **AgentStudio backend** (Node.js): `agentstudio/backend/src/`
- **AgentStudio frontend** (React): `agentstudio/frontend/src/`

---

## Phase 1: Setup & Foundation

**Purpose**: Shared utilities and configuration changes that Phase A–D depend on. No new endpoints yet.

- [X] T001 [P] [US1] Create `forward_service/utils/short_id.py` — implement `generate_outbound_short_id()` using `"ob_" + secrets.token_hex(3)`; include uniqueness validation helper (accept an async `exists_checker` callback)
- [X] T002 [P] [US1] Extend `SHORT_ID_PATTERN` in `forward_service/utils/content.py` to support `ob_` prefix — update regex from `[a-f0-9]{6,8}` to also match `ob_[a-f0-9]{6}`; ensure `extract_content_parts()` returns `ob_xxxxxx` as `quoted_short_id`
- [X] T003 [US1] Update `expires_at` default in `forward_service/models.py` `OutboundMessageContext` — change from `timedelta(hours=24)` to `timedelta(days=7)` per spec FR-006

**Checkpoint**: Shared utilities ready — Phase A and Phase B can proceed.

---

## Phase 2: User Story 1 — Web-to-IM Message Forwarding (Priority: P1) 🎯 MVP

**Goal**: User clicks "Forward to WeChat Work" on an AI message bubble → message is sent to the configured group with routing header `[#ob_xxxxxx ProjectName]`, user sees confirmation.

**Independent Test**: Send a message from AgentStudio Web UI to a WeChat Work group; verify the message arrives with the correct `[#ob_xxxxxx ProjectName]` routing header and the UI shows success status.

### Phase 2A: as-dispatch — 出站发送端点

- [ ] T004 [US1] Create `forward_service/routes/im_send.py` — implement `POST /api/im/send` endpoint with `require_enterprise_jwt` auth:
  - Accept `DispatchRequest` body (message_content, bot_key, chat_id, session_id, agent_id?, project_name?, msg_type?)
  - Call `generate_outbound_short_id()` from T001
  - Prepend routing header `[#ob_xxxxxx ProjectName]\n\n` to message_content
  - Wrap `send_to_wecom()` (fly-pigeon sync) via `asyncio.get_event_loop().run_in_executor()`
  - On success: save `OutboundMessageContext` via `create_outbound_context()` with `expires_at = now + 7 days`
  - On failure: return `{ success: false, error }` without persisting context
  - Return `{ success: true, short_id, message_with_header }`
- [ ] T005 [US1] Register `im_send_router` in `forward_service/routes/__init__.py` — add import and `__all__` entry
- [ ] T006 [US1] Mount `im_send_router` in `forward_service/app.py` — add `app.include_router(im_send_router)`

### Phase 2C: AgentStudio — 后端代理端点

- [ ] T007 [US1] Create `agentstudio/backend/src/services/dispatchService.ts` — implement as-dispatch API client:
  - `generateJWT()`: sign JWT with `JWT_SECRET_KEY` env var using `jsonwebtoken`
  - `sendToIM(params)`: POST to `${AS_DISPATCH_URL}/api/im/send` with JWT Bearer auth
  - Timeout: 10 seconds
  - Error handling: network errors → `{ success: false, error }`
- [ ] T008 [US1] Add `POST /api/agui/dispatch-im` route in `agentstudio/backend/src/routes/agui.ts`:
  - Accept `{ sessionId, messageContent, botKey, chatId, projectName?, agentId? }`
  - Call `dispatchService.sendToIM()` from T007
  - Return `{ success, shortId, error? }` to frontend

### Phase 2D: AgentStudio — 前端 UI

- [ ] T009 [P] [US1] Create `agentstudio/frontend/src/types/dispatch.ts` — define TypeScript types:
  - `DispatchIMRequest`: sessionId, messageContent, botKey, chatId, projectName?, agentId?
  - `DispatchIMResponse`: success, shortId?, error?
  - `DispatchStatus`: 'idle' | 'sending' | 'sent' | 'error'
- [ ] T010 [US1] Create `agentstudio/frontend/src/hooks/useDispatchIM.ts` — implement dispatch hook:
  - `dispatchToIM(request)`: call `POST /api/agui/dispatch-im`
  - Track per-message `DispatchStatus` state
  - Return `{ dispatchToIM, getStatus, resetStatus }`
- [ ] T011 [US1] Create `agentstudio/frontend/src/components/chat/DispatchIMDialog.tsx` — confirmation dialog:
  - Show target group info (chatId / bot name)
  - Show message preview (first 100 chars)
  - Confirm / Cancel buttons
  - Loading state during dispatch
- [ ] T012 [US1] Modify `agentstudio/frontend/src/components/chat/MessageBubble.tsx`:
  - Add forward icon button on AI message bubbles (only when project has `botKey` + `chatId` configured)
  - Wire button → open `DispatchIMDialog`
  - Show dispatch status indicator: sending spinner, "已转发" icon+tooltip (with short_id), error state
  - Support re-dispatch (each forward generates new short_id)

**Checkpoint**: User Story 1 complete — Web-to-IM forwarding is fully functional and independently testable.

---

## Phase 3: User Story 2 — IM Reply Routing Back to Agent Conversation (Priority: P1)

**Goal**: User quotes a forwarded message in WeChat Work → reply is automatically injected into the originating AgentStudio Agent conversation.

**Independent Test**: After forwarding a message (US1), reply to it in WeChat Work by quoting. Verify the reply appears in the original AgentStudio session and triggers the Agent to respond.

### Phase 3B: as-dispatch — 回调路由增强

- [ ] T013 [US2] Modify `forward_service/routes/callback.py` — add `ob_` prefix short_id routing branch:
  - In the quote-reply routing section, BEFORE the existing `quoted_message_id` logic, add:
    1. Check if `quoted_short_id` starts with `ob_`
    2. If yes: query `find_context_by_message_id(quoted_short_id)` from OutboundMessageContext
    3. If found: extract `session_id` from context, derive AgentStudio URL from bot config `target_url`
    4. Call `POST <agentstudio_url>/api/agui/sessions/{sessionId}/inject` with `{ message: reply_text, sender: "wecom-reply", workspace: project_name }` using `httpx.AsyncClient`
    5. On inject success: `mark_context_replied()`
    6. On inject failure: log ERROR, fall through to existing routing (silent fallback per FR-009)
  - Maintain existing routing priority: ob_short_id > quoted_message_id > HITL quoted_short_id > active session
  - Use `httpx.AsyncClient` for async HTTP (P10 compliance)

**Checkpoint**: User Story 2 complete — Full bidirectional loop: Web → IM → reply → Agent conversation.

---

## Phase 4: Unit Tests & Edge Cases (Phase E)

**Purpose**: Validate complete flow, edge cases, and error handling across both sub-projects.

### as-dispatch tests

- [ ] T014 [P] [US1] Create `tests/unit/test_short_id.py` — tests for `generate_outbound_short_id()`:
  - Format validation: starts with `ob_`, 8 chars total, hex suffix
  - Uniqueness across multiple calls
  - `secrets.token_hex(3)` output length
- [ ] T015 [P] [US1] Create `tests/unit/test_im_send.py` — tests for `POST /api/im/send`:
  - Happy path: valid request → success response with short_id
  - Routing header format: `[#ob_xxxxxx ProjectName]\n\n<content>`
  - Send failure: fly-pigeon error → `{ success: false, error }`, no context persisted
  - Missing required fields → 422
  - JWT auth enforcement
- [ ] T016 [P] [US2] Create `tests/unit/test_outbound_routing.py` — tests for callback ob_ routing:
  - Quote-reply with `ob_xxxxxx` → matches outbound context → injects to AgentStudio
  - Quote-reply with expired `ob_xxxxxx` → falls back to existing routing
  - Quote-reply with invalid `ob_xxxxxx` (not in DB) → falls back to existing routing
  - Non-quote reply → no outbound matching
  - AgentStudio inject failure → silent fallback, ERROR logged
  - Existing HITL routing unchanged (regression)

### Edge case validation

- [ ] T017 [US1] Verify repeated dispatch of the same message generates different `short_id` values (each forward creates new OutboundMessageContext)
- [ ] T018 [US2] Verify `SHORT_ID_PATTERN` in `forward_service/utils/content.py` correctly extracts both `ob_xxxxxx` and legacy `[a-f0-9]{6,8}` short_ids

**Checkpoint**: All tests pass — both user stories verified with edge cases.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, configuration, and cleanup tasks.

- [ ] T019 [P] Update `specs/001-outbound-im-dispatch/quickstart.md` with end-to-end manual test steps for both US1 and US2
- [ ] T020 [P] Add environment variable documentation (AS_DISPATCH_URL, JWT_SECRET_KEY) to AgentStudio's config/README
- [ ] T021 Code review: verify all new modules have `logger = logging.getLogger(__name__)` (P6 compliance) and complete type annotations (P2 compliance)
- [ ] T022 Run `quickstart.md` end-to-end validation scenario

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
  ├── T001, T002 can run in parallel
  └── T003 independent
      │
      ├──────────────────────────────┐
      ▼                              ▼
Phase 2 (US1: Web-to-IM)       Phase 3 (US2: Reply Routing)
  T004 → T005 → T006              T013 depends on T002 (ob_ regex)
  T007 → T008                       and T004 (outbound context exists)
  T009 ──┐
  T010 → T011 → T012
      │
      ▼
Phase 4 (Tests)
  T014, T015, T016 in parallel
  T017, T018 after tests
      │
      ▼
Phase 5 (Polish)
  T019, T020 in parallel → T021 → T022
```

### User Story Dependencies

- **User Story 1 (P1)**: Requires Phase 1 (T001–T003). Can be completed independently — delivers value without reply routing.
- **User Story 2 (P1)**: Requires Phase 1 (T002 for regex) + Phase 2A (T004 for context creation). Reply routing completes the bidirectional loop.
- **User Story 3 (P2)**: DEFERRED — depends on AgentStudio scheduling/hooks infrastructure. Will reuse `POST /api/im/send` from T004.

### Cross-Project Dependencies

- **T007–T008** (AgentStudio backend) depend on **T004** (as-dispatch endpoint) being available for integration
- **T010–T012** (AgentStudio frontend) depend on **T008** (backend proxy endpoint)
- **T013** (callback inject) depends on AgentStudio's existing `POST /api/agui/sessions/:sessionId/inject` (already implemented)

### Within Each Phase

- Utilities (T001, T002) before endpoints (T004)
- Backend endpoints (T004–T006, T007–T008) before frontend UI (T009–T012)
- Implementation before tests (Phase 4 after Phase 2+3)

### Parallel Opportunities

- **Phase 1**: T001 and T002 can run in parallel (different files)
- **Phase 2**: After T004–T006 (as-dispatch), T007–T008 (AgentStudio backend) and T013 (callback) can start in parallel
- **Phase 2D**: T009 (types) can run in parallel with T007–T008 (different project)
- **Phase 4**: T014, T015, T016 all in parallel (different test files)
- **Phase 5**: T019 and T020 in parallel

---

## Parallel Example: Phase 2 (after Phase 1 complete)

```text
# Stream 1: as-dispatch endpoint
Task T004: Create POST /api/im/send in forward_service/routes/im_send.py
Task T005: Register router in forward_service/routes/__init__.py
Task T006: Mount router in forward_service/app.py

# Stream 2 (after T004 done): AgentStudio backend
Task T007: Create dispatchService.ts in agentstudio/backend/src/services/
Task T008: Add dispatch-im route in agentstudio/backend/src/routes/agui.ts

# Stream 3 (parallel with Stream 2): as-dispatch callback
Task T013: Modify callback.py for ob_ routing

# Stream 4 (parallel with Stream 2): frontend types
Task T009: Create dispatch.ts types in agentstudio/frontend/src/types/
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: T001–T003 (shared utilities)
2. Complete Phase 2A: T004–T006 (as-dispatch endpoint)
3. Complete Phase 2C: T007–T008 (AgentStudio backend proxy)
4. Complete Phase 2D: T009–T012 (AgentStudio frontend UI)
5. **STOP and VALIDATE**: Test Web-to-IM forwarding end-to-end
6. Deploy/demo if ready — US1 delivers standalone value

### Full P1 Delivery

1. After MVP validated, add Phase 3: T013 (callback routing)
2. Complete Phase 4: T014–T018 (tests + edge cases)
3. Complete Phase 5: T019–T022 (polish)

### Incremental Delivery

1. Phase 1 (Setup) → Foundation ready
2. Phase 2 (US1) → Web-to-IM forwarding works → Demo/Deploy (MVP)
3. Phase 3 (US2) → Reply routing works → Complete bidirectional loop
4. Phase 4 (Tests) → Quality validated
5. Phase 5 (Polish) → Production ready

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to US1 (Web-to-IM Forwarding) or US2 (IM Reply Routing)
- Phase F (P2-Story3: Scheduled Task IM Notification) is intentionally deferred
- Model, repository, migration, and outbound_context_api.py are already committed — tasks start from new code
- `repository.py` method `create_outbound_context()` already accepts `expires_at` implicitly via model default — T003 changes the default
- Avoid modifying `forward_service/sender.py` and `forward_service/channel/wecom.py` (P9: additive only)
- All new async HTTP calls must use `httpx.AsyncClient` (P10: no blocking I/O)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
