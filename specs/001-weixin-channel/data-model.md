# Data Model: 个人微信通道接入 (Weixin Channel)

**Date**: 2026-03-22
**Plan**: `specs/001-weixin-channel/plan.md`

---

## Overview

The Weixin channel introduces **no new database tables**. All persistent state is stored in the existing `chatbot` table's `platform_config` JSON column, following the same pattern used by QQBot and Discord adapters. Runtime state is managed through in-memory dataclasses.

## 1. Persisted State (Database)

### 1.1 Bot Credentials — `chatbot.platform_config` JSON

When a chatbot record has `platform = "weixin"`, its `platform_config` JSON column stores:

```json
{
  "bot_token": "eyJhbGciOi...",
  "ilink_bot_id": "bot_123456",
  "ilink_user_id": "user_789",
  "get_updates_buf": "base64_opaque_cursor...",
  "login_status": "logged_in",
  "last_active_at": "2026-03-22T10:30:00Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `bot_token` | `str` | Yes (after login) | Bearer token for iLinkAI API authentication |
| `ilink_bot_id` | `str` | Yes (after login) | Bot identifier returned on QR confirmation |
| `ilink_user_id` | `str` | Yes (after login) | WeChat user identifier for the bot account |
| `get_updates_buf` | `str` | No | Opaque long-poll cursor; persisted after each poll cycle |
| `login_status` | `str` | No | `"logged_in"` / `"expired"` / `"pending"` — informational |
| `last_active_at` | `str` (ISO 8601) | No | Timestamp of last successful poll or message send |

**Lifecycle**:
- Created empty when admin creates a Weixin bot via existing Bot management API
- Populated with `bot_token`, `ilink_bot_id`, `ilink_user_id` after successful QR login
- `get_updates_buf` updated after each successful poll cycle
- `login_status` updated on login success, session expiry, and stop

---

## 2. Runtime State (In-Memory)

### 2.1 WeixinClient

```python
@dataclass
class WeixinClient:
    """iLinkAI HTTP API client for a single WeChat bot account."""
    
    bot_token: str
    """Bearer token for API authentication."""
    
    _http: httpx.AsyncClient
    """Shared async HTTP client instance."""
```

**Validation**: `bot_token` must be non-empty. `_http` created in `__init__`, closed in `close()`.

### 2.2 WeixinPoller

```python
@dataclass
class WeixinPoller:
    """Runtime state for a single WeChat bot's long-poll loop."""
    
    bot_key: str
    """Bot identifier in as-dispatch (maps to chatbot.bot_key)."""
    
    client: WeixinClient
    """HTTP client for iLinkAI API calls."""
    
    status: WeixinPollerStatus
    """Current poller state."""
    
    get_updates_buf: str
    """Opaque cursor for long-poll continuity. Loaded from DB on start."""
    
    context_tokens: dict[str, str]
    """Cache: user_id → most recent context_token. Used for reply routing."""
    
    consecutive_failures: int
    """Counter for exponential backoff. Reset to 0 on successful poll."""
    
    _task: asyncio.Task | None
    """Background asyncio task running the poll loop."""
    
    ilink_bot_id: str
    """Bot ID from iLinkAI, for logging and typing API calls."""
```

**State Transitions**:

```
                  start_weixin()
    [stopped] ──────────────────► [running]
        ▲                            │
        │ stop_weixin()              │ errcode=-14
        │                            ▼
        │                        [paused]
        │                            │
        │                            │ 1 hour sleep
        │                            ▼
        │                        [running] ──► retry fails ──► [expired]
        │                                                         │
        └──── stop_weixin() ◄─────────────────────────────────────┘
```

### 2.3 WeixinPollerStatus (Enum)

```python
class WeixinPollerStatus(str, Enum):
    STOPPED = "stopped"       # Not running; initial state or after admin stop
    RUNNING = "running"       # Active long-poll loop
    PAUSED = "paused"         # Session expiry detected; waiting 1 hour
    EXPIRED = "expired"       # Session invalid; requires QR re-login
    LOGIN_PENDING = "login_pending"  # QR login in progress
```

### 2.4 QRLoginAttempt

```python
@dataclass
class QRLoginAttempt:
    """Tracks an in-progress QR code login flow."""
    
    qrcode: str
    """QR code identifier returned by iLinkAI."""
    
    qrcode_url: str
    """QR code image URL for admin to display/scan."""
    
    status: str
    """Current status: 'wait' / 'scaned' / 'confirmed' / 'expired'."""
    
    refresh_count: int
    """Number of times the QR code has been auto-refreshed (max 3)."""
    
    created_at: datetime
    """Timestamp when this login attempt started."""
    
    bot_token: str | None
    """Populated on 'confirmed' — the obtained bot token."""
    
    ilink_bot_id: str | None
    """Populated on 'confirmed' — the bot ID."""
    
    ilink_user_id: str | None
    """Populated on 'confirmed' — the user ID."""
```

**Lifecycle**: Created on `POST /{bot_key}/qr-login`, updated on each `GET /{bot_key}/qr-status` poll. Auto-refreshed up to 3 times on expiry. Discarded after login completes or fails.

### 2.5 Inbound Message Mapping (iLinkAI → InboundMessage)

The raw iLinkAI message structure (from `getupdates` response):

```json
{
  "from_user_name": "用户昵称",
  "from_user_id": "wxid_abc123",
  "context_token": "ctx_token_xyz",
  "message_state": 3,
  "item_list": [
    {
      "type": 1,
      "content": "你好"
    }
  ]
}
```

Mapped to internal dict (by `WeixinPoller._parse_message`):

```python
{
    "type": "direct",           # Always direct (no group chat)
    "sender_id": "wxid_abc123",
    "sender_name": "用户昵称",
    "content": "你好",
    "message_type": "text",     # Derived from item_list[0].type
    "context_token": "ctx_token_xyz",
    "_bot_key": "bot_key_xxx",  # Injected by poller
}
```

Then converted by `WeixinAdapter.parse_inbound()` to `InboundMessage`:

| Raw Field | InboundMessage Field | Transformation |
|---|---|---|
| `"weixin"` | `platform` | Constant |
| `_bot_key` | `bot_key` | Injected by poller |
| `sender_id` | `user_id` | Direct mapping |
| `sender_name` | `user_name` | Direct mapping |
| `""` | `user_alias` | Not available; empty default |
| `f"direct:{sender_id}"` | `chat_id` | Synthetic format for pipeline compatibility |
| `"direct"` | `chat_type` | Always direct |
| `content` | `text` | From first TEXT item |
| `[]` | `images` | Empty for MVP |
| `message_type` | `msg_type` | `"text"` / `"image"` / `"voice"` / `"file"` / `"video"` |
| `None` | `quoted_short_id` | Not supported in iLinkAI |
| hash of content + timestamp | `message_id` | Generated for dedup |
| full raw dict | `raw_data` | Preserved including `context_token` |

### 2.6 Message Type Constants

```python
WEIXIN_MSG_TYPE_TEXT = 1
WEIXIN_MSG_TYPE_IMAGE = 2
WEIXIN_MSG_TYPE_VOICE = 3
WEIXIN_MSG_TYPE_FILE = 4
WEIXIN_MSG_TYPE_VIDEO = 5

WEIXIN_MSG_TYPE_NAMES: dict[int, str] = {
    1: "text",
    2: "image",
    3: "voice",
    4: "file",
    5: "video",
}

WEIXIN_NON_TEXT_PLACEHOLDERS: dict[int, str] = {
    2: "[收到了图片，暂不支持处理图片消息]",
    3: "[收到了语音，暂不支持处理语音消息]",
    4: "[收到了文件，暂不支持处理文件消息]",
    5: "[收到了视频，暂不支持处理视频消息]",
}
```

---

## 3. Module-Level State (routes/weixin.py)

```python
# Active poller instances: bot_key → WeixinPoller
weixin_pollers: dict[str, WeixinPoller] = {}

# Active QR login attempts: bot_key → QRLoginAttempt
weixin_login_attempts: dict[str, QRLoginAttempt] = {}
```

These are analogous to `qqbot_clients: Dict[str, QQBotClient]` in `routes/qqbot.py`.

---

## 4. Relationships

```
chatbot (existing table)
  └── platform_config (JSON) → WeixinClient credentials
  └── bot_key ──────────────► weixin_pollers[bot_key] (runtime)
                                  ├── .client (WeixinClient)
                                  ├── .context_tokens (dict)
                                  └── .get_updates_buf (str)

weixin_login_attempts[bot_key] → QRLoginAttempt (transient, during login only)
```
