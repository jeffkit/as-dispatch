---

description: "Task list for 003-async-agent-call — Async Message Stream feature"
---

# Tasks: Async Agent Call via JSON-RPC Message Stream

**Input**: Design documents from `platform/as-dispatch/specs/003-async-agent-call/`  
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅  
**Branch**: `003-async-agent-call`  
**Project root**: `platform/as-dispatch/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Paths relative to `platform/as-dispatch/`

---

## Phase 1: Setup

**Purpose**: Verify environment and integration points before any code changes.

- [ ] T001 Verify active branch is `003-async-agent-call` in `platform/as-dispatch/` and SQLite DB is accessible (`alembic current`)
- [X] T002 [P] Review integration points: `forward_service/routes/callback.py` (sync handler), `forward_service/models.py` (Chatbot model), `forward_service/repository.py` (existing patterns), `forward_service/services/forwarder.py` (AgentResult shape)
- [X] T002b Verify A2A async call capability: inspect `forward_service/services/forwarder.py` and `routes/tunnel_proxy.py` to confirm whether `forward_to_agent_with_user_project()` can submit a task and return a task_id (vs. waiting for full response). If the function only supports synchronous blocking calls, document the adaptation plan (e.g., wrap in asyncio.create_task(), use SSE stream reading with asyncio.wait_for). This verification gates T013 (submit_task implementation). Write findings to `specs/003-async-agent-call/research.md` under "A2A Async Capability Verification".

---

## Phase 2: Foundation (Blocking Prerequisites)

**Purpose**: Database schema, config, and data-access layer — MUST be complete before any user story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `AsyncTaskStatus` str enum (`PENDING / PROCESSING / COMPLETED / FAILED / TIMEOUT`) to `forward_service/models.py`
- [X] T004 Add 4 async fields to `Chatbot` model in `forward_service/models.py`: `async_mode` (Boolean, default False, server_default="0"), `processing_message` (String 500, nullable), `sync_timeout_seconds` (Integer, default 30, server_default="30"), `max_task_duration_seconds` (Integer, default 1800, server_default="1800")
- [X] T005 Add `AsyncAgentTask` SQLAlchemy model to `forward_service/models.py` per data-model.md §1 — all 22 columns, 5 composite indexes, `to_dict()` method, `is_timed_out` property
- [X] T006 [P] Add 3 config fields to `ServiceConfig` in `forward_service/config.py`: `async_task_max_concurrency` (int, default 10, env `ASYNC_TASK_MAX_CONCURRENCY`), `async_task_default_timeout` (int, default 1800, env `ASYNC_TASK_DEFAULT_TIMEOUT`), `async_task_default_processing_msg` (str, default "正在为您处理，请稍候...", env `ASYNC_TASK_DEFAULT_PROCESSING_MSG`)
- [X] T007 Generate Alembic migration #1 in `alembic/versions/`: `alembic revision --autogenerate -m "add_async_fields_to_chatbots"` — review generated SQL for correct column types and `server_default` values
- [X] T008 Generate Alembic migration #2 in `alembic/versions/`: `alembic revision --autogenerate -m "create_async_agent_tasks"` — review for all indexes and composite index on `(status, created_at)`
- [ ] T009 Run `alembic upgrade head` locally against SQLite and verify schema: confirm `chatbots` has 4 new columns with correct defaults, `async_agent_tasks` table has all columns and indexes
- [X] T010 Implement `AsyncTaskRepository` class in `forward_service/repository.py` with all 8 methods from data-model.md §6: `create`, `get_by_task_id`, `get_by_status`, `get_active_by_chat`, `update_status`, `increment_retry`, `list_for_admin`, `cleanup_old_completed` — follow existing `get_db_manager().get_session()` async context manager pattern

**Checkpoint**: Foundation ready — migration applied locally, repository verified. User story implementation can now begin.

---

## Phase 3: US1 — Instant Message Acknowledgment (Priority: P1) 🎯 MVP

**Goal**: WeChat Work callback returns HTTP 200 within 3 seconds; user sees "正在为您处理..." within 5 seconds.

**Independent Test**: Send a WeChat callback POST; verify HTTP response arrives in <3s and a processing message is sent to the chat — without waiting for agent completion.

### Tests for US1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T011 [P] [US1] Unit test for `submit_task()` in `tests/test_async_task_service.py`: mock DB session, verify `AsyncAgentTask` is persisted with status=PENDING and task_id is returned without blocking

### Implementation for US1

- [X] T012 [US1] Create `forward_service/services/async_task_service.py` with `AsyncTaskService` class skeleton: `__init__` with `asyncio.Semaphore(config.async_task_max_concurrency)`, stub methods for `submit_task`, `execute_task`, `recover_pending_tasks`, `get_task_status`
- [X] T013 [US1] Implement `submit_task()` in `forward_service/services/async_task_service.py`: generate short UUID task_id, persist `AsyncAgentTask` to DB via `AsyncTaskRepository.create()`, spawn `asyncio.create_task(self.execute_task(task_id))`, return task_id immediately
- [X] T014 [US1] Implement `_handle_async_mode()` helper in `forward_service/routes/callback.py`: (1) check active PENDING/PROCESSING tasks via `repo.get_active_by_chat()` and reply with elapsed-time warning if found; (2) resolve `ForwardConfig`; (3) `send_reply()` processing message; (4) call `async_task_service.submit_task()`; (5) update `ForwardLog` with status="async_submitted"; (6) return `{"errcode": 0, "errmsg": "ok"}`
- [X] T015 [US1] Add `async_mode` routing branch in `forward_service/routes/callback.py` after existing dedup/auth/command checks: `if bot.async_mode: return await _handle_async_mode(...)`; sync path (`else`) unchanged

**Checkpoint**: US1 independently testable — callback returns <3s, processing message delivered within 5s.

---

## Phase 4: US2 — Agent Response Delivered to User (Priority: P1)

**Goal**: After agent completes (up to 30 min), full response is posted to WeChat Work conversation automatically; service restarts do not lose in-flight tasks.

**Independent Test**: Submit a simulated task; verify that `execute_task()` transitions PENDING→PROCESSING→COMPLETED and calls `send_reply()` with agent output. Restart service mid-task; verify task resumes.

### Tests for US2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [P] [US2] Unit tests for `execute_task()` state machine in `tests/test_async_task_service.py`: mock `forward_to_agent_with_user_project()` to return fast/slow/timeout/error; assert correct DB status transitions and `send_reply()` invocations
- [X] T017 [P] [US2] Unit test for retry logic in `tests/test_async_task_service.py`: mock `send_reply()` to fail 2 times then succeed; verify task ends COMPLETED with retry_count=2; mock all 3 failures; verify task ends FAILED

### Implementation for US2

- [X] T018 [US2] Implement `execute_task()` core in `forward_service/services/async_task_service.py`: acquire Semaphore, load task from DB, guard against duplicate execution (status != PENDING), update to PROCESSING, call `asyncio.wait_for(forward_to_agent_with_user_project(...), timeout=task.max_duration_seconds)`, dispatch result to `_deliver_result()` or `_handle_timeout()` on `asyncio.TimeoutError`, catch all exceptions and call `_handle_failure()`
- [X] T019 [US2] Implement `_deliver_result()` in `forward_service/services/async_task_service.py`: up to `max_retries+1` attempts with exponential backoff (2s/4s/8s); call `send_reply()`; on success update DB to COMPLETED with `completed_at`, `response_text` (truncated to 10000 chars), `new_session_id`; update UserSession via session_manager; on all retries exhausted call `_handle_failure()`
- [X] T020 [US2] Implement `_handle_timeout()` in `forward_service/services/async_task_service.py`: update DB to TIMEOUT with `completed_at` + `error_message`; `send_reply()` timeout notification ("⏱️ 任务处理超时，请稍后重试")
- [X] T021 [US2] Implement `_handle_failure()` in `forward_service/services/async_task_service.py`: update DB to FAILED with `completed_at` + `error_message`; `send_reply()` error notification ("⚠️ 处理失败，请稍后重试"); log error with exc_info
- [X] T022 [US2] Implement `recover_pending_tasks()` in `forward_service/services/async_task_service.py`: query `get_by_status(["PENDING", "PROCESSING"])`; for each task compute elapsed; if elapsed > `max_duration_seconds` call `_handle_timeout()`; else **first reset status to PENDING via `await repo.update_status(task_id, status="PENDING")`** (so `execute_task()` guard condition `status != PENDING` passes), then spawn `asyncio.create_task(self.execute_task(task_id))`; log count of recovered vs timed-out tasks. NOTE: `execute_task()` has a guard that returns early if status != PENDING — PROCESSING tasks MUST be reset to PENDING before re-spawning to avoid silent no-op recovery.
- [X] T023 [US2] Register `recover_pending_tasks()` in FastAPI lifespan in `forward_service/app.py`: call `await async_task_service.recover_pending_tasks()` during startup, after DB init

**Checkpoint**: US1 + US2 both independently functional — full async loop works, restart recovery verified.

---

## Phase 5: US3 — Task Lifecycle Visibility (Priority: P2)

**Goal**: Operators can query task status, list in-flight tasks, and see failure reasons via admin API.

**Independent Test**: Submit a long-running task; call `GET /api/admin/async-tasks?status=PROCESSING`; verify task appears with correct `bot_key`, `chat_id`, `created_at`; wait for completion; call `GET /api/admin/async-tasks/{task_id}`; verify status=COMPLETED.

### Tests for US3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T024 [P] [US3] Unit tests for admin API in `tests/test_async_tasks_api.py`: test list endpoint with status/bot_key/limit/offset filters; test detail endpoint 200 and 404 cases; verify admin key auth is enforced

### Implementation for US3

- [X] T025 [US3] Create `forward_service/routes/async_tasks_api.py` with `GET /api/admin/async-tasks` list endpoint: query params `status`, `bot_key`, `chat_id`, `limit` (max 100), `offset`; call `AsyncTaskRepository.list_for_admin()`; return list of `task.to_dict()`; require `verify_admin_key` dependency
- [X] T026 [US3] Add `GET /api/admin/async-tasks/{task_id}` detail endpoint in `forward_service/routes/async_tasks_api.py`: call `AsyncTaskRepository.get_by_task_id()`; return 404 if not found; return `task.to_dict()` with full `error_message` field for debugging
- [X] T027 [US3] Register `async_tasks_api.router` in `forward_service/app.py` with prefix `/api/admin/async-tasks`

**Checkpoint**: All 3 user stories (US1+US2+US3) independently functional — operators can observe task lifecycle.

---

## Phase 6: US4 — Backward Compatible Short-Task Handling (Priority: P3)

**Goal**: Bots with `async_mode=False` continue to work exactly as before; sync timeout auto-falls back to async.

**Independent Test**: Configure bot with `async_mode=False`; send message; verify direct reply arrives without intermediate "processing" notification; configure bot with `sync_timeout_seconds=5`; send slow-agent message; verify "processing" message sent and result delivered async.

### Tests for US4 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T028 [P] [US4] Integration test in `tests/test_async_callback.py`: test sync bot (async_mode=False) returns direct reply; test sync timeout fallback sends processing msg and submits async task; verify existing sync test cases still pass

### Implementation for US4

- [X] T029 [US4] Wrap sync agent call with `asyncio.wait_for(timeout=float(bot.sync_timeout_seconds))` in sync branch of `forward_service/routes/callback.py`; on `asyncio.TimeoutError` log fallback event, send `bot.processing_message or config.async_task_default_processing_msg`, call `async_task_service.submit_task()`, return `{"errcode": 0, "errmsg": "ok"}`
- [X] T030 [US4] Extend `BotCreateRequest` and `BotUpdateRequest` Pydantic schemas in `forward_service/routes/bots_api.py` with optional fields: `async_mode`, `processing_message`, `sync_timeout_seconds`, `max_task_duration_seconds`; add validation (sync_timeout 5–300s, max_task_duration 60–7200s)
- [X] T031 [US4] Include `async_config` nested object in Bot GET response in `forward_service/routes/bots_api.py`: `{"async_mode": bool, "processing_message": str|null, "sync_timeout_seconds": int, "max_task_duration_seconds": int}`

**Checkpoint**: All 4 user stories complete — existing bots unaffected, new async bots work end-to-end.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Message splitting, observability, migration production readiness, end-to-end validation.

- [X] T032 Integrate `message_splitter.py` in `_deliver_result()` in `forward_service/services/async_task_service.py`: split `result.reply` into chunks respecting WeChat per-message limit; call `send_reply()` sequentially for each chunk; log chunk count
- [X] T033 [P] Add structured logging throughout `forward_service/services/async_task_service.py`: every state transition logs `task_id`, `bot_key`, `chat_id`, `elapsed_ms`, new status, error (if any). Capture the WeChat callback `request_id` (or generate a correlation ID at callback entry) and thread it through to AsyncTaskService as `correlation_id` field — use `logger.info` for success, `logger.warning` for retries, `logger.error` for failures with `exc_info=True` (addresses P8 requirement for end-to-end request tracing)
- [ ] T034 Manual end-to-end validation of all Success Criteria: SC-001 (curl timing <3s), SC-003 (WeChat processing msg <5s), SC-005 (restart recovery), SC-006 (sync bot unchanged) — **跳过**：由 ArgusAI 手工/E2E 验证
- [X] T035 [P] Generate production SQL preview: `alembic upgrade head --sql > specs/003-async-agent-call/migration_003_preview.sql` — review for MySQL 8 compatibility (column types, DEFAULT encoding for Chinese text, index names)
- [X] T036 Implement graceful shutdown in `forward_service/app.py` lifespan: on shutdown, signal `async_task_service` to stop accepting new tasks, then `await asyncio.wait([t for t in active_tasks], timeout=60)` to allow in-flight tasks to complete before process exit; log number of tasks that did not complete within timeout (addresses F-006 / SC-005 second half — complements T023 startup recovery)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundation (Phase 2)**: Depends on Phase 1 — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Phase 2 completion
- **US2 (Phase 4)**: Depends on Phase 3 completion (execute_task builds on submit_task/submit flow)
- **US3 (Phase 5)**: Depends on Phase 2 completion — **can run in parallel with US2 after foundation**
- **US4 (Phase 6)**: Depends on Phase 2 completion — **can run in parallel with US2+US3 after foundation**
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### Within Each Phase

- Tests (T011, T016, T017, T024, T028) MUST be written and confirmed FAILING before implementation
- Models (T003–T005) before migrations (T007–T008)
- Repository (T010) before service (T012–T013)
- Service submit (T013) before callback branch (T014–T015)
- Service execute (T018) before deliver/timeout/failure (T019–T021)

### Parallel Opportunities

| Parallelizable Group | Tasks |
|---|---|
| Phase 2 config + models | T004, T005, T006 can run in parallel after T003 |
| Phase 2 migration + repo | T007, T008, T010 can run in parallel after T004/T005 |
| US2 tests | T016, T017 can be written simultaneously |
| US3 after foundation | Can start Phase 5 tests (T024) alongside Phase 4 implementation |
| US4 after foundation | Can start Phase 6 tests (T028) alongside Phase 4+5 implementation |
| Polish | T033, T035 can run in parallel |

---

## Implementation Strategy

### MVP First (US1 + US2 Only — Phases 1–4)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundation (schema, config, repository)
3. Complete Phase 3: US1 — instant acknowledgment
4. Complete Phase 4: US2 — result delivery + restart recovery
5. **STOP and VALIDATE**: curl timing test, WeChat end-to-end, restart recovery
6. Deploy MVP — eliminates 504 timeout errors

### Incremental Delivery

| Stage | Phases | Value Delivered |
|---|---|---|
| MVP | 1–4 | Eliminates 504 errors; async loop works |
| +Visibility | +5 | Operators can debug in-flight tasks |
| +Compat | +6 | Smooth migration path for existing bots |
| +Polish | +Final | Production hardening, message splitting |

### Parallel Team Strategy (if 2 developers)

After Phase 2 Foundation is complete:
- **Dev A**: US1 (Phase 3) → US2 (Phase 4)
- **Dev B**: US3 (Phase 5) → US4 (Phase 6) → Polish

---

## Notes

- `[P]` tasks touch different files with no shared write dependencies
- `[Story]` label enables independent story verification and delivery
- All state transitions in `async_task_service.py` MUST log `task_id` for traceability (FR per research.md §P8)
- `alembic upgrade head` MUST be verified on SQLite before any production deployment
- `async_mode` defaults to `False` — existing bots require zero configuration changes (SC-006)
- `asyncio.Semaphore(10)` is initialized at class level in `AsyncTaskService.__init__` — shared across all tasks in the process
- api_key field in `AsyncAgentTask` is snapshotted at task creation; MUST NOT be logged in full (research.md §P6)
- Commit after each phase checkpoint or logical task group; do not batch multiple phases in one commit
