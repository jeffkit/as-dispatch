# Tasks: 个人微信通道接入 (Weixin Channel)

**Input**: Design documents from `/specs/001-weixin-channel/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/admin-api.md ✅

**Tests**: Not explicitly requested in spec — test tasks are omitted. Unit test file `tests/unit/test_channel_weixin.py` is documented in plan.md and can be added later.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project** (additive to existing `forward_service/`):
  - New files: `forward_service/clients/weixin.py`, `forward_service/channel/weixin.py`, `forward_service/routes/weixin.py`
  - Modified files: `forward_service/app.py`, `forward_service/channel/__init__.py`, `forward_service/routes/__init__.py`

---

## Phase 1: Setup (File Skeletons)

**Purpose**: Create the 3 new module files with docstrings, logger declarations, constants, shared types, and empty class/function stubs. No business logic yet.

- [X] T001 Create `forward_service/clients/weixin.py` with module docstring, `logger = logging.getLogger(__name__)`, `BASE_URL = "https://ilinkai.weixin.qq.com"`, and `WeixinClient` class skeleton: `__init__(self, bot_token: str)` initializing `httpx.AsyncClient` with auth headers (`Authorization: Bearer`, `AuthorizationType: ilink_bot_token`, `X-WECHAT-UIN`), and `async def close(self)` to shut down the HTTP client
- [X] T002 [P] Create `forward_service/channel/weixin.py` with module docstring (per P5 structure), `logger`, message type constants (`WEIXIN_MSG_TYPE_TEXT = 1` through `VIDEO = 5`), `WEIXIN_MSG_TYPE_NAMES` dict, `WEIXIN_NON_TEXT_PLACEHOLDERS` dict, `WeixinPollerStatus(str, Enum)` with 5 states (`STOPPED`, `RUNNING`, `PAUSED`, `EXPIRED`, `LOGIN_PENDING`), and empty `WeixinAdapter(ChannelAdapter)` class stub with `platform` property returning `"weixin"`
- [X] T003 [P] Create `forward_service/routes/weixin.py` with module docstring, `logger`, `weixin_admin_router = APIRouter(prefix="/admin/weixin", tags=["weixin-admin"])`, `QRLoginAttempt` dataclass (fields: `qrcode`, `qrcode_url`, `status`, `refresh_count`, `created_at`, `bot_token`, `ilink_bot_id`, `ilink_user_id`), `WeixinPoller` dataclass skeleton (fields: `bot_key`, `client`, `status`, `get_updates_buf`, `context_tokens`, `consecutive_failures`, `_task`, `ilink_bot_id`), and module-level dicts `weixin_pollers: dict[str, WeixinPoller] = {}` and `weixin_login_attempts: dict[str, QRLoginAttempt] = {}`

---

## Phase 2: Foundational (Registration in Existing Files)

**Purpose**: Wire the new modules into the existing as-dispatch platform. MUST be complete before any user story implementation.

**⚠️ CRITICAL**: These are purely additive changes per constitution P9 — no existing adapter registrations or routes are modified.

- [X] T004 [P] Add `WeixinAdapter` import and export in `forward_service/channel/__init__.py`: add `from .weixin import WeixinAdapter` to imports, add `"WeixinAdapter"` to `__all__`, and update module docstring to include `from forward_service.channel import WeixinAdapter`
- [X] T005 [P] Add `weixin_admin_router` import and export in `forward_service/routes/__init__.py`: add `from .weixin import weixin_admin_router` and `"weixin_admin_router"` to `__all__`
- [X] T006 Register Weixin channel in `forward_service/app.py`: import `WeixinAdapter` from `.channel.weixin`, import `weixin_admin_router` from `.routes`, call `register_adapter(WeixinAdapter())` in lifespan (after existing adapters), `app.include_router(weixin_admin_router)` (after `qqbot_admin_router`), and add auto-start logic for previously logged-in weixin bots + shutdown cleanup (following QQBot pattern with `asyncio.create_task` and `weixin_pollers` cleanup)

**Checkpoint**: All 3 new modules are importable, router is mounted, adapter is registered. Platform starts without errors.

---

## Phase 3: User Story 1 — QR Code Login for WeChat Bot Account (Priority: P1) 🎯 MVP

**Goal**: Admin can trigger QR code generation, scan with WeChat, and obtain valid bot credentials persisted to the database.

**Independent Test**: Call `POST /admin/weixin/{bot_key}/qr-login` → get QR code URL → poll `GET /admin/weixin/{bot_key}/qr-status` → scan QR → verify status transitions (wait → scaned → confirmed) and credentials saved to `chatbot.platform_config`.

**FRs covered**: FR-001, FR-002, FR-003, FR-004, FR-019

### Implementation for User Story 1

- [X] T007 [US1] Implement `WeixinClient.get_qrcode(self) -> dict` calling `GET /ilink/bot/get_bot_qrcode?bot_type=3` (10s timeout) and `WeixinClient.get_qrcode_status(self, qrcode: str) -> dict` calling `GET /ilink/bot/get_qrcode_status?qrcode={qrcode}` (10s timeout) in `forward_service/clients/weixin.py`
- [X] T008 [US1] Implement `POST /admin/weixin/{bot_key}/qr-login` endpoint in `forward_service/routes/weixin.py`: validate bot exists and is weixin platform (query chatbot from DB), create a temporary `WeixinClient` (no bot_token needed for QR generation — use empty token or app-level auth), call `client.get_qrcode()`, store `QRLoginAttempt` in `weixin_login_attempts[bot_key]`, return `{success, bot_key, qrcode, qrcode_url, message}` per contract
- [X] T009 [US1] Implement `GET /admin/weixin/{bot_key}/qr-status` endpoint in `forward_service/routes/weixin.py`: look up `QRLoginAttempt` from `weixin_login_attempts[bot_key]`, call `client.get_qrcode_status(attempt.qrcode)`, handle status transitions: `wait` → return waiting, `scaned` → return scanned message, `expired` → auto-refresh QR (increment `refresh_count`, call `get_qrcode()` again, max 3 times per FR-003), `confirmed` → extract `bot_token`, `ilink_bot_id`, `ilink_user_id` from response
- [X] T010 [US1] Implement credential persistence on login success in `forward_service/routes/weixin.py`: on `confirmed` status, update `chatbot.platform_config` JSON in database with `bot_token`, `ilink_bot_id`, `ilink_user_id`, `login_status: "logged_in"`, `last_active_at` (per data-model.md §1.1), clean up `weixin_login_attempts[bot_key]`, return success response with `ilink_bot_id` per contract

**Checkpoint**: Admin can complete the full QR login flow via API. Credentials are persisted to DB and survive service restarts.

---

## Phase 4: User Story 2 — Send and Receive Text Messages (Priority: P1) 🎯 MVP

**Goal**: A WeChat user sends a text message to the bot's account and receives an AI-generated text reply via the existing as-dispatch pipeline.

**Independent Test**: Start a logged-in bot → send text message from WeChat → verify message arrives in as-dispatch pipeline → verify AI reply is delivered back to WeChat user.

**FRs covered**: FR-005, FR-006, FR-007, FR-009, FR-015, FR-016, FR-017

### Implementation for User Story 2

- [X] T011 [US2] Implement `WeixinClient.get_updates(self, ilink_bot_id: str, get_updates_buf: str) -> dict` in `forward_service/clients/weixin.py`: POST to `/ilink/bot/getupdates` with body `{ilink_bot_id, get_updates_buf}`, 40s client timeout (35s server + 5s buffer per research Decision 1), return parsed response dict
- [X] T012 [US2] Implement `WeixinClient.send_message(self, ilink_bot_id: str, to_user_id: str, context_token: str, text: str) -> dict` in `forward_service/clients/weixin.py`: POST to `/ilink/bot/sendmessage` with body `{ilink_bot_id, to_user_id, context_token, item_list: [{type: 1, content: text}]}`, 30s timeout, return response dict
- [X] T013 [US2] Implement `WeixinAdapter.should_ignore(self, raw_data: dict) -> bool` in `forward_service/channel/weixin.py`: return True for non-direct messages (group chat per FR-017) and bot's own messages (message_state != 3/finished); implement `WeixinAdapter.extract_bot_key(self, raw_data: dict) -> str` returning `raw_data["_bot_key"]` injected by the poller
- [X] T014 [US2] Implement `WeixinAdapter.parse_inbound(self, raw_data: dict) -> InboundMessage` in `forward_service/channel/weixin.py`: map iLinkAI fields to InboundMessage per data-model.md §2.5 — `platform="weixin"`, `bot_key` from `_bot_key`, `user_id` from `sender_id`, `chat_id` as `f"direct:{sender_id}"`, `chat_type="direct"`, `text` from first TEXT item, `msg_type` from `WEIXIN_MSG_TYPE_NAMES`, `message_id` from content hash, `raw_data` preserved with `context_token`
- [X] T015 [US2] Implement non-text message handling in `WeixinAdapter.parse_inbound()` in `forward_service/channel/weixin.py`: detect `item_list[0].type` != 1, set `text` to corresponding `WEIXIN_NON_TEXT_PLACEHOLDERS[type]` value, set `msg_type` to the type name — placeholder messages flow through pipeline and are replied back to user (FR-007)
- [X] T016 [US2] Implement `WeixinAdapter.send_outbound(self, message: OutboundMessage) -> SendResult` in `forward_service/channel/weixin.py`: look up `context_token` from `raw_data`, delegate to `WeixinClient.send_message()` via the active `WeixinPoller` instance (access through `weixin_pollers[bot_key]`), wrap in try/except returning `SendResult(success=False, error=...)` on failure per constitution P3
- [X] T017 [US2] Implement `WeixinPoller._poll_loop(self)` and `handle_weixin_message()` in `forward_service/routes/weixin.py`: infinite loop calling `client.get_updates()` → parse response messages → for each message: update `context_tokens[user_id] = context_token` (FR-009), build raw_data dict with `_bot_key` injection, call pipeline `process_message()` with `WeixinAdapter` and raw_data. Include basic error handling (log and continue on message parse failure)
- [X] T018 [US2] Implement `start_weixin(bot_key: str) -> dict` and `stop_weixin(bot_key: str) -> dict` internal functions in `forward_service/routes/weixin.py`: `start_weixin` loads credentials from `chatbot.platform_config`, creates `WeixinClient`, creates `WeixinPoller`, launches `asyncio.create_task(_poll_loop)`, stores in `weixin_pollers[bot_key]`; `stop_weixin` cancels the task, calls `client.close()`, removes from `weixin_pollers`

**Checkpoint**: A logged-in WeChat bot can receive text messages, route them through the AI pipeline, and send replies. Non-text messages get friendly placeholder responses.

---

## Phase 5: User Story 3 — Bot Lifecycle Management (Priority: P2)

**Goal**: Admin can start, stop, query status, and list all WeChat bot instances via HTTP admin API.

**Independent Test**: Call start → verify bot appears as "running" in status → call stop → verify "stopped" → call list → verify correct aggregation.

**FRs covered**: FR-010, FR-018

### Implementation for User Story 3

- [X] T019 [US3] Implement `POST /admin/weixin/{bot_key}/start` endpoint in `forward_service/routes/weixin.py`: validate bot exists/is weixin/has credentials, call `start_weixin(bot_key)`, handle already-running case (idempotent: stop then restart per contract), return `{success, bot_key, status: "running", ilink_bot_id, message}` per contract
- [X] T020 [US3] Implement `POST /admin/weixin/{bot_key}/stop` endpoint in `forward_service/routes/weixin.py`: validate bot is running, call `stop_weixin(bot_key)`, return `{success, bot_key, message}` per contract, handle not-running error case
- [X] T021 [US3] Implement `GET /admin/weixin/{bot_key}/status` endpoint in `forward_service/routes/weixin.py`: look up `weixin_pollers[bot_key]`, return `{running, bot_key, status, ilink_bot_id, consecutive_failures, last_poll_at, active_users}` if running, or `{running: false, bot_key, status: "stopped"}` if not, per contract
- [X] T022 [US3] Implement `GET /admin/weixin/list` endpoint in `forward_service/routes/weixin.py`: iterate all weixin-platform chatbots from DB, cross-reference with `weixin_pollers` for runtime status, return `{bots: [...], total, running_count}` per contract

**Checkpoint**: Full admin lifecycle control is available. Bots can be started, stopped, and monitored independently via API.

---

## Phase 6: User Story 4 — Automatic Failure Recovery (Priority: P2)

**Goal**: The bot automatically retries on transient errors with exponential backoff, pauses for 1 hour on session expiry, and persists the polling cursor for restart continuity.

**Independent Test**: Simulate network failure → verify retry with backoff (1s, 2s, 4s... max 30s) → simulate errcode=-14 → verify 1-hour pause → restart service → verify polling resumes from persisted cursor.

**FRs covered**: FR-008, FR-012, FR-013

### Implementation for User Story 4

- [X] T023 [US4] Implement exponential backoff retry logic in `WeixinPoller._poll_loop()` in `forward_service/routes/weixin.py`: on transient error, increment `consecutive_failures`, compute backoff `min(2 ** consecutive_failures, 30)` seconds (per research Decision 1), `await asyncio.sleep(backoff)`, reset `consecutive_failures = 0` on successful poll
- [X] T024 [US4] Implement session expiry detection and pause in `WeixinPoller._poll_loop()` in `forward_service/routes/weixin.py`: check response `errcode == -14`, transition `status` to `PAUSED`, `await asyncio.sleep(3600)` (1 hour per research Decision 6), retry with existing credentials, if retry fails transition to `EXPIRED` status and exit loop
- [X] T025 [US4] Implement `get_updates_buf` persistence in `forward_service/routes/weixin.py`: after each successful poll cycle, update `chatbot.platform_config["get_updates_buf"]` and `last_active_at` in DB via `repository` (per research Decision 4, ~1 write per 35s per bot — negligible load)
- [X] T026 [US4] Implement `get_updates_buf` loading on poller startup in `start_weixin()` in `forward_service/routes/weixin.py`: read `chatbot.platform_config["get_updates_buf"]` from DB when creating `WeixinPoller`, default to empty string if not present (per edge case: corrupted cursor → start fresh)

**Checkpoint**: Bot is resilient to network failures and session expiry. Polling cursor survives service restarts for message continuity.

---

## Phase 7: User Story 5 — Multiple Simultaneous Accounts (Priority: P3)

**Goal**: Multiple personal WeChat bot accounts run independently, each with isolated state and message routing.

**Independent Test**: Start two WeChat bots → send message to Bot A → verify only Bot A processes it → expire Bot B's session → verify Bot A continues unaffected.

**FRs covered**: FR-011

### Implementation for User Story 5

- [X] T027 [US5] Verify and harden multi-account isolation in `forward_service/routes/weixin.py`: ensure `weixin_pollers` dict keys are `bot_key`, each `WeixinPoller` instance has independent `context_tokens` cache, `consecutive_failures` counter, and `get_updates_buf` cursor — no shared mutable state between pollers (per research Decision 3 and plan Key Design Decision 6)
- [X] T028 [US5] Ensure session expiry in one account does not affect others in `forward_service/routes/weixin.py`: verify `_poll_loop()` state transitions (RUNNING → PAUSED → EXPIRED) are scoped to the individual `WeixinPoller` instance, not the module-level dict; verify `stop_weixin()` only removes the target bot_key from `weixin_pollers`

**Checkpoint**: Multiple WeChat accounts can be logged in, started, and operated simultaneously without interference.

---

## Phase 8: User Story 6 — Typing Indicator (Priority: P3)

**Goal**: When a user sends a message, a typing indicator appears in their WeChat before the AI reply arrives.

**Independent Test**: Send a message → verify typing indicator API call fires before AI processing → verify typing cancel fires after reply is sent.

**FRs covered**: FR-014

### Implementation for User Story 6

- [X] T029 [US6] Implement `WeixinClient.get_config(self, ilink_bot_id: str) -> dict` calling `POST /ilink/bot/getconfig` (10s timeout) to obtain `typing_ticket`, and `WeixinClient.send_typing(self, ilink_bot_id: str, to_user_id: str, context_token: str, typing_ticket: str, action: str) -> dict` calling `POST /ilink/bot/sendtyping` (10s timeout) in `forward_service/clients/weixin.py`
- [X] T030 [US6] Integrate typing indicator into message flow in `handle_weixin_message()` in `forward_service/routes/weixin.py`: before calling `process_message()`, call `client.get_config()` to get `typing_ticket`, then `client.send_typing(action="start")` with the user's `context_token`; wrap in try/except — typing failure must not block message processing (per constitution P3 error isolation)
- [X] T031 [US6] Implement typing cancel after reply in `forward_service/routes/weixin.py` or `forward_service/channel/weixin.py`: after `send_outbound()` succeeds, call `client.send_typing(action="cancel")`; wrap in try/except — failure to cancel typing is non-critical

**Checkpoint**: Users see typing feedback in their WeChat client while the AI generates a response.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Quality assurance and compliance verification across all new code

- [X] T032 [P] Audit structured logging across all 3 new modules per constitution P6: verify INFO for inbound/outbound, DEBUG for ignored messages, WARNING for parse failures, ERROR with `exc_info=True` for send/network failures; verify no secrets (tokens, API keys) in log output; verify message content truncated to ≤50 chars in `forward_service/clients/weixin.py`, `forward_service/channel/weixin.py`, `forward_service/routes/weixin.py`
- [X] T033 [P] Audit type annotation completeness per constitution P2 across all 3 new modules: verify every function, method, and coroutine has explicit parameter types and return types; verify no untyped `Any` escape hatches except for raw platform payloads
- [X] T034 Verify no breaking changes per constitution P9: confirm existing routes (`/callback`, `/wecom/*`, `/admin/qqbot/*`, etc.) are unmodified; confirm existing adapters (WeComAdapter, TelegramAdapter, etc.) are not changed; run full import check to verify no import errors in existing modules
- [X] T035 End-to-end manual validation: start service, trigger QR login, scan QR, start bot, send text message, verify reply received, send image message, verify placeholder response, stop bot, verify clean shutdown — following quickstart.md scenarios if available

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Story 1 (Phase 3, P1)**: Depends on Phase 2 + T001 (WeixinClient skeleton)
- **User Story 2 (Phase 4, P1)**: Depends on Phase 2 + T007 (WeixinClient QR methods exist) — core messaging pipeline
- **User Story 3 (Phase 5, P2)**: Depends on T018 (start/stop functions from US2) — adds admin API layer
- **User Story 4 (Phase 6, P2)**: Depends on T017 (poll loop from US2) — adds resilience to the poller
- **User Story 5 (Phase 7, P3)**: Depends on T018 (start/stop) + T022 (list endpoint) — verifies multi-account isolation
- **User Story 6 (Phase 8, P3)**: Depends on T017 (poll loop) + T012 (send_message) — adds typing to message flow
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Phase 1 (Setup)
    │
    ▼
Phase 2 (Foundational)
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 3 (US1: QR Login)   Phase 4 (US2: Messaging)
    P1                         P1
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
              Phase 5      Phase 6    Phase 8
              (US3:        (US4:      (US6:
              Lifecycle)   Recovery)  Typing)
              P2           P2         P3
                    │          │
                    ▼          │
              Phase 7          │
              (US5:            │
              Multi-acct)      │
              P3               │
                    │          │
                    ▼          ▼
                Phase 9 (Polish)
```

**Key insight**: US1 (QR Login) and US2 (Messaging) can be developed in parallel after Foundational — they touch different methods in WeixinClient and different endpoints in routes. US3-US6 all depend on US2's core poller infrastructure.

### Within Each User Story

- Models/dataclasses before services/logic
- Client methods before adapter/poller methods
- Core implementation before integration (e.g., pipeline wiring)
- Story complete before moving to next priority

### Parallel Opportunities

**Phase 1**: T002 and T003 can run in parallel with T001 (different files)

**Phase 2**: T004, T005 can run in parallel (different `__init__.py` files)

**Phase 3 + Phase 4**: US1 and US2 can run in parallel after Phase 2:
- US1 works on: `WeixinClient.get_qrcode*()` + QR login routes
- US2 works on: `WeixinClient.get_updates/send_message()` + WeixinAdapter + WeixinPoller

**Phase 5 + Phase 6**: US3 and US4 can run in parallel after US2:
- US3 works on: Admin endpoint wrappers in routes/weixin.py
- US4 works on: Backoff/recovery logic in WeixinPoller._poll_loop()

**Phase 9**: T032 and T033 can run in parallel (different audit concerns)

---

## Parallel Example: US1 + US2 (Both P1, Different Files)

```bash
# Developer A: US1 (QR Login flow)
Task T007: "WeixinClient.get_qrcode() and get_qrcode_status() in clients/weixin.py"
Task T008: "POST /{bot_key}/qr-login endpoint in routes/weixin.py"
Task T009: "GET /{bot_key}/qr-status endpoint in routes/weixin.py"
Task T010: "Credential persistence on login success in routes/weixin.py"

# Developer B: US2 (Messaging flow)
Task T011: "WeixinClient.get_updates() and send_message() in clients/weixin.py"
Task T013: "WeixinAdapter should_ignore + extract_bot_key in channel/weixin.py"
Task T014: "WeixinAdapter parse_inbound in channel/weixin.py"
Task T016: "WeixinAdapter send_outbound in channel/weixin.py"
Task T017: "WeixinPoller._poll_loop() in routes/weixin.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup (create 3 file skeletons)
2. Complete Phase 2: Foundational (register in existing files)
3. Complete Phase 3: US1 — QR code login works end-to-end
4. Complete Phase 4: US2 — Text messaging works end-to-end
5. **STOP and VALIDATE**: Log in via QR → start bot → send text → receive reply
6. Deploy/demo if ready — this is the MVP

### Incremental Delivery

1. Setup + Foundational → Platform starts with Weixin adapter registered (no runtime effect)
2. Add US1 → Admin can log in WeChat bots via QR code
3. Add US2 → Full text messaging pipeline works → **Deploy (MVP!)**
4. Add US3 → Admin has full lifecycle API control → Deploy
5. Add US4 → Bot is resilient to failures and restarts → Deploy
6. Add US5 → Multiple accounts verified isolated → Deploy
7. Add US6 → Typing indicator enhances UX → Deploy
8. Polish → Logging, types, compliance audit → Final deploy

### Single Developer Strategy (Recommended)

Follow phases sequentially in priority order:
1. Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → **Validate MVP**
2. Phase 5 (US3) → Phase 6 (US4) → **Validate production readiness**
3. Phase 7 (US5) → Phase 8 (US6) → Phase 9 (Polish) → **Final validation**

---

## FR Coverage Matrix

| FR | Description | Task(s) | Story |
|---|---|---|---|
| FR-001 | QR code generation | T007, T008 | US1 |
| FR-002 | QR status polling | T007, T009 | US1 |
| FR-003 | QR auto-refresh (3x) | T009 | US1 |
| FR-004 | Session credential persistence | T010 | US1 |
| FR-005 | Long-poll message receiving | T011, T017 | US2 |
| FR-006 | Outbound text reply | T012, T016 | US2 |
| FR-007 | Non-text placeholder handling | T015 | US2 |
| FR-008 | get_updates_buf persistence | T025, T026 | US4 |
| FR-009 | context_token cache | T017 | US2 |
| FR-010 | Admin start/stop/status API | T019–T022 | US3 |
| FR-011 | Multiple simultaneous accounts | T027, T028 | US5 |
| FR-012 | Exponential backoff retry | T023 | US4 |
| FR-013 | Session expiry pause (1h) | T024 | US4 |
| FR-014 | Typing indicators | T029–T031 | US6 |
| FR-015 | Bearer token auth headers | T001 | Setup |
| FR-016 | X-WECHAT-UIN header | T001 | Setup |
| FR-017 | Private messages only | T013 | US2 |
| FR-018 | Additive platform registration | T004–T006 | Foundational |
| FR-019 | Admin QR login endpoints | T008, T009 | US1 |

---

## Notes

- [P] tasks = different files, no dependencies — safe to execute in parallel
- [Story] label maps each task to its user story for traceability
- Each user story is independently completable and testable at its checkpoint
- Constitution compliance is enforced throughout: P1 (async), P2 (types), P3 (error isolation), P4 (adapter contract), P5 (WeComAdapter structure), P6 (logging), P7 (client module), P8 (testability), P9 (additive only), P10 (non-blocking)
- All file paths are relative to the repository root (`forward_service/...`)
- Reference implementation: QQBot adapter pattern for long-poll lifecycle, WeComAdapter for adapter structure
