# Implementation Plan: Multi-Platform IM ChannelAdapter Unification

**Branch**: `feature/im-integration` | **Date**: 2026-03-02 | **Spec**: `spec.md`  
**Input**: `.specify/features/multi-platform-channel-adapters/spec.md`

---

## Summary

Connect Telegram, Lark (飞书), Discord, and Slack to the same unified adapter architecture and 10-step processing pipeline already used by WeCom (企业微信). Four new `ChannelAdapter` subclasses are added — one per platform — following the `WeComAdapter` structural reference exactly. The unified callback route (`unified_callback.py`) receives a localized fix to replace the hardcoded `"wecom"` platform fallback with pure registry lookup, plus two additions: duck-typed verification-challenge support and HTTP-header injection for adapters that need header-based filtering (Slack retries, Telegram bot-key identification). All four new adapters register at service startup in `app.py`. Discord requires the WebSocket message handler in `routes/discord.py` to call `process_message()` instead of its own standalone logic — the route path and WebSocket lifecycle management remain unchanged. Existing routes, WeComAdapter, pipeline.py, and base.py are untouched.

---

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: FastAPI (existing), discord.py (existing), httpx (existing), pycryptodome (existing, for Lark AES decryption)  
**Storage**: No new tables; existing SQLite/MySQL database is sufficient  
**Testing**: pytest — `tests/unit/test_channel_<platform>.py` per Principle 8  
**Target Platform**: Linux server (uvicorn/asyncio)  
**Project Type**: Single (extension to existing `forward_service`)  
**Performance Goals**: ≤ 30 seconds end-to-end AI reply for all platforms (existing pipeline SLA per SC-002)  
**Constraints**:  
- `base.py`, `pipeline.py`, `WeComAdapter` — **no modifications** (spec Out of Scope)  
- Existing API routes (paths) — **remain operational** (FR-022)  
- All adapter methods must be `async`/`await` (Principle 10)  
- No direct HTTP sessions in adapters; delegate to existing clients (Principle 7)  

**Scale/Scope**: 5 platforms × N configured bots; low message concurrency per bot

---

## Constitution Check

*Source: `.specify/memory/constitution.md` v1.0.0*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| P1 | Python 3.11+, FastAPI, async handlers only | ✅ | All four adapters use `async def parse_inbound` and `async def send_outbound`. The `unified_callback.py` fix keeps the existing async route. |
| P2 | All functions have type annotations | ✅ | Every method in the four new adapters will carry explicit parameter and return type annotations. `Any` used only for `raw_data: dict` per spec. |
| P3 | Exceptions caught per-adapter; `send_outbound` returns `SendResult` on error | ✅ | Each `send_outbound()` wraps all sends in `try/except` and returns `SendResult(success=False, error=str(e))`. `parse_inbound()` catches format errors and re-raises as `ValueError` after local logging. |
| P4 | Subclass `ChannelAdapter`; all 5 members implemented | ✅ | All four adapters implement `platform`, `should_ignore`, `extract_bot_key`, `parse_inbound`, `send_outbound`. |
| P5 | Mirrors WeComAdapter structure | ✅ | Each adapter file follows: module docstring → platform constants → class with methods in order (platform, should_ignore, extract_bot_key, parse_inbound, send_outbound) → `# ===== Private helpers =====` section. |
| P6 | Module-level logger; mandatory log events | ✅ | Each adapter declares `logger = logging.getLogger(__name__)`. INFO for inbound/outbound, DEBUG for ignored, WARNING for unexpected, ERROR+exc_info for failures. |
| P7 | Use existing clients only | ✅ | TelegramAdapter → `TelegramClient`; LarkAdapter → `LarkClient`; DiscordAdapter → `DiscordBotClient`; SlackAdapter → `SlackClient`. No raw `httpx.AsyncClient` in adapter classes. |
| P8 | Unit tests in `tests/unit/test_channel_<platform>.py` | ✅ | Four test files, each testing `parse_inbound` (happy path + error), `send_outbound` (success + failure with mocked client), `should_ignore`, and `extract_bot_key`. |
| P9 | Additive only; existing routes and WeComAdapter unchanged | ✅ | WeComAdapter: no changes. Existing route paths: no removal or renaming. `unified_callback.py`: localized fix only. `routes/discord.py`: implementation updated to call unified pipeline (route path unchanged — see Complexity Tracking). |
| P10 | All network calls async; no blocking I/O | ✅ | All client calls (`TelegramClient.send_message`, `LarkClient.send_text`, `DiscordBotClient.send_dm`, `SlackClient.post_message`) are already `async`. No `time.sleep()` or synchronous HTTP. |

> **Violation justification**: None. All principles pass.

---

## Project Structure

### Documentation (this feature)

```text
.specify/features/multi-platform-channel-adapters/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 research findings
├── data-model.md        # Field-by-field payload mappings
├── quickstart.md        # Setup, testing, curl examples
└── contracts/           # (empty for this feature; API is adapter interface, not REST)
```

### Source Code Changes

```text
forward_service/
├── channel/
│   ├── base.py              — NO CHANGES
│   ├── wecom.py             — NO CHANGES
│   ├── registry.py          — NO CHANGES
│   ├── telegram.py          — NEW: TelegramAdapter
│   ├── lark.py              — NEW: LarkAdapter
│   ├── discord.py           — NEW: DiscordAdapter
│   └── slack.py             — NEW: SlackAdapter
├── clients/
│   ├── telegram.py          — MODIFY: add get_file_url() method (pre-requisite)
│   ├── lark.py              — NO CHANGES
│   ├── discord.py           — NO CHANGES
│   └── slack.py             — NO CHANGES
├── routes/
│   ├── unified_callback.py  — MODIFY: 3 localized fixes (see below)
│   └── discord.py           — MODIFY: handle_discord_message calls process_message()
└── app.py                   — MODIFY: register 4 new adapters at startup

tests/
└── unit/
    ├── test_channel_telegram.py  — NEW
    ├── test_channel_lark.py      — NEW
    ├── test_channel_discord.py   — NEW
    └── test_channel_slack.py     — NEW
```

**Structure Decision**: Single project (existing service). All new files are added within the existing `forward_service/` package. No new packages, no new route files.

---

## Phase 0: Research Findings

*Full details in `research.md`. Summary of key decisions:*

| Decision | Chosen Approach | Key Reason |
|----------|----------------|------------|
| Telegram bot_key source | `X-Telegram-Bot-Api-Secret-Token` header | Only reliable per-bot identifier in the unified HTTP path |
| Lark bot_key source | `raw_data["header"]["app_id"]` (v2.0 schema) | Always present unencrypted; enables credential lookup before decryption |
| Lark AES decryption | `LarkClient.decrypt_event()` with per-bot encrypt_key from config | Existing client already implements AES-256-CBC; re-use per Principle 7 |
| Slack bot_key source | `raw_data.get("api_app_id")` | Identifies the Slack app, not just the workspace |
| Slack retry header | Inject `_request_headers` into `raw_data` in `unified_callback.py` | `should_ignore()` signature can't take headers; base.py is out of scope |
| Verification challenges | Duck-typed `get_verification_response()` in `unified_callback.py` | Can't add abstract method to base.py; no hardcoded platform check in route |
| Discord architecture | Update `routes/discord.py` to call unified pipeline | Discord uses WebSocket, not HTTP webhooks; existing route must become the integration point |
| Discord send | `discord_bots[bot_key].send_dm()` looked up in `routes/discord` module | Need running bot instance; coupling is minimal and documented |
| Telegram image URLs | Add `get_file_url(file_id)` to `TelegramClient` | `file_id` is not a URL; requires Telegram's `getFile` API |
| Lark image keys | Store `image_key` as-is in `images[]` for MVP | Getting download URL requires extra Lark API call; deferred to Phase 2 |

---

## Phase 1: File-by-File Implementation Design

### 1. `forward_service/clients/telegram.py` — Add `get_file_url()` (Pre-Requisite)

**Change type**: Add one async method. All existing methods unchanged.

```python
async def get_file_url(self, file_id: str) -> Optional[str]:
    """
    Resolve file_id to a download URL via Telegram getFile API.
    Returns https://api.telegram.org/file/bot{token}/{file_path} or None.
    """
    url = f"{self.base_url}/getFile"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"file_id": file_id})
            response.raise_for_status()
            data = response.json()
            if data.get("ok") and data.get("result", {}).get("file_path"):
                return (
                    f"https://api.telegram.org/file/"
                    f"bot{self.bot_token}/{data['result']['file_path']}"
                )
    except Exception as e:
        logger.error(f"getFile API 失败: file_id={file_id[:20]}, error={e}", exc_info=True)
    return None
```

---

### 2. `forward_service/routes/unified_callback.py` — Localized Fix

**Three targeted changes** to the existing file:

#### Change A: Remove hardcoded WeComAdapter fallback (FR-021)

**Before:**
```python
from ..channel.wecom import WeComAdapter
from ..channel import get_adapter
...
_default_wecom_adapter = WeComAdapter()

@router.post("/callback/{platform}")
async def handle_callback_unified(...):
    ...
    adapter = get_adapter(platform)
    if not adapter:
        if platform == "wecom":
            adapter = _default_wecom_adapter
        else:
            logger.warning(f"未注册的平台: {platform}")
            return {
                "errcode": 400,
                "errmsg": f"Unsupported platform: {platform}. Available: wecom"
            }
```

**After:**
```python
from ..channel import get_adapter, list_adapters
# (Remove: from ..channel.wecom import WeComAdapter)
# (Remove: _default_wecom_adapter = WeComAdapter())

@router.post("/callback/{platform}")
async def handle_callback_unified(...):
    ...
    adapter = get_adapter(platform)
    if not adapter:
        registered = list(list_adapters().keys())
        logger.warning(f"未注册的平台: {platform}, 已注册: {registered}")
        return {
            "errcode": 400,
            "errmsg": (
                f"Unsupported platform: {platform}. "
                f"Registered: {registered}"
            ),
        }
```

#### Change B: Inject HTTP headers into raw_data

```python
    data = await request.json()
    # Inject HTTP context for adapters that need header-based detection
    # (Telegram: bot key from X-Telegram-Bot-Api-Secret-Token;
    #  Slack: retry detection from X-Slack-Retry-Num)
    data["_request_headers"] = {k.lower(): v for k, v in request.headers.items()}
```

#### Change C: Duck-typed verification challenge support

```python
    # Handle platform verification challenges (Lark url_verification, Slack url_verification)
    # Adapters that need to respond with challenge data implement get_verification_response().
    _get_vr = getattr(adapter, "get_verification_response", None)
    if callable(_get_vr):
        vr = _get_vr(data)
        if vr is not None:
            logger.info(f"[{platform}] 返回验证挑战响应")
            return vr

    # Check should_ignore (bot messages, heartbeats, retries)
    if adapter.should_ignore(data):
        logger.debug(f"[{platform}] 忽略消息")
        return {"errcode": 0, "errmsg": "ok"}
```

**Complete resulting flow** in `handle_callback_unified`:
```
1. Auth check (unchanged)
2. Registry lookup → error if not found (fixed)
3. Parse request JSON
4. Inject _request_headers into data (new)
5. get_verification_response() duck-type check → return challenge if needed (new)
6. should_ignore() check → return ok if ignored (unchanged logic, debug level)
7. parse_inbound() → return 400 on ValueError (unchanged)
8. process_message() → return result (unchanged)
```

---

### 3. `forward_service/channel/telegram.py` — NEW

**Module structure** (following WeComAdapter pattern exactly):

```
Module docstring — Telegram adapter responsibilities
Platform constants — TELEGRAM_MAX_MESSAGE_CHARS, TELEGRAM_PHOTO_PLACEHOLDER
TelegramAdapter class:
  @property platform → "telegram"
  @property max_message_bytes → 4096 * 3 (UTF-8 safety margin)
  should_ignore(raw_data) → True if author is_bot or no message key
  extract_bot_key(raw_data, **kwargs) → from _request_headers
  parse_inbound(raw_data, **kwargs) → InboundMessage
  send_outbound(message) → SendResult
# ===== Private helpers =====
  _extract_message(raw_data) → discord.Message dict or None
  _extract_images(message, bot_key) → list[str] (resolves via get_file_url)
  _get_client(bot_key) → TelegramClient
  _truncate_text(text, max_chars) → str
```

**Key implementation details**:

`should_ignore(raw_data: dict) -> bool`:
```python
message = (
    raw_data.get("message")
    or raw_data.get("edited_message")
    or raw_data.get("channel_post")
)
if not message:
    return True   # No processable message in this Update type
from_user = message.get("from", {})
return from_user.get("is_bot", False)
```

`extract_bot_key(raw_data: dict, **kwargs: Any) -> Optional[str]`:
```python
headers = raw_data.get("_request_headers", {})
return headers.get("x-telegram-bot-api-secret-token") or None
```

`parse_inbound(raw_data: dict, **kwargs: Any) -> InboundMessage`:
```python
bot_key = self.extract_bot_key(raw_data) or ""
message = self._extract_message(raw_data)
if not message:
    raise ValueError("Update contains no processable message")

from_user = message.get("from", {})
chat = message.get("chat", {})

user_id = str(from_user.get("id", "unknown"))
first = from_user.get("first_name", "")
last = from_user.get("last_name", "")
user_name = f"{first} {last}".strip() or from_user.get("username", user_id)

chat_id = str(chat.get("id", ""))
chat_type = "direct" if chat.get("type") == "private" else "group"

text = message.get("text") or message.get("caption") or ""
images = await self._extract_images(message, bot_key)
msg_type = "image" if message.get("photo") else "text"

logger.info(
    f"[telegram] 收到消息: bot_key={bot_key[:10]}..., "
    f"user={user_name}, text={text[:50]}"
)

return InboundMessage(
    platform="telegram",
    bot_key=bot_key,
    user_id=user_id,
    user_name=user_name,
    chat_id=chat_id,
    chat_type=chat_type,
    text=text,
    images=images,
    msg_type=msg_type,
    message_id=str(message.get("message_id", "")),
    raw_data=raw_data,
)
```

`send_outbound(message: OutboundMessage) -> SendResult`:
```python
try:
    client = self._get_client(message.bot_key)
    text = message.text
    if len(text) > TELEGRAM_MAX_MESSAGE_CHARS:
        text = text[:TELEGRAM_MAX_MESSAGE_CHARS - 20] + "\n\n...(截断)"

    logger.info(
        f"[telegram] 发送消息: chat_id={message.chat_id}, "
        f"text={text[:50]}..."
    )
    await client.send_message(
        chat_id=message.chat_id,
        text=text,
        parse_mode="Markdown",
    )
    return SendResult(success=True, parts_sent=1)
except Exception as e:
    logger.error(f"[telegram] 发送失败: {e}", exc_info=True)
    return SendResult(success=False, error=str(e))
```

`_get_client(bot_key: str) -> TelegramClient`:
```python
from ..config import config
bot = config.get_bot(bot_key)
if not bot:
    raise ValueError(f"未找到 Telegram bot 配置: {bot_key[:10]}...")
platform_config = bot.get_platform_config()
bot_token = platform_config.get("bot_token", "")
if not bot_token:
    raise ValueError(f"Telegram bot_token 未配置: {bot_key[:10]}...")
return TelegramClient(bot_token=bot_token)
```

---

### 4. `forward_service/channel/lark.py` — NEW

**Module structure**:

```
Module docstring — Lark adapter responsibilities (including AES decryption note)
Platform constants — LARK_MAX_MESSAGE_CHARS, LARK_EVENT_TYPE_MESSAGE
LarkAdapter class:
  @property platform → "lark"
  should_ignore(raw_data) → True if sender_type == "bot"
  extract_bot_key(raw_data, **kwargs) → from header.app_id
  get_verification_response(raw_data) → challenge dict or None (non-abstract)
  parse_inbound(raw_data, **kwargs) → InboundMessage (with decrypt)
  send_outbound(message) → SendResult
# ===== Private helpers =====
  _decrypt_if_needed(raw_data, bot_key) → dict (decrypted event or original)
  _extract_text_from_content(content_str, message_type) → str
  _extract_images_from_content(content_str, message_type) → list[str]
  _get_client(bot_key) → LarkClient
```

**Key implementation details**:

`get_verification_response(raw_data: dict) -> Optional[dict]`:
```python
# Not in abstract base — duck-typed by unified_callback.py
if raw_data.get("type") == "url_verification":
    challenge = raw_data.get("challenge", "")
    logger.info("[lark] 返回 URL 验证挑战")
    return {"challenge": challenge}
return None
```

`should_ignore(raw_data: dict) -> bool`:
```python
event = raw_data.get("event", {})
sender = event.get("sender", {})
if sender.get("sender_type") == "bot":
    logger.debug("[lark] 忽略 Bot 消息")
    return True
return False
```

`extract_bot_key(raw_data: dict, **kwargs: Any) -> Optional[str]`:
```python
return raw_data.get("header", {}).get("app_id") or None
```

`parse_inbound(raw_data: dict, **kwargs: Any) -> InboundMessage`:
```python
bot_key = self.extract_bot_key(raw_data) or ""

# Decrypt if encrypted payload
try:
    event_data = self._decrypt_if_needed(raw_data, bot_key)
except Exception as e:
    logger.warning(f"[lark] AES 解密失败: {e}")
    raise ValueError(f"Lark event decryption failed: {e}") from e

header = event_data.get("header", {})
event = event_data.get("event", {})
message = event.get("message", {})
sender = event.get("sender", {})

sender_id = sender.get("sender_id", {})
user_id = sender_id.get("open_id", sender_id.get("user_id", "unknown"))
user_name = sender_id.get("user_id", user_id)

chat_id = message.get("chat_id", "")
chat_type_raw = message.get("chat_type", "group")
chat_type = "direct" if chat_type_raw == "p2p" else "group"
message_type = message.get("message_type", "text")
content_str = message.get("content", "{}")

text = self._extract_text_from_content(content_str, message_type)
images = self._extract_images_from_content(content_str, message_type)
msg_type = "image" if images and not text else message_type

logger.info(
    f"[lark] 收到消息: bot_key={bot_key[:10]}..., "
    f"user={user_name}, text={text[:50]}"
)

return InboundMessage(
    platform="lark",
    bot_key=bot_key,
    user_id=user_id,
    user_name=user_name,
    chat_id=chat_id,
    chat_type=chat_type,
    text=text,
    images=images,
    msg_type=msg_type,
    message_id=message.get("message_id", ""),
    raw_data=raw_data,
)
```

`_decrypt_if_needed(raw_data: dict, bot_key: str) -> dict`:
```python
if "encrypt" not in raw_data:
    return raw_data   # Unencrypted: use as-is

client = self._get_client(bot_key)
decrypted = client.decrypt_event(raw_data["encrypt"])
# Re-attach original header if present (for bot_key / app_id continuity)
if "header" in raw_data and "header" not in decrypted:
    decrypted["header"] = raw_data["header"]
return decrypted
```

`send_outbound(message: OutboundMessage) -> SendResult`:
```python
try:
    client = self._get_client(message.bot_key)
    logger.info(
        f"[lark] 发送消息: chat_id={message.chat_id}, "
        f"text={message.text[:50]}..."
    )
    await client.send_text(
        receive_id=message.chat_id,
        text=message.text,
        receive_id_type="chat_id",
    )
    return SendResult(success=True, parts_sent=1)
except Exception as e:
    logger.error(f"[lark] 发送失败: {e}", exc_info=True)
    return SendResult(success=False, error=str(e))
```

---

### 5. `forward_service/channel/discord.py` — NEW

**Module structure**:

```
Module docstring — Discord adapter responsibilities; notes WebSocket coupling to routes/discord.discord_bots
Platform constants — DISCORD_MAX_MESSAGE_CHARS = 2000, DISCORD_CHUNK_SIZE = 1900
DiscordAdapter class:
  @property platform → "discord"
  should_ignore(raw_data) → True if author_is_bot
  extract_bot_key(raw_data, **kwargs) → from kwargs["bot_key"] or raw_data
  parse_inbound(raw_data, **kwargs) → InboundMessage
  send_outbound(message) → SendResult (chunked)
# ===== Private helpers =====
  _get_bot_client(bot_key) → DiscordBotClient
  _send_chunked(client, user_id, text) → int (parts sent)
```

**Key implementation details**:

`extract_bot_key(raw_data: dict, **kwargs: Any) -> Optional[str]`:
```python
# bot_key is injected by routes/discord.py as a kwarg when calling parse_inbound()
return kwargs.get("bot_key") or raw_data.get("_bot_key") or None
```

`should_ignore(raw_data: dict) -> bool`:
```python
if raw_data.get("author_is_bot"):
    logger.debug("[discord] 忽略 Bot 消息")
    return True
return False
```

`parse_inbound(raw_data: dict, **kwargs: Any) -> InboundMessage`:
```python
bot_key = self.extract_bot_key(raw_data, **kwargs) or ""
user_id = raw_data.get("user_id", "unknown")
user_name = raw_data.get("user_name", user_id)
content = raw_data.get("content", "")

# Extract image URLs from attachments
images = [
    a["url"]
    for a in raw_data.get("attachments", [])
    if a.get("content_type", "").startswith("image/")
]
msg_type = "image" if images else "text"

logger.info(
    f"[discord] 收到消息: bot_key={bot_key[:10]}..., "
    f"user={user_name}, text={content[:50]}"
)

return InboundMessage(
    platform="discord",
    bot_key=bot_key,
    user_id=user_id,
    user_name=user_name,
    chat_id=user_id,        # DM: use user_id as the stable chat identifier
    chat_type="direct",
    text=content,
    images=images,
    msg_type=msg_type,
    message_id=raw_data.get("message_id", ""),
    raw_data=raw_data,
)
```

`send_outbound(message: OutboundMessage) -> SendResult`:
```python
try:
    client = self._get_bot_client(message.bot_key)
    user_id = int(message.chat_id)
    parts = await self._send_chunked(client, user_id, message.text)
    return SendResult(success=True, parts_sent=parts)
except Exception as e:
    logger.error(f"[discord] 发送失败: {e}", exc_info=True)
    return SendResult(success=False, error=str(e))
```

`_get_bot_client(bot_key: str) -> DiscordBotClient`:
```python
# Import from routes module; coupling is documented and intentional.
# DEVIATION NOTE: Discord uses WebSocket; no alternative without duplicating the connection.
from ..routes.discord import discord_bots
client = discord_bots.get(bot_key)
if not client:
    raise ValueError(f"Discord Bot 未运行: {bot_key[:10]}...")
return client
```

`_send_chunked(client: DiscordBotClient, user_id: int, text: str) -> int`:
```python
if len(text) <= DISCORD_MAX_MESSAGE_CHARS:
    await client.send_dm(user_id, text)
    return 1
chunks = [
    text[i : i + DISCORD_CHUNK_SIZE]
    for i in range(0, len(text), DISCORD_CHUNK_SIZE)
]
total = len(chunks)
for idx, chunk in enumerate(chunks):
    prefix = f"({idx + 1}/{total}) " if total > 1 else ""
    await client.send_dm(user_id, prefix + chunk)
logger.info(f"[discord] 消息分拆发送: {total} 条")
return total
```

---

### 6. `forward_service/channel/slack.py` — NEW

**Module structure**:

```
Module docstring — Slack adapter responsibilities (URL verification, retry handling)
Platform constants — SLACK_MAX_MESSAGE_CHARS = 40000
SlackAdapter class:
  @property platform → "slack"
  should_ignore(raw_data) → True if retry header present or bot message
  extract_bot_key(raw_data, **kwargs) → from api_app_id
  get_verification_response(raw_data) → challenge dict or None (non-abstract)
  parse_inbound(raw_data, **kwargs) → InboundMessage
  send_outbound(message) → SendResult
# ===== Private helpers =====
  _extract_images(event) → list[str]
  _get_client(bot_key) → SlackClient
```

**Key implementation details**:

`get_verification_response(raw_data: dict) -> Optional[dict]`:
```python
if raw_data.get("type") == "url_verification":
    challenge = raw_data.get("challenge", "")
    logger.info("[slack] 返回 URL 验证挑战")
    return {"challenge": challenge}
return None
```

`should_ignore(raw_data: dict) -> bool`:
```python
headers = raw_data.get("_request_headers", {})
if "x-slack-retry-num" in headers:
    logger.debug("[slack] 忽略 Slack 重试请求")
    return True
event = raw_data.get("event", {})
if event.get("bot_id") or event.get("subtype") == "bot_message":
    logger.debug("[slack] 忽略 Bot 消息")
    return True
return False
```

`extract_bot_key(raw_data: dict, **kwargs: Any) -> Optional[str]`:
```python
return raw_data.get("api_app_id") or None
```

`parse_inbound(raw_data: dict, **kwargs: Any) -> InboundMessage`:
```python
bot_key = self.extract_bot_key(raw_data) or ""
event = raw_data.get("event", {})
user_id = event.get("user", "unknown")
channel = event.get("channel", "")
ts = event.get("ts", "")

# DM channels start with "D"
chat_type = "direct" if channel.startswith("D") else "group"

text = event.get("text", "")
images = self._extract_images(event)
msg_type = "image" if images else "text"

event_id = raw_data.get("event_id", "")
message_id = event_id or f"{channel}:{ts}"

logger.info(
    f"[slack] 收到消息: bot_key={bot_key[:10]}..., "
    f"user={user_id}, channel={channel}, text={text[:50]}"
)

return InboundMessage(
    platform="slack",
    bot_key=bot_key,
    user_id=user_id,
    user_name=user_id,    # Display name requires Users API; use ID as fallback
    chat_id=channel,
    chat_type=chat_type,
    text=text,
    images=images,
    msg_type=msg_type,
    message_id=message_id,
    raw_data=raw_data,
)
```

`send_outbound(message: OutboundMessage) -> SendResult`:
```python
try:
    client = self._get_client(message.bot_key)
    logger.info(
        f"[slack] 发送消息: channel={message.chat_id}, "
        f"text={message.text[:50]}..."
    )
    await client.post_message(
        channel=message.chat_id,
        text=message.text,
    )
    return SendResult(success=True, parts_sent=1)
except Exception as e:
    logger.error(f"[slack] 发送失败: {e}", exc_info=True)
    return SendResult(success=False, error=str(e))
```

`_extract_images(event: dict) -> list[str]`:
```python
files = event.get("files", [])
return [
    f["url_private_download"]
    for f in files
    if f.get("mimetype", "").startswith("image/")
    and f.get("url_private_download")
]
```

---

### 7. `forward_service/routes/discord.py` — Update handle_discord_message

**Change scope**: The `handle_discord_message` function only. The Discord WebSocket lifecycle (bot startup, `on_ready`, `on_message`, `start_discord_bot`, `get_discord_bot`) is unchanged.

**Before** (standalone pipeline logic):
```python
async def handle_discord_message(message: discord.Message, client: DiscordBotClient):
    user_id = str(message.author.id)
    content = message.content
    bot = config.get_bot_or_default(client.bot_key)
    # ... standalone session, forward, reply logic (~80 lines) ...
```

**After** (delegate to unified pipeline):
```python
async def handle_discord_message(message: discord.Message, client: DiscordBotClient):
    """处理 Discord DM 消息 — 通过统一 ChannelAdapter 管线处理"""
    from ..channel import get_adapter
    from ..pipeline import process_message

    # Ignore bot self-messages
    if message.author.bot:
        logger.debug(f"[discord] 忽略 Bot 消息: {message.author}")
        return

    adapter = get_adapter("discord")
    if not adapter:
        logger.error("[discord] DiscordAdapter 未注册，跳过消息处理")
        return

    # Serialize discord.Message to a plain dict for the adapter
    raw = {
        "message_id": str(message.id),
        "user_id": str(message.author.id),
        "user_name": str(message.author),
        "content": message.content or "",
        "attachments": [
            {
                "url": a.url,
                "content_type": a.content_type or "",
                "filename": a.filename,
            }
            for a in message.attachments
        ],
        "author_is_bot": message.author.bot,
    }

    try:
        inbound = await adapter.parse_inbound(raw, bot_key=client.bot_key)
    except ValueError as e:
        logger.error(f"[discord] 消息解析失败: {e}")
        await message.channel.send("⚠️ 消息解析失败，请重试")
        return

    await process_message(adapter, inbound)
```

**Why this change is necessary and acceptable**: Discord messages arrive via WebSocket gateway, not HTTP POST. There is no way for the `POST /callback/discord` endpoint to receive regular Discord messages. The only integration point is the WebSocket callback already handled by `routes/discord.py`. Updating `handle_discord_message` to delegate to the unified pipeline is the equivalent of how Telegram, Lark, and Slack route through `unified_callback.py` — it's the platform's ingress point, not a backward-incompatible change. The Discord user experience (send DM → get reply) is identical before and after.

---

### 8. `forward_service/app.py` — Register New Adapters

**Existing registration** (unchanged):
```python
register_adapter(WeComAdapter())
logger.info("  通道适配器已注册: wecom")
```

**Add immediately after** (new):
```python
from .channel.telegram import TelegramAdapter
from .channel.lark import LarkAdapter
from .channel.discord import DiscordAdapter
from .channel.slack import SlackAdapter

register_adapter(TelegramAdapter())
logger.info("  通道适配器已注册: telegram")

register_adapter(LarkAdapter())
logger.info("  通道适配器已注册: lark")

register_adapter(DiscordAdapter())
logger.info("  通道适配器已注册: discord")

register_adapter(SlackAdapter())
logger.info("  通道适配器已注册: slack")
```

The Discord WebSocket bot startup code (existing `for bot_key in discord_bots: asyncio.create_task(...)`) remains exactly as-is.

---

## Implementation Order (Task Dependencies)

```
Step 1: clients/telegram.py — add get_file_url()        [no dependencies]
Step 2: channel/telegram.py — TelegramAdapter            [depends on Step 1]
Step 3: channel/lark.py — LarkAdapter                   [no dependencies]
Step 4: channel/discord.py — DiscordAdapter              [no dependencies (import is lazy)]
Step 5: channel/slack.py — SlackAdapter                  [no dependencies]
Step 6: routes/unified_callback.py — 3-part fix          [depends on Steps 2–5 registered]
Step 7: routes/discord.py — update handle_discord_message [depends on Step 4]
Step 8: app.py — register new adapters                   [depends on Steps 2–5]
Step 9: Unit tests — 4 test files                        [depends on Steps 2–5]
```

Steps 2–5 and their unit tests (Step 9) can be implemented in parallel.  
Steps 6, 7, 8 are integration steps done after the adapters exist.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Lark AES key length mismatch | Medium | High — decryption silently corrupts or raises | Catch `ValueError`/`KeyError` from `decrypt_event()`, log WARNING, return 400. Add unit test with known key/ciphertext pair. Document that `encrypt_key` must be exactly 32 UTF-8 bytes. |
| Telegram `getFile` rate limit | Low | Low — image URLs not resolved | On failure, `get_file_url()` returns `None`; adapter includes no image URL in `images[]` but still processes text. Log WARNING. |
| Discord `send_dm()` fails when bot instance not running | Medium | Medium — `send_outbound()` raises | `_get_bot_client()` raises `ValueError` caught by `send_outbound()`'s try/except → returns `SendResult(success=False)`. Pipeline logs ERROR. |
| Slack `api_app_id` absent (e.g., old Slack event format) | Low | Medium — `bot_key=""`, bot not found | Pipeline creates skeleton bot. Document that Events API v2 (`api_app_id` field) is required. |
| `routes/discord.py` change breaks existing Discord DM handling | Low | High | Preserve identical user-visible behavior. Unit test `handle_discord_message` with mocked adapter. Keep `handle_discord_command` unchanged (called by the route, not by the adapter path). |
| Slack retry responding too slowly (timeout → retry loop) | Medium | Low | `should_ignore()` runs in < 1ms (just a dict lookup). Return 200 immediately when retry detected. No AI pipeline overhead. |

---

## Complexity Tracking

> Required by Constitution Principle 9 — deviation from "existing routes unchanged" for Discord

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|-----------|--------------------------------------|
| `routes/discord.py` `handle_discord_message` implementation updated | Discord uses WebSocket (discord.py gateway), not HTTP webhooks. The only way to run Discord messages through the unified pipeline is to update the existing WebSocket callback handler. | Pure registry registration with no route change would leave Discord messages on the old standalone pipeline — the core purpose of this feature would not be achieved for Discord. A separate new route for Discord would also require updates to the existing handler (to avoid double-processing). |

---

## Constitution Validation (Post-Design Re-check)

All 10 principles remain satisfied after Phase 1 design:

- **P3**: Both the `DiscordAdapter._get_bot_client()` failure path and the `handle_discord_message` update propagate to `SendResult(success=False, ...)` without unhandled exceptions.
- **P7**: `DiscordAdapter._get_bot_client()` imports from `routes/discord.discord_bots` — this is a runtime lookup of an existing client instance, not creating a new HTTP session. Compliant with Principle 7.
- **P9**: The only change to an existing file with behavioral impact is the `handle_discord_message` function in `routes/discord.py`. The route path (`/discord/dm` or the WebSocket callback) is not changed, not removed, and not renamed. WeComAdapter is unchanged. `base.py`, `pipeline.py`, and `registry.py` are unchanged.

---

## Readiness for Task Breakdown

✅ All NEEDS CLARIFICATION items resolved (see `research.md`)  
✅ All 10 Constitution principles verified compliant  
✅ Data model documented (see `data-model.md`) — no database schema changes  
✅ File-by-file implementation design complete with code skeletons  
✅ Implementation order and dependencies defined  
✅ Risks identified with mitigations  
✅ Quickstart and test examples documented (see `quickstart.md`)  

**Ready for `/speckit.tasks` to generate the task breakdown.**
