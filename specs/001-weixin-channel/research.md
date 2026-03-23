# Research: 个人微信通道接入 (Weixin Channel)

**Date**: 2026-03-22
**Plan**: `specs/001-weixin-channel/plan.md`

---

## Decision 1: Long-Polling Architecture (WeixinPoller)

**Decision**: Use a per-bot `asyncio.Task` running an infinite long-poll loop, identical to the QQBot Gateway pattern.

**Rationale**: The iLinkAI protocol uses HTTP long-polling (POST `/ilink/bot/getupdates`) with a 35-second server-side timeout. This is functionally equivalent to QQBot's WebSocket Gateway in terms of lifecycle management — both are persistent background connections that must be started, stopped, and reconnected. The QQBot pattern (background `asyncio.Task` + module-level client dict + admin start/stop endpoints) is proven in production and fully compatible with the as-dispatch lifespan model.

**Alternatives considered**:
1. **Periodic timer (asyncio.create_task with sleep interval)**: Rejected — introduces unnecessary latency between polls. Long-poll is already a blocking-until-data pattern; a timer would add artificial delay.
2. **WebSocket wrapper**: Rejected — the iLinkAI protocol does not offer WebSocket; HTTP long-poll is the only option.
3. **Dedicated worker process**: Rejected — over-engineering for the expected scale (≤10 accounts). The asyncio event loop can handle 10 concurrent long-poll tasks easily.

**Trade-offs**:
- (+) Proven pattern, minimal new code, consistent with QQBot
- (+) Each poller is independently cancellable
- (-) Long-poll requests hold an HTTP connection for up to 35s each — at 10 accounts, that's 10 persistent connections. This is well within httpx.AsyncClient's connection pool limits.

---

## Decision 2: httpx.AsyncClient Lifecycle

**Decision**: Use a single shared `httpx.AsyncClient` instance per `WeixinClient`, created in `__init__` and closed in `close()`.

**Rationale**: The iLinkAI protocol requires long-lived HTTP connections (35s long-poll). Creating a new client per request would waste connection setup time and miss HTTP/2 multiplexing benefits. A shared client with a connection pool (httpx default: 100 connections) efficiently handles both long-poll and send/typing requests concurrently.

**Alternatives considered**:
1. **New httpx.AsyncClient per request**: Rejected — connection setup overhead defeats the purpose of long-poll.
2. **Module-level global client**: Rejected — per constitution P7, each platform's HTTP logic lives in its own client class. A global client would couple lifecycles across bots.

**Trade-offs**:
- (+) Connection reuse, efficient pooling
- (+) Clean lifecycle (create on start, close on stop)
- (-) Must ensure `close()` is called on shutdown to avoid resource leaks

---

## Decision 3: context_token Cache Strategy

**Decision**: In-memory `dict[tuple[str, str], str]` mapping `(bot_account_id, user_id) → context_token`, stored on the `WeixinPoller` instance.

**Rationale**: The `context_token` is per-message and must be echoed in replies. It changes with each inbound message from a user, so only the most recent token is needed. An in-memory cache is sufficient because:
1. The token is transient — it's repopulated on the next inbound message.
2. Losing it on restart only means one reply might lack conversation context linkage (graceful degradation per spec edge case).
3. Database persistence would add unnecessary write overhead for every inbound message.

**Alternatives considered**:
1. **Database persistence**: Rejected — write amplification for a transient, non-critical value.
2. **Redis/external cache**: Rejected — not available in as-dispatch's deployment model; adds operational complexity.
3. **LRU cache with TTL**: Considered but deferred — simple dict is sufficient for ≤10 accounts × ~100 active users. Can add LRU later if memory becomes a concern.

**Trade-offs**:
- (+) Zero latency, zero I/O overhead
- (+) Automatically scoped to poller lifecycle
- (-) Lost on restart (acceptable per spec)
- (-) Unbounded growth in theory (mitigated by expected scale)

---

## Decision 4: get_updates_buf Persistence

**Decision**: Store `get_updates_buf` in the bot's `platform_config` JSON field in the existing SQLAlchemy database, updated after each successful poll cycle.

**Rationale**: The `get_updates_buf` is an opaque cursor that must survive service restarts to maintain message continuity (FR-008). The bot's `platform_config` JSON column already stores credentials (`bot_token`, `ilink_bot_id`); adding the cursor here avoids schema changes. The QQBot adapter uses a similar pattern for storing `session_id` and `last_seq` in memory (though QQBot doesn't persist these — WeChat's fragile sessions make persistence more important).

**Alternatives considered**:
1. **Separate database column**: Rejected — requires schema migration for a single field.
2. **File-based persistence**: Rejected — not compatible with containerized deployments; DB is the canonical persistence layer.
3. **In-memory only (like QQBot)**: Rejected — QQBot can resume via WebSocket `RESUME` opcode. WeChat long-poll has no such mechanism; losing the cursor means missing messages.

**Trade-offs**:
- (+) Survives restarts
- (+) No schema changes
- (+) Leverages existing DB infrastructure
- (-) One DB write per poll cycle (~every 35s per bot) — negligible load

---

## Decision 5: QR Login Flow Design

**Decision**: Expose two admin API endpoints: `POST /{bot_key}/qr-login` (trigger QR generation) and `GET /{bot_key}/qr-status` (poll QR status). Auto-refresh QR up to 3 times on expiry.

**Rationale**: The iLinkAI QR login is a multi-step process:
1. `GET /ilink/bot/get_bot_qrcode?bot_type=3` → returns QR code identifier + image URL
2. Admin scans QR with phone
3. `GET /ilink/bot/get_qrcode_status?qrcode=xxx` → returns status (wait/scaned/confirmed/expired)
4. On `confirmed`, extract bot_token + ilink_bot_id from response

The two-endpoint design (trigger + poll) matches the iLinkAI protocol's async nature and is consistent with QQBot's start/stop/status pattern. Auto-refresh on expiry (up to 3 times) fulfills FR-003 without requiring admin re-trigger.

**Alternatives considered**:
1. **WebSocket-based real-time status**: Rejected — adds complexity; HTTP polling is sufficient for a human-speed interaction.
2. **Single blocking endpoint**: Rejected — QR scan can take minutes; a blocking HTTP request would timeout.
3. **Background auto-login**: Rejected — requires admin's physical phone interaction; can't be fully automated.

**Trade-offs**:
- (+) Simple, stateless API
- (+) Admin can use any HTTP client (curl, browser, admin UI)
- (-) Requires admin to poll status endpoint

---

## Decision 6: Session Expiry Recovery Strategy

**Decision**: On `errcode=-14`, pause the poller for 1 hour via `asyncio.sleep(3600)`, then retry with existing credentials. If retry fails, transition to `expired` status.

**Rationale**: Per the SDK analysis, `errcode=-14` indicates session expiry. The 1-hour pause is the recommended recovery interval (from the SDK behavior). After the pause, attempting reconnection with existing credentials may succeed if the session was only temporarily invalidated. If it fails, the bot needs manual QR re-login.

**Alternatives considered**:
1. **Immediate re-login**: Rejected — could trigger rate limiting or account restrictions.
2. **No automatic retry**: Rejected — violates FR-013 and User Story 4.
3. **Configurable pause duration**: Deferred — 1 hour is the standard from SDK analysis. Can parameterize later.

**Trade-offs**:
- (+) Follows SDK-recommended behavior
- (+) Automatic recovery without admin intervention
- (-) 1-hour downtime during pause (acceptable for session expiry)

---

## Decision 7: Typing Indicator Implementation

**Decision**: Send typing indicator via `POST /ilink/bot/sendtyping` with a `typing_ticket` obtained from `POST /ilink/bot/getconfig`. Typing is sent once before processing begins; no continuous typing updates.

**Rationale**: The iLinkAI typing API requires a `typing_ticket` from the config endpoint, then a `sendtyping` call with that ticket plus the `context_token`. This is a two-step process. Sending a single typing indicator before the AI processes the message provides sufficient UX feedback without adding complexity of continuous typing updates.

**Alternatives considered**:
1. **Continuous typing (periodic re-send)**: Deferred — adds timer complexity. Single indicator is sufficient for MVP (P3 feature).
2. **Skip typing entirely**: Rejected — typing is a specific user story (US-6) and the API supports it.

**Trade-offs**:
- (+) Simple implementation
- (+) Better UX than no indicator
- (-) Typing may "expire" if AI takes very long — acceptable for MVP

---

## Decision 8: Non-Text Message Handling

**Decision**: Detect message type from `item_list[].type` field (TEXT=1, IMAGE=2, VOICE=3, FILE=4, VIDEO=5). For non-text types, return a localized placeholder message and do not process further.

**Rationale**: FR-007 requires graceful handling of non-text messages without crashing. The spec explicitly marks media processing as out of scope for MVP. Returning a friendly placeholder (e.g., `[收到了图片，暂不支持显示]`) acknowledges the user's message while being transparent about the limitation.

**Placeholder messages**:
- IMAGE (2): `[收到了图片，暂不支持处理图片消息]`
- VOICE (3): `[收到了语音，暂不支持处理语音消息]`
- FILE (4): `[收到了文件，暂不支持处理文件消息]`
- VIDEO (5): `[收到了视频，暂不支持处理视频消息]`

**Trade-offs**:
- (+) Graceful degradation
- (+) Clear user feedback
- (-) No actual media processing (explicitly out of scope)

---

## Decision 9: Message Format Mapping (iLinkAI → InboundMessage)

**Decision**: Map iLinkAI `WeixinMessage` to `InboundMessage` as follows:

| iLinkAI Field | InboundMessage Field | Notes |
|---|---|---|
| (derived from account) | `platform` | Always `"weixin"` |
| (bot_key from poller) | `bot_key` | Injected via kwargs |
| `from_user_name` / `from_user_id` | `user_id`, `user_name` | Sender identifiers |
| `""` | `user_alias` | Not available in iLinkAI; empty string (per P4) |
| `"direct:{user_id}"` | `chat_id` | Synthetic chat_id for direct messages |
| `"direct"` | `chat_type` | Always direct (no group chat support) |
| `item_list[type=1].content` | `text` | First text item's content |
| `[]` | `images` | Empty for MVP (no image processing) |
| `"text"` / `"image"` / etc. | `msg_type` | Derived from item_list types |
| `context_token` | `raw_data["context_token"]` | Preserved in raw_data for reply routing |
| (auto-generated) | `message_id` | Derived from content hash or timestamp (iLinkAI doesn't provide a message ID) |

**Rationale**: Follows the same mapping pattern as QQBotAdapter. The synthetic `chat_id` format `"direct:{user_id}"` matches QQBot's `"c2c:{openid}"` pattern, enabling the pipeline's session management to work correctly.
