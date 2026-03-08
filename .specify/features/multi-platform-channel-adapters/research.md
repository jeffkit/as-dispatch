# Research: Multi-Platform IM ChannelAdapter Unification

**Date**: 2026-03-02  
**Status**: Complete — all NEEDS CLARIFICATION items resolved

---

## Decision: Telegram Bot Key Identification

**Rationale**: Use the `X-Telegram-Bot-Api-Secret-Token` HTTP header. When registering a Telegram webhook via `setWebhook`, the operator sets `secret_token = bot_key`. Telegram then echoes this header on every inbound webhook call, uniquely identifying which bot received the message.

**Alternatives considered**:
- Embedding bot_key in the URL path (e.g., `/callback/telegram/{bot_key}`) — rejected because it breaks the single unified endpoint design required by FR-021.
- Using the Telegram `from.id` field to back-calculate the bot — rejected: `from.id` identifies the *sender*, not the receiving bot; a bot cannot inspect its own ID from the Update payload without an extra API call.

**Trade-offs**: Requires the operator to set `secret_token` to the `bot_key` value during webhook registration. This is a one-time setup step documented in `quickstart.md`.

**Implementation**: Headers are injected into `raw_data["_request_headers"]` by `unified_callback.py` before calling any adapter methods, so `TelegramAdapter.extract_bot_key()` can read `raw_data.get("_request_headers", {}).get("x-telegram-bot-api-secret-token")`.

---

## Decision: Lark Bot Key Identification

**Rationale**: Use `raw_data.get("header", {}).get("app_id")` from the Lark Events API 2.0 envelope. In the v2 schema, the outer envelope always carries `header.app_id` in cleartext, even when the `event` field is AES-encrypted. This allows the adapter to identify the app — and thus retrieve the correct `encrypt_key` from config — before attempting decryption.

**Alternatives considered**:
- Single global `encrypt_key` for all Lark bots — rejected: different Lark apps have different keys; a global key cannot support multi-bot deployments.
- Path-based routing (`/callback/lark/{app_id}`) — rejected for same reason as Telegram.

**Trade-offs**: Restricts Lark support to Events API v2.0. Lark v1 events (legacy format) lack the cleartext `header` envelope and are documented as out of scope for this release.

---

## Decision: Lark AES Decryption Flow

**Rationale**: The existing `LarkClient.decrypt_event(encrypted: str)` already implements AES-256-CBC decryption using `pycryptodome`. The adapter will:
1. Check `raw_data.get("encrypt")` to detect an encrypted payload.
2. Look up the Lark app credentials via `config.get_bot(bot_key).get_platform_config()`.
3. Instantiate a transient `LarkClient(app_id, app_secret, encrypt_key=key)` and call `decrypt_event()`.
4. Replace `raw_data` with the decrypted dict before further parsing.

**Key technical note** on `LarkClient.decrypt_event()`: The current implementation uses `key = self.encrypt_key.encode("utf-8")` directly as the AES key. Lark's official SDK derives a 32-byte key via `SHA256(encrypt_key)`. The existing client matches Lark's documented behavior only when the configured `encrypt_key` is already 32 bytes. The plan notes this as a known limitation; if decryption failures occur, the adapter should catch and log them at WARNING level (per Acceptance Scenario 4 in spec).

**Trade-offs**: Instantiating `LarkClient` per request for decryption is lightweight (no network call, pure crypto). Caching LarkClient instances per bot_key is a future optimization.

---

## Decision: Slack Bot Key Identification

**Rationale**: Use `raw_data.get("api_app_id")`. Slack includes this field in every Events API payload; it uniquely identifies the Slack app (bot) that received the event, independent of team/workspace.

**Alternatives considered**:
- `team_id` — identifies the workspace, not the app; would break multi-app deployments.
- Slack signing secret header (`X-Slack-Signature`) — can verify authenticity but doesn't identify the app in a multi-bot setup.

**Trade-offs**: `api_app_id` is absent from `url_verification` challenge payloads. For challenges, `extract_bot_key()` returns `None`; the challenge is handled before the pipeline is entered anyway (see Verification Challenge decision below).

---

## Decision: Verification Challenges (Lark & Slack) Without Modifying base.py

**Rationale**: Both Lark and Slack send platform verification challenges that must receive a specific JSON response immediately — not a generic `{"errcode": 0}`. Because `base.py` is out of scope, we cannot add an abstract or default `get_verification_response()` method to `ChannelAdapter`. Instead we use Python duck-typing in `unified_callback.py`:

```python
# Injected into unified_callback.py BEFORE should_ignore() check
get_vr = getattr(adapter, "get_verification_response", None)
if callable(get_vr):
    vr = get_vr(data)
    if vr is not None:
        return vr
```

`LarkAdapter` and `SlackAdapter` implement `get_verification_response(raw_data: dict) -> Optional[dict]` as a concrete non-abstract method. `WeComAdapter`, `TelegramAdapter`, and `DiscordAdapter` do not implement it; the `getattr` fallback returns `None` safely.

**Alternatives considered**:
- Modifying `base.py` to add the method — rejected: spec explicitly excludes base.py from changes.
- Encoding challenge in `parse_inbound()` raise — rejected: the challenge must return a 200 response with specific JSON, not a 400 error.
- Platform-specific `if platform == "lark"` check in the route — rejected: violates the platform-agnostic principle of the unified callback.

**Trade-offs**: Duck-typing reduces static type safety for this code path. Mitigated by integration tests and clear documentation.

---

## Decision: Slack Retry Header Filtering

**Rationale**: Slack sends `X-Slack-Retry-Num` on automatic retries when it does not receive a timely 200 response. Processing retries would send duplicate AI pipeline calls. Since `should_ignore()` only receives `raw_data: dict` (no HTTP headers), and `base.py` cannot be changed, the unified callback injects HTTP headers into the raw data under the reserved key `_request_headers`:

```python
data["_request_headers"] = dict(request.headers)
```

`SlackAdapter.should_ignore()` then checks:
```python
headers = raw_data.get("_request_headers", {})
return "x-slack-retry-num" in headers
```

**Alternatives considered**:
- Dedicated Slack-only check in `unified_callback.py` — rejected: platform-specific routing logic pollutes the unified handler.
- Adding `**kwargs` to `should_ignore()` signature in `base.py` — rejected: base.py is out of scope.

**Trade-offs**: `_request_headers` key (prefixed with `_`) in raw_data is a meta-field convention. All adapters must treat keys starting with `_` as injected metadata, not platform payload fields. This is documented as an adapter contract convention.

---

## Decision: Discord Architecture — WebSocket vs HTTP Webhooks

**Rationale**: Discord's standard bot integration uses a persistent WebSocket connection via the `discord.py` gateway protocol. Regular message events (DMs, channel messages) only arrive via WebSocket — Discord does not send HTTP webhooks for regular messages. The existing `routes/discord.py` route already manages this WebSocket lifecycle.

Therefore, `DiscordAdapter`:
1. Is registered in the adapter registry (supports `POST /callback/discord` for Discord Interactions such as slash commands if configured).
2. Is **also invoked from within `routes/discord.py`'s `handle_discord_message` callback** to gain unified pipeline processing.

The change to `routes/discord.py` replaces its standalone forward-to-agent logic with `process_message(adapter, inbound)` — the route path and WebSocket connection management remain unchanged. This satisfies FR-022's "operational and unchanged" requirement at the user-facing level.

**Alternatives considered**:
- Keep `routes/discord.py` unchanged and only register the adapter for HTTP interactions — rejected: would leave Discord messages off the unified pipeline, the core goal of this feature.
- Migrate Discord to pure HTTP interactions endpoint — rejected: requires Discord slash command registration, fundamentally changes the bot UX, and is out of scope.

**Trade-offs**: `DiscordAdapter.send_outbound()` requires access to a running `DiscordBotClient` instance. The adapter retrieves it from `routes.discord.discord_bots[bot_key]` at send time. This couples the adapter to the discord route module, but is the only way to send messages without duplicating the WebSocket connection management. The coupling is documented in the module docstring.

---

## Decision: Image URL Handling per Platform

| Platform | Image Source | URL Availability | Adapter Behavior |
|----------|-------------|-----------------|-----------------|
| **Telegram** | `message.photo[]` — last (largest) item | `file_id` only; actual URL requires `getFile` API call | `parse_inbound()` calls `TelegramClient.get_file_url(file_id)` to resolve to `https://api.telegram.org/file/bot{token}/{file_path}`. Note: `TelegramClient` does not currently have `get_file_url()` — this method must be added to the client before the adapter task is implemented (tracked as a client gap). |
| **Lark** | `message.content.image_key` | Requires `LarkClient.get_image_url(image_key)` API call | `parse_inbound()` stores the image_key as-is in `images[]`. A future enhancement can resolve keys to URLs via the Lark API. Initial implementation passes image_key as a reference; the pipeline must handle it. |
| **Discord** | `message.attachments[].url` | Direct CDN URL, no auth required | Include all attachment URLs where `content_type.startswith("image/")` |
| **Slack** | `event.files[].url_private_download` | Requires `Authorization: Bearer {token}` header | Store URL directly in `images[]`. The pipeline passes the URL to the AI backend, which must supply the Slack token if downloading. |

**Key gap**: `TelegramClient` lacks a `get_file_url()` method. This must be added to `forward_service/clients/telegram.py` before the `TelegramAdapter` can resolve photo URLs. This is a client-layer responsibility (Principle 7), not the adapter's.

---

## Decision: unified_callback.py — Complete Fix Specification

The current file has two issues to fix:

**Issue 1** (FR-021): Hardcoded `if platform == "wecom"` fallback  
**Fix**: Remove `_default_wecom_adapter`, remove the WeComAdapter import, replace with pure registry lookup. Error response should include the list of registered platforms dynamically.

**Issue 2**: No mechanism for platform-specific verification challenge responses  
**Fix**: Add duck-typed `get_verification_response` check before `should_ignore()`.

**Issue 3**: Adapters cannot access HTTP headers from `should_ignore()` or `extract_bot_key()`  
**Fix**: Inject headers into `raw_data["_request_headers"]` before any adapter calls.

The complete fixed flow in `unified_callback.py`:

```python
data = await request.json()

# Inject HTTP context for adapters that need header-based detection
data["_request_headers"] = dict(request.headers)

# Handle verification challenges (Lark url_verification, Slack url_verification)
get_vr = getattr(adapter, "get_verification_response", None)
if callable(get_vr):
    vr = get_vr(data)
    if vr is not None:
        return vr

# Check should_ignore (bot messages, heartbeats, retries)
if adapter.should_ignore(data):
    logger.debug(f"[{platform}] 忽略消息")
    return {"errcode": 0, "errmsg": "ok"}

# Parse inbound (pass headers as kwargs for adapters that need them)
try:
    inbound = await adapter.parse_inbound(data, headers=dict(request.headers))
except ValueError as e:
    logger.error(f"[{platform}] 消息解析失败: {e}")
    return {"errcode": 400, "errmsg": f"Invalid message format: {e}"}

return await process_message(adapter, inbound)
```

---

## Decision: app.py Registration Order and Discord Task Integration

**Adapter registration** (after existing `register_adapter(WeComAdapter())`):
```python
from .channel.telegram import TelegramAdapter
from .channel.lark import LarkAdapter
from .channel.discord import DiscordAdapter
from .channel.slack import SlackAdapter

register_adapter(TelegramAdapter())
register_adapter(LarkAdapter())
register_adapter(DiscordAdapter())
register_adapter(SlackAdapter())
```

The `DiscordAdapter` registration is additive — the Discord WebSocket bot lifecycle (start/stop) remains in the existing lifespan code unchanged.

---

## Client Gap: TelegramClient.get_file_url()

**Gap**: `TelegramClient` does not implement `get_file_url(bot_token, file_id) -> str`. This method must be added before the Telegram adapter can resolve photo URLs.

**Required implementation**:
```python
async def get_file_url(self, file_id: str) -> Optional[str]:
    """
    Resolve a file_id to a download URL via getFile API.
    Returns: https://api.telegram.org/file/bot{token}/{file_path}
    """
    url = f"{self.base_url}/getFile"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"file_id": file_id})
        data = response.json()
        if data.get("ok") and data.get("result", {}).get("file_path"):
            return f"https://api.telegram.org/file/bot{self.bot_token}/{data['result']['file_path']}"
    return None
```

This is a pre-requisite for the TelegramAdapter task and must be implemented first.
