# Quickstart: Multi-Platform IM ChannelAdapter Unification

**Date**: 2026-03-02  
**Branch**: `feature/im-integration`

---

## Prerequisites

```bash
cd platform/as-dispatch/.worktrees/intelligent-bot
uv sync              # install all Python dependencies
cp .env.example .env # configure credentials
alembic upgrade head # apply any pending DB migrations (none for this feature)
```

---

## Running the Service

```bash
uv run python -m forward_service.app
# Service starts on port 8083 (default)
```

On startup you should see:
```
  通道适配器已注册: wecom
  通道适配器已注册: telegram
  通道适配器已注册: lark
  通道适配器已注册: discord
  通道适配器已注册: slack
  🚀 启动 Discord Bot 任务: <bot_key>...  (if Discord bots configured)
```

---

## Platform Configuration

### Telegram

1. Get a Bot Token from `@BotFather`.
2. Register the bot in the service database (via the admin API or config file), setting `platform = "telegram"` and `platform_config.bot_token`.
3. Register the webhook — **critical**: set `secret_token` to your `bot_key`:
   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://your-server.com/callback/telegram",
       "secret_token": "<YOUR_BOT_KEY>"
     }'
   ```
4. Send a message to the bot on Telegram. Check service logs for `[telegram] 收到消息`.

### Lark (飞书)

1. Create a Lark app at `open.feishu.cn`, note `app_id` and `app_secret`.
2. Register bot in service with `platform = "lark"`, `platform_config.app_id`, `platform_config.app_secret`, and optionally `platform_config.encrypt_key`.
3. Configure the Lark app's Event Subscription URL to: `https://your-server.com/callback/lark`.
4. On first save, Lark sends a URL verification challenge — the service responds automatically.
5. Send a message in a Lark group where the bot is a member.

### Discord

Discord uses WebSocket (not HTTP webhook). No `/callback/discord` URL configuration is needed for the bot.

1. Create a Discord application at `discord.com/developers`, create a bot user, copy the bot token.
2. Register bot in service with `platform = "discord"`, `platform_config.bot_token`.
3. On service startup, the bot connects to Discord's gateway automatically.
4. Send a DM to the bot from a Discord user.

### Slack

1. Create a Slack app at `api.slack.com/apps`, enable Event Subscriptions.
2. Set Request URL to: `https://your-server.com/callback/slack`.
3. Slack sends a URL verification challenge — the service responds automatically.
4. Subscribe to `message.channels` and/or `message.im` events.
5. Note the `App ID` — this is used as `bot_key`. Register bot in service with `platform = "slack"`, `platform_config.bot_token`.
6. Invite the bot to a Slack channel and send a message.

---

## Testing: Unit Tests

Run all new adapter unit tests:
```bash
uv run pytest tests/unit/test_channel_telegram.py -v
uv run pytest tests/unit/test_channel_lark.py -v
uv run pytest tests/unit/test_channel_discord.py -v
uv run pytest tests/unit/test_channel_slack.py -v
```

Run existing tests to verify no regression:
```bash
uv run pytest tests/ -v
```

### Test File Locations

Per Principle 8, test files follow the naming convention:
```
tests/unit/
├── test_channel_telegram.py    # TelegramAdapter tests
├── test_channel_lark.py        # LarkAdapter tests
├── test_channel_discord.py     # DiscordAdapter tests
└── test_channel_slack.py       # SlackAdapter tests
```

### Example: Telegram parse_inbound() Test

```python
import pytest
from forward_service.channel.telegram import TelegramAdapter

@pytest.fixture
def adapter():
    return TelegramAdapter()

def test_parse_inbound_text_message(adapter):
    raw = {
        "update_id": 123,
        "message": {
            "message_id": 42,
            "from": {"id": 111, "is_bot": False, "first_name": "Alice"},
            "chat": {"id": 111, "type": "private"},
            "text": "Hello!"
        },
        "_request_headers": {"x-telegram-bot-api-secret-token": "my-bot-key"}
    }
    # Note: parse_inbound is async
    import asyncio
    inbound = asyncio.run(adapter.parse_inbound(raw))
    assert inbound.platform == "telegram"
    assert inbound.bot_key == "my-bot-key"
    assert inbound.text == "Hello!"
    assert inbound.chat_type == "direct"
    assert inbound.images == []

def test_should_ignore_bot_message(adapter):
    raw = {
        "message": {
            "from": {"is_bot": True},
            "text": "I am a bot"
        }
    }
    assert adapter.should_ignore(raw) is True

def test_should_ignore_regular_message(adapter):
    raw = {
        "message": {
            "from": {"is_bot": False},
            "text": "Hello"
        }
    }
    assert adapter.should_ignore(raw) is False
```

### Example: Lark URL Verification Test

```python
from forward_service.channel.lark import LarkAdapter

def test_get_verification_response_for_challenge():
    adapter = LarkAdapter()
    raw = {
        "challenge": "ajls384kdjx98XX",
        "token": "xxxxxx",
        "type": "url_verification"
    }
    response = adapter.get_verification_response(raw)
    assert response == {"challenge": "ajls384kdjx98XX"}

def test_get_verification_response_returns_none_for_normal_event():
    adapter = LarkAdapter()
    raw = {"schema": "2.0", "header": {}, "event": {}}
    assert adapter.get_verification_response(raw) is None
```

### Example: Slack Retry Header Test

```python
from forward_service.channel.slack import SlackAdapter

def test_should_ignore_retry():
    adapter = SlackAdapter()
    raw = {
        "type": "event_callback",
        "event": {"type": "message", "text": "Hello"},
        "_request_headers": {"x-slack-retry-num": "1"}
    }
    assert adapter.should_ignore(raw) is True

def test_should_ignore_bot_message():
    adapter = SlackAdapter()
    raw = {
        "event": {"type": "message", "bot_id": "B12345"},
        "_request_headers": {}
    }
    assert adapter.should_ignore(raw) is True
```

### Example: send_outbound() with Mocked Client

```python
from unittest.mock import AsyncMock, patch
from forward_service.channel.telegram import TelegramAdapter
from forward_service.channel.base import OutboundMessage

@pytest.mark.asyncio
async def test_send_outbound_success():
    adapter = TelegramAdapter()
    msg = OutboundMessage(
        chat_id="111222333",
        text="Hello from bot!",
        bot_key="my-bot-key"
    )

    with patch("forward_service.channel.telegram.TelegramClient") as MockClient:
        mock_instance = AsyncMock()
        MockClient.return_value = mock_instance
        mock_instance.send_message.return_value = {"ok": True}

        # Mock config to return bot with platform_config
        with patch("forward_service.channel.telegram.config") as mock_config:
            mock_bot = Mock()
            mock_bot.get_platform_config.return_value = {"bot_token": "TOKEN"}
            mock_config.get_bot.return_value = mock_bot

            result = await adapter.send_outbound(msg)

    assert result.success is True
    assert result.parts_sent == 1
```

---

## Integration Scenario: All 5 Platforms

Test that a message from each platform goes through the unified pipeline:

```bash
# 1. Verify all adapters registered at startup
curl http://localhost:8083/health
# Should show: "bots_count": N

# 2. Simulate a Telegram webhook
curl -X POST http://localhost:8083/callback/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: my-bot-key" \
  -d '{
    "update_id": 1,
    "message": {
      "message_id": 1,
      "from": {"id": 123, "is_bot": false, "first_name": "Test"},
      "chat": {"id": 123, "type": "private"},
      "text": "/ping"
    }
  }'

# 3. Simulate a Lark URL verification
curl -X POST http://localhost:8083/callback/lark \
  -H "Content-Type: application/json" \
  -d '{"challenge": "test-challenge", "token": "xxx", "type": "url_verification"}'
# Expected: {"challenge": "test-challenge"}

# 4. Simulate a Slack URL verification
curl -X POST http://localhost:8083/callback/slack \
  -H "Content-Type: application/json" \
  -d '{"token": "xxx", "challenge": "test-challenge", "type": "url_verification"}'
# Expected: {"challenge": "test-challenge"}

# 5. Simulate a Slack message with retry header (should be ignored)
curl -X POST http://localhost:8083/callback/slack \
  -H "Content-Type: application/json" \
  -H "X-Slack-Retry-Num: 1" \
  -d '{"type": "event_callback", "api_app_id": "A123", "event": {"type": "message", "user": "U1", "channel": "C1", "text": "Hello"}}'
# Expected: {"errcode": 0, "errmsg": "ok"} (silently ignored)

# 6. Test unregistered platform error
curl -X POST http://localhost:8083/callback/whatsapp \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: {"errcode": 400, "errmsg": "Unsupported platform: whatsapp. Registered: [wecom, telegram, lark, discord, slack]"}
```

---

## Backward Compatibility Verification

After deployment, verify that existing WeChat processing continues to work:

```bash
# Test existing WeChat callback still works
curl -X POST http://localhost:8083/callback/wecom \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=my-wecom-key",
    "msgtype": "text",
    "text": {"content": "test"},
    "from": {"userid": "user1", "name": "Test User"},
    "chatid": "chat1",
    "chattype": "group",
    "msgid": "msg001"
  }'

# Also verify the old /callback route (WeChat legacy) still works
curl -X POST http://localhost:8083/callback \
  -H "Content-Type: application/json" \
  -d '{ ... same payload ... }'
```

Both should return `{"errcode": 0, "errmsg": "ok"}` or appropriate processing response.
