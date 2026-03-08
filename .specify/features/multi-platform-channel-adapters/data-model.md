# Data Model: Multi-Platform IM ChannelAdapter Unification

**Date**: 2026-03-02  
**Status**: Complete — no new database tables; existing models are sufficient

---

## Summary

This feature adds no new database tables and makes no changes to existing database schemas. All entities are either existing dataclasses (`InboundMessage`, `OutboundMessage`, `SendResult`) or in-memory constructs (adapter registry).

The section below documents how each new platform maps its raw webhook payload to the existing `InboundMessage` fields.

---

## Existing Entities (No Changes)

### InboundMessage

Defined in `forward_service/channel/base.py`. All four new adapters map to this structure.

```python
@dataclass
class InboundMessage:
    platform: str          # "telegram" | "lark" | "discord" | "slack"
    bot_key: str           # Platform-specific bot identifier (see mapping table)
    user_id: str           # Sender user ID (stringified)
    user_name: str         # Sender display name
    user_alias: str = ""   # Not used by new platforms; always ""
    chat_id: str = ""      # Chat/channel/group ID (stringified)
    chat_type: str = "group"  # "direct" | "group"
    text: str = ""         # Message text (cleaned)
    images: list[str] = field(default_factory=list)  # Image URLs or keys
    msg_type: str = "text" # "text" | "image" | "mixed"
    quoted_short_id: Optional[str] = None  # Not used by new platforms; None
    message_id: str = ""   # Platform message ID for deduplication
    raw_data: dict = field(default_factory=dict)
```

### OutboundMessage

Defined in `forward_service/channel/base.py`. Pipeline produces this; adapters consume it.

```python
@dataclass
class OutboundMessage:
    chat_id: str           # Target chat/channel/user ID
    text: str              # Reply text
    msg_type: str = "text" # "text" | "markdown"
    bot_key: str = ""      # Bot to send from
    short_id: Optional[str] = None
    project_name: Optional[str] = None
    mentioned_user_ids: Optional[list[str]] = None
    extra: dict = field(default_factory=dict)  # Platform-specific extensions
```

### SendResult

```python
@dataclass
class SendResult:
    success: bool
    parts_sent: int = 0
    error: Optional[str] = None
```

---

## Platform → InboundMessage Field Mapping

### Telegram

**Raw payload structure** (`Update` object):
```json
{
  "update_id": 123456789,
  "message": {
    "message_id": 42,
    "from": {
      "id": 111222333,
      "is_bot": false,
      "first_name": "Alice",
      "username": "alice_tg"
    },
    "chat": {
      "id": 111222333,
      "type": "private"
    },
    "text": "Hello bot!",
    "photo": [
      {"file_id": "AgAC...", "width": 320, "height": 240},
      {"file_id": "AgAD...", "width": 1280, "height": 960}
    ]
  },
  "_request_headers": {"x-telegram-bot-api-secret-token": "my-bot-key"}
}
```

| InboundMessage field | Source | Notes |
|---------------------|--------|-------|
| `platform` | `"telegram"` | Literal |
| `bot_key` | `raw_data["_request_headers"]["x-telegram-bot-api-secret-token"]` | Set by operator during webhook registration |
| `user_id` | `str(message["from"]["id"])` | |
| `user_name` | `f'{message["from"].get("first_name", "")} {message["from"].get("last_name", "")}'.strip()` or `username` | |
| `user_alias` | `""` | Not applicable |
| `chat_id` | `str(message["chat"]["id"])` | |
| `chat_type` | `"direct"` if `chat["type"] == "private"` else `"group"` | |
| `text` | `message.get("text", "")` | Caption for photo messages |
| `images` | Resolved URLs from `message["photo"][-1]["file_id"]` via `TelegramClient.get_file_url()` | Last photo = highest resolution |
| `msg_type` | `"image"` if photo present, else `"text"` | |
| `message_id` | `str(message["message_id"])` | |

**should_ignore conditions**:
- `message["from"].get("is_bot") == True` → ignore bot messages
- No `message` key in update (e.g., `channel_post`, `callback_query`) → ignore unless handled

---

### Lark (飞书)

**Raw payload structure** (Events API v2.0, possibly encrypted):

Unencrypted:
```json
{
  "schema": "2.0",
  "header": {
    "event_id": "5e3702a84e1b4b7c8...",
    "event_type": "im.message.receive_v1",
    "create_time": "1608725989000",
    "token": "xxx",
    "app_id": "cli_9c8609450f7a100e",
    "tenant_key": "2ca1d211f64f6438"
  },
  "event": {
    "sender": {
      "sender_id": {
        "user_id": "ou_123abc",
        "open_id": "ou_456def",
        "union_id": "on_789ghi"
      },
      "sender_type": "user"
    },
    "message": {
      "message_id": "om_abcdef",
      "root_id": "om_rootid",
      "parent_id": "om_parentid",
      "create_time": "1609073151",
      "chat_id": "oc_groupid123",
      "chat_type": "group",
      "message_type": "text",
      "content": "{\"text\":\"Hello bot!\"}"
    }
  }
}
```

Encrypted:
```json
{
  "schema": "2.0",
  "header": {
    "app_id": "cli_9c8609450f7a100e",
    ...
  },
  "encrypt": "base64_encrypted_data..."
}
```

URL verification challenge:
```json
{
  "challenge": "ajls384kdjx98XX",
  "token": "xxxxxx",
  "type": "url_verification"
}
```

| InboundMessage field | Source | Notes |
|---------------------|--------|-------|
| `platform` | `"lark"` | Literal |
| `bot_key` | `raw_data["header"]["app_id"]` | Lark app_id uniquely identifies the bot |
| `user_id` | `event["sender"]["sender_id"]["open_id"]` | open_id is stable across apps |
| `user_name` | `event["sender"]["sender_id"]["user_id"]` or `open_id` | Display name requires extra API call; use ID as fallback |
| `user_alias` | `""` | Not applicable |
| `chat_id` | `event["message"]["chat_id"]` | |
| `chat_type` | `"direct"` if `message["chat_type"] == "p2p"` else `"group"` | |
| `text` | `json.loads(message["content"]).get("text", "")` | Content is JSON-encoded string |
| `images` | `message["content"]["image_key"]` when `message_type == "image"` | Image key (not URL); requires Lark API to resolve |
| `msg_type` | `message["message_type"]` | "text" \| "image" \| "post" |
| `message_id` | `message["message_id"]` | Used for deduplication |

**should_ignore conditions**:
- `event["sender"]["sender_type"] == "bot"` → ignore bot-originated messages

**get_verification_response conditions**:
- `raw_data.get("type") == "url_verification"` → return `{"challenge": raw_data["challenge"]}`

---

### Discord

**Raw dict structure** (from WebSocket `discord.Message`, serialized in `routes/discord.py`):
```json
{
  "message_id": "1234567890123456789",
  "user_id": "987654321098765432",
  "user_name": "Bob#1234",
  "chat_id": "987654321098765432",
  "content": "Hello bot!",
  "attachments": [
    {
      "url": "https://cdn.discordapp.com/attachments/.../image.png",
      "content_type": "image/png",
      "filename": "image.png"
    }
  ],
  "author_is_bot": false
}
```

| InboundMessage field | Source | Notes |
|---------------------|--------|-------|
| `platform` | `"discord"` | Literal |
| `bot_key` | `kwargs["bot_key"]` | Passed by `routes/discord.py` when calling `parse_inbound()` |
| `user_id` | `raw_data["user_id"]` | Discord user snowflake ID |
| `user_name` | `raw_data["user_name"]` | `username#discriminator` format |
| `user_alias` | `""` | Not applicable |
| `chat_id` | `raw_data["user_id"]` | For DMs: chat is identified by the user's ID |
| `chat_type` | `"direct"` | Current implementation: DMs only |
| `text` | `raw_data.get("content", "")` | |
| `images` | CDN URLs from `attachments` where `content_type.startswith("image/")` | Direct URLs, no auth needed |
| `msg_type` | `"image"` if attachments present, else `"text"` | |
| `message_id` | `raw_data["message_id"]` | Discord message snowflake ID |

**should_ignore conditions**:
- `raw_data.get("author_is_bot") == True` → ignore bot self-messages

---

### Slack

**Raw payload structure** (Events API, event type: `message`):
```json
{
  "token": "Jhj5dZrVaK7ZwHHjRyZWjbDl",
  "team_id": "T061EG9R6",
  "api_app_id": "A0FFV41KK",
  "event": {
    "type": "message",
    "channel": "C2147483705",
    "user": "U2147483697",
    "text": "Hello bot!",
    "ts": "1355517523.000005",
    "files": [
      {
        "id": "F12345678",
        "url_private_download": "https://files.slack.com/...",
        "mimetype": "image/png"
      }
    ]
  },
  "event_id": "Ev0PV52K21",
  "event_time": 1355517523,
  "type": "event_callback",
  "_request_headers": {"x-slack-retry-num": "1"}
}
```

URL verification challenge:
```json
{
  "token": "Jhj5dZrVaK7ZwHHjRyZWjbDl",
  "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9zS3zQ6ap3rodXEnsWn7Cewhr",
  "type": "url_verification"
}
```

| InboundMessage field | Source | Notes |
|---------------------|--------|-------|
| `platform` | `"slack"` | Literal |
| `bot_key` | `raw_data.get("api_app_id", "")` | Absent in url_verification; handled before pipeline |
| `user_id` | `raw_data["event"]["user"]` | Slack user ID |
| `user_name` | `raw_data["event"]["user"]` | Display name requires Users API call; use ID as fallback |
| `user_alias` | `""` | Not applicable |
| `chat_id` | `raw_data["event"]["channel"]` | Slack channel ID |
| `chat_type` | `"direct"` if `channel.startswith("D")` else `"group"` | Channel IDs starting with "D" are DMs |
| `text` | `raw_data["event"].get("text", "")` | |
| `images` | `url_private_download` from `files` where `mimetype.startswith("image/")` | Requires `Authorization: Bearer {token}` to download |
| `msg_type` | `"image"` if files with image mimetype present, else `"text"` | |
| `message_id` | `raw_data.get("event_id", raw_data["event"].get("ts", ""))` | Prefer event_id for deduplication |

**should_ignore conditions**:
- `"x-slack-retry-num" in raw_data.get("_request_headers", {})` → ignore retries
- `raw_data["event"].get("bot_id")` is not None → ignore bot-originated messages
- `raw_data["event"].get("subtype") == "bot_message"` → ignore bot messages

**get_verification_response conditions**:
- `raw_data.get("type") == "url_verification"` → return `{"challenge": raw_data["challenge"]}`

---

## OutboundMessage → Platform-Specific Behavior

| Platform | send_outbound() implementation | Character limit | Splitting |
|----------|-------------------------------|----------------|-----------|
| **Telegram** | `TelegramClient.send_message(chat_id, text)` | 4096 chars | Truncate at 4096 with "...(截断)" suffix |
| **Lark** | `LarkClient.send_text(chat_id, text)` | ~4000 chars | Use card format for long messages |
| **Discord** | `DiscordBotClient.send_dm(int(chat_id), content)` | 2000 chars | Split into 1900-char chunks |
| **Slack** | `SlackClient.post_message(channel, text)` | ~40,000 chars | No splitting needed in practice |

**@mention**: New platform adapters do NOT need to send `@mention` for the mentioned_user_ids in the first release. The pipeline sets `mentioned_user_ids` but adapters may ignore it if the platform doesn't support it or it's not critical to the MVP.

---

## Adapter Registry (In-Memory)

No database table. The registry is a module-level dict in `forward_service/channel/registry.py`:

```python
_adapters: dict[str, ChannelAdapter] = {
    "wecom": WeComAdapter(),    # existing
    "telegram": TelegramAdapter(),  # new
    "lark": LarkAdapter(),          # new
    "discord": DiscordAdapter(),    # new
    "slack": SlackAdapter(),        # new
}
```

Registration happens in `app.py`'s `lifespan()` at service startup.
