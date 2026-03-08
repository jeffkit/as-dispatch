# Tasks: Multi-Platform IM ChannelAdapter Unification

**Input**: `.specify/features/multi-platform-channel-adapters/`  
**Branch**: `feature/im-integration`  
**Generated**: 2026-03-02  
**Total Tasks**: 22 | **Phases**: 6

---

## Format: `- [ ] [ID] [P?] [Story?] Description — file path`

- **[P]**: Parallelizable (different files, no shared mutable dependencies)
- **[Story]**: Maps to user story from spec.md (US1–US5)
- **No story label**: Setup / foundational / cross-cutting task

---

## Phase 1: Foundation Fix — Unified Callback (US5, P1) 🎯 Required First

**Goal**: Replace the hardcoded `"wecom"` fallback in `unified_callback.py` with pure registry
lookup, inject HTTP request headers for adapter-level filtering (Slack retry, Telegram bot-key),
and add duck-typed verification-challenge support (Lark/Slack URL challenges).

**Spec**: User Story 5 — Unified Callback Entry Routes to Any Registered Platform (P1)

**Independent Test**: Register WeComAdapter only, POST to `/callback/wecom` with a valid
WeCom payload → verify the response is identical to today. Then POST to `/callback/unknown` →
verify a 400 with `"Unsupported platform"` and a list of registered adapters in the error body.

**⚠️ CRITICAL**: Phases 2–5 each include an `app.py` registration step. The foundation fix
in Phase 1 must be committed first so the registry-based routing is live before the new
adapters are exercised end-to-end.

### Implementation

- [X] T001 [US5] Remove hardcoded `WeComAdapter` fallback and replace with registry lookup + `list_adapters()` error message — `forward_service/routes/unified_callback.py` (Change A from plan.md §2)
- [X] T002 [US5] Inject HTTP request headers as `_request_headers` into `raw_data` dict immediately after `await request.json()` — `forward_service/routes/unified_callback.py` (Change B from plan.md §2)
- [X] T003 [US5] Add duck-typed `get_verification_response()` call before `should_ignore()` in the unified callback handler — `forward_service/routes/unified_callback.py` (Change C from plan.md §2)

**Checkpoint**: `POST /callback/wecom` still works. `POST /callback/unknown` returns a
structured 400. No other platform code exists yet — this is a pure routing fix.

---

## Phase 2: Telegram Adapter (US1, P1) 🎯 MVP

**Goal**: A Telegram user sends a text or image message to the bot; the bot parses it via the
unified adapter, runs the AI pipeline, and replies in the same chat.

**Spec**: User Story 1 — Telegram Bot Receives and Replies to Messages (P1)

**Independent Test**: Deploy with TelegramAdapter registered, send `"hello"` to the bot on
Telegram, and verify an AI-generated reply arrives in the same chat within 30 seconds.

**Acceptance coverage**:
- Plain text → AI reply (Scenario 1)
- Image message → `images` list populated, AI reply acknowledges image (Scenario 2)
- Bot-originated message → silently ignored, no reply sent (Scenario 3)
- Unprocessable update (sticker-only) → logged, no exception propagated (Scenario 4)

### Implementation

- [X] T004 [US1] Add `async def get_file_url(self, file_id: str) -> Optional[str]` method using Telegram `getFile` API — `forward_service/clients/telegram.py`
- [X] T005 [US1] Create `TelegramAdapter` subclass with all 5 `ChannelAdapter` members; `extract_bot_key` reads `X-Telegram-Bot-Api-Secret-Token` from `_request_headers`; `_extract_images` resolves `file_id` via `get_file_url()` — `forward_service/channel/telegram.py` (NEW)
- [X] T006 [US1] Import and register `TelegramAdapter` at service startup — `forward_service/app.py`
- [X] T007 [P] [US1] Write unit tests: `parse_inbound` happy path + `ValueError` on missing message key; `send_outbound` success + failure with mocked `TelegramClient`; `should_ignore` for bot author; `extract_bot_key` from headers — `tests/unit/test_channel_telegram.py` (NEW)

**Checkpoint**: User Story 1 fully functional and independently testable. WeChat regression
check: `POST /callback/wecom` continues to return 200.

---

## Phase 3: Lark Adapter (US2, P2)

**Goal**: A Lark group member sends a text or image message; the bot decrypts the event
(if encrypted), parses it, and replies via `LarkClient`.

**Spec**: User Story 2 — Lark (飞书) Bot Receives and Replies to Messages (P2)

**Independent Test**: Configure `LarkAdapter` with a test Lark app, send a message in a test
group, verify an AI reply appears in the group.

**Acceptance coverage**:
- Text message → decrypt → AI reply in group (Scenario 1)
- URL verification challenge → immediate `{"challenge": "..."}` response, no pipeline call (Scenario 2)
- Image message → `images` field populated with `image_key` (Scenario 3)
- Wrong AES key → `WARNING` log, safe HTTP error (not a 500) (Scenario 4)

### Implementation

- [X] T008 [US2] Create `LarkAdapter` subclass: `get_verification_response()` (duck-typed), `_decrypt_if_needed()` calling `LarkClient.decrypt_event()`, `parse_inbound` with `p2.im.message.receive_v1` event schema, `send_outbound` via `LarkClient.send_text()` — `forward_service/channel/lark.py` (NEW)
- [X] T009 [US2] Import and register `LarkAdapter` at service startup — `forward_service/app.py`
- [X] T010 [P] [US2] Write unit tests: `parse_inbound` happy path + decryption failure; `send_outbound` success + failure with mocked `LarkClient`; `get_verification_response` with `url_verification` payload; `should_ignore` for `sender_type == "bot"` — `tests/unit/test_channel_lark.py` (NEW)

**Checkpoint**: User Stories 1 and 2 both pass their independent tests. No regressions.

---

## Phase 4: Discord Adapter (US3, P3)

**Goal**: A Discord user sends a message in a channel where the bot is present; the bot
processes it via the unified pipeline and replies via `DiscordBotClient.send_dm()`.

**Spec**: User Story 3 — Discord Bot Receives and Replies to Messages (P3)

**Independent Test**: Set up a Discord bot in a test server, send a message, confirm the bot
posts an AI reply in the same channel.

**Acceptance coverage**:
- Text message → AI reply in channel (Scenario 1)
- Image attachment → URLs in `images` field (Scenario 2)
- Bot self-message → silently ignored (Scenario 3)

> **Architecture note** (from plan.md §7): Discord uses the WebSocket gateway (discord.py),
> not HTTP webhooks. The unified callback endpoint cannot receive Discord messages directly.
> The only integration point is `routes/discord.py::handle_discord_message`. Updating that
> function to delegate to the unified pipeline is the Discord-equivalent of routing through
> `POST /callback/{platform}`. This is the documented deviation (Complexity Tracking, plan.md).

### Implementation

- [X] T011 [US3] Create `DiscordAdapter` subclass: `extract_bot_key` from `kwargs["bot_key"]`; `parse_inbound` serializes a `discord.Message`-shaped dict into `InboundMessage`; `send_outbound` with chunked message support (2 000-char limit); `_get_bot_client` imports `discord_bots` from `routes.discord` — `forward_service/channel/discord.py` (NEW)
- [X] T012 [US3] Rewrite `handle_discord_message` to serialize `discord.Message` to a plain dict, call `adapter.parse_inbound(raw, bot_key=client.bot_key)`, then `await process_message(adapter, inbound)` — `forward_service/routes/discord.py` (existing function body only; route path and WebSocket lifecycle unchanged)
- [X] T013 [US3] Import and register `DiscordAdapter` at service startup — `forward_service/app.py`
- [X] T014 [P] [US3] Write unit tests: `parse_inbound` happy path + image attachments; `send_outbound` success + chunked output + failure with mocked `DiscordBotClient`; `should_ignore` for bot author; `extract_bot_key` from kwargs — `tests/unit/test_channel_discord.py` (NEW)

**Checkpoint**: User Stories 1, 2, and 3 all pass their independent tests. No regressions.

---

## Phase 5: Slack Adapter (US4, P4)

**Goal**: A Slack user sends a message in a channel where the bot is installed; the bot
responds using Slack's message API, with URL challenge and retry-detection support.

**Spec**: User Story 4 — Slack Bot Receives and Replies to Messages (P4)

**Independent Test**: Install the Slack bot in a test workspace channel, send a message,
and confirm the bot replies in thread or channel.

**Acceptance coverage**:
- Text message → AI reply (Scenario 1)
- `url_verification` challenge → immediate `{"challenge": "..."}` response (Scenario 2)
- `X-Slack-Retry-Num` header present → return 200 immediately, no pipeline call (Scenario 3)
- Bot message (`bot_id` or `subtype == "bot_message"`) → silently ignored (Scenario 4)
- Image file attachment → `url_private_download` URLs in `images` field (Scenario 5)

### Implementation

- [X] T015 [US4] Create `SlackAdapter` subclass: `get_verification_response()` (duck-typed); `should_ignore` checks `_request_headers["x-slack-retry-num"]` then bot flags; `extract_bot_key` from `api_app_id`; `_extract_images` from `event.files[]`; `send_outbound` via `SlackClient.post_message()` — `forward_service/channel/slack.py` (NEW)
- [X] T016 [US4] Import and register `SlackAdapter` at service startup — `forward_service/app.py`
- [X] T017 [P] [US4] Write unit tests: `parse_inbound` happy path + image files; `send_outbound` success + failure with mocked `SlackClient`; `should_ignore` for retry header and bot message; `get_verification_response` with `url_verification` payload — `tests/unit/test_channel_slack.py` (NEW)

**Checkpoint**: All four new platform adapters pass their independent tests. No regressions.

---

## Phase 6: Integration & Verification (US5)

**Goal**: Confirm all five adapters are wired into the unified pipeline end-to-end, the
`__init__.py` exports are clean, and the MULTI_PLATFORM_ROADMAP.md reflects completion.

**Spec**: User Story 5 — Unified Callback Entry Routes to Any Registered Platform (P1) — final
acceptance items (SC-001 through SC-008).

### Implementation

- [X] T018 [US5] Add named exports for `TelegramAdapter`, `LarkAdapter`, `DiscordAdapter`, `SlackAdapter` to the channel package — `forward_service/channel/__init__.py`
- [X] T019 [P] [US5] End-to-end smoke verification: POST crafted payloads for all 4 new platforms to `POST /callback/{platform}` (or the Discord WebSocket path) with mocked AI backend; confirm `process_message` is called for each and that a WeChat payload on the same endpoint still succeeds — manual or scripted using `quickstart.md` curl examples
- [X] T020 [P] [US5] Update `docs/MULTI_PLATFORM_ROADMAP.md`: mark Phase 1 (Telegram, Lark, Discord, Slack adapter unification) as ✅ complete with date 2026-03-02

**Checkpoint**: SC-001 (all 5 platforms end-to-end), SC-003 (WeChat zero regression),
SC-004 (error isolation), SC-007 (URL challenges under 3 s), SC-008 (bot-message filtering)
all verifiable.

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Foundation Fix)     — no dependencies; start immediately
Phase 2 (Telegram)           — depends on Phase 1 complete
Phase 3 (Lark)               — depends on Phase 1 complete; independent of Phase 2
Phase 4 (Discord)            — depends on Phase 1 complete; independent of Phases 2–3
Phase 5 (Slack)              — depends on Phase 1 complete; independent of Phases 2–4
Phase 6 (Integration)        — depends on Phases 2–5 all complete
```

### Per-Phase Task Dependencies

| Task | Depends on |
|------|-----------|
| T001 | — (start of Phase 1) |
| T002 | T001 |
| T003 | T002 |
| T004 | T003 (Phase 1 complete) |
| T005 | T004 (`get_file_url` must exist) |
| T006 | T005 |
| T007 | T005 (can run parallel with T006) |
| T008 | T003 (Phase 1 complete) |
| T009 | T008 |
| T010 | T008 (can run parallel with T009) |
| T011 | T003 (Phase 1 complete) |
| T012 | T011 (`DiscordAdapter` must exist) |
| T013 | T011 |
| T014 | T011 (can run parallel with T012, T013) |
| T015 | T003 (Phase 1 complete) |
| T016 | T015 |
| T017 | T015 (can run parallel with T016) |
| T018 | T006, T009, T013, T016 (all adapters registered) |
| T019 | T018 |
| T020 | T019 |

### Files Modified / Created per Task

| Task | File | Action |
|------|------|--------|
| T001–T003 | `forward_service/routes/unified_callback.py` | MODIFY (3 targeted changes) |
| T004 | `forward_service/clients/telegram.py` | MODIFY (add `get_file_url`) |
| T005 | `forward_service/channel/telegram.py` | NEW |
| T006 | `forward_service/app.py` | MODIFY (add Telegram registration) |
| T007 | `tests/unit/test_channel_telegram.py` | NEW |
| T008 | `forward_service/channel/lark.py` | NEW |
| T009 | `forward_service/app.py` | MODIFY (add Lark registration) |
| T010 | `tests/unit/test_channel_lark.py` | NEW |
| T011 | `forward_service/channel/discord.py` | NEW |
| T012 | `forward_service/routes/discord.py` | MODIFY (`handle_discord_message` body only) |
| T013 | `forward_service/app.py` | MODIFY (add Discord registration) |
| T014 | `tests/unit/test_channel_discord.py` | NEW |
| T015 | `forward_service/channel/slack.py` | NEW |
| T016 | `forward_service/app.py` | MODIFY (add Slack registration) |
| T017 | `tests/unit/test_channel_slack.py` | NEW |
| T018 | `forward_service/channel/__init__.py` | MODIFY (add exports) |
| T019 | — (manual/scripted verification) | VERIFY |
| T020 | `docs/MULTI_PLATFORM_ROADMAP.md` | MODIFY |

> **Note on `app.py`**: Tasks T006, T009, T013, T016 all touch `forward_service/app.py`.
> They can be batched into a single commit after all four adapters exist (Phase 6 entry),
> or applied incrementally one at a time as each adapter phase completes — both are safe
> because each change is an additive `register_adapter(...)` call.

---

## Parallel Execution Examples

### Phases 2–5 in Parallel (if 4 developers available)

Once Phase 1 is merged:

```
Developer A → Phase 2 (Telegram): T004 → T005 → T006 + T007 in parallel
Developer B → Phase 3 (Lark):     T008 → T009 + T010 in parallel
Developer C → Phase 4 (Discord):  T011 → T012 + T013 + T014 in parallel
Developer D → Phase 5 (Slack):    T015 → T016 + T017 in parallel
```

All four developers merge back before Phase 6 begins.

### Within Phase 4 (Discord) — 3-way parallel after T011

```
T012 (routes/discord.py)    ─┐
T013 (app.py registration)  ─┼─ all start as soon as T011 is done
T014 (unit tests)           ─┘
```

---

## Implementation Strategy

### MVP First (Phases 1 + 2 Only — Telegram)

1. Complete Phase 1: Foundation Fix (T001–T003)
2. Complete Phase 2: Telegram Adapter (T004–T007)
3. **VALIDATE**: Send `"hello"` to Telegram bot → AI reply received
4. **VALIDATE**: WeChat messages continue to work (SC-003)
5. Demo / early deployment if stakeholder approval needed

### Incremental Delivery

```
Phase 1 → Routing foundation (enables all platforms)
Phase 2 → Telegram live (P1, highest-visibility value)
Phase 3 → Lark live (P2, Chinese enterprise teams)
Phase 4 → Discord live (P3, third adapter pattern validated)
Phase 5 → Slack live (P4, fourth adapter, full coverage)
Phase 6 → Integration confirmed, roadmap updated
```

Each phase independently deployable. Operator can enable platforms by
bot configuration without code changes.

---

## Success Criteria Traceability

| SC | Description | Verified by |
|----|-------------|-------------|
| SC-001 | All 5 platforms end-to-end | T019 (smoke verification) |
| SC-002 | AI reply ≤ 30 s | T019 (timed curl / manual) |
| SC-003 | Zero WeChat regression | Checkpoints after T006, T009, T013, T016 |
| SC-004 | Error isolation across adapters | T019 + unit tests (T007, T010, T014, T017) |
| SC-005 | Unit test coverage per adapter | T007, T010, T014, T017 |
| SC-006 | Image forwarding all platforms | T007 (Telegram), T010 (Lark), T014 (Discord), T017 (Slack) |
| SC-007 | URL challenges < 3 s (Lark, Slack) | T003 + T010 + T017 |
| SC-008 | Bot-message filtering | T007 (Telegram), T013/T014 (Discord), T017 (Slack) |

---

## Notes

- Tasks T001–T003 MUST be committed before any adapter is registered; the routing fix is
  the prerequisite that makes the registry-only lookup safe.
- `app.py` receives 4 separate `register_adapter()` additions (T006, T009, T013, T016).
  These can be squashed into one commit at the end of Phase 5 or applied incrementally.
- `routes/discord.py` (T012) touches only `handle_discord_message`; the WebSocket bot
  lifecycle (`on_ready`, `start_discord_bot`, `discord_bots` dict) is **not changed**.
- `base.py`, `pipeline.py`, `registry.py`, and `WeComAdapter` are **not modified** in any task.
- Lark image support in MVP stores `image_key` as-is in `images[]`; full download URL
  resolution is deferred to Phase 2 of the roadmap (noted in research.md).
