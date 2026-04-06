# Quickstart: 个人微信通道接入 (Weixin Channel)

**Date**: 2026-03-22
**Plan**: `specs/001-weixin-channel/plan.md`

---

## Prerequisites

1. **as-dispatch service** running locally or in dev environment
2. **Personal WeChat account** (for QR scanning)
3. **Database** initialized with existing as-dispatch schema (SQLite for dev)

## Setup

### 1. Start as-dispatch

```bash
cd platform/as-dispatch/.worktrees/weixin
USE_DATABASE=true uv run python -m forward_service.app
```

The service starts on port 8083 (default). You should see in the logs:

```
通道适配器已注册: wecom, telegram, lark, discord, slack, qqbot, weixin
```

### 2. Create a Weixin Bot Record

Use the existing Bot management API to create a new bot with `platform = "weixin"`:

```bash
# Via the admin API (adjust bot_key and name as needed)
curl -X POST http://localhost:8083/bots \
  -H "Content-Type: application/json" \
  -d '{
    "bot_key": "wx_test_001",
    "name": "测试微信 Bot",
    "platform": "weixin",
    "enabled": true
  }'
```

### 3. QR Code Login

**Step 1**: Trigger QR code generation

```bash
curl -X POST http://localhost:8083/admin/weixin/wx_test_001/qr-login
```

Response:
```json
{
  "success": true,
  "bot_key": "wx_test_001",
  "qrcode": "qr_abc123",
  "qrcode_url": "https://ilinkai.weixin.qq.com/qrcode/qr_abc123.png"
}
```

**Step 2**: Open the `qrcode_url` in a browser and scan it with your WeChat mobile app.

**Step 3**: Poll login status until `confirmed`:

```bash
# Poll every 3 seconds
curl http://localhost:8083/admin/weixin/wx_test_001/qr-status
```

Wait for:
```json
{
  "success": true,
  "status": "confirmed",
  "message": "登录成功！可以使用 POST /{bot_key}/start 启动消息接收"
}
```

### 4. Start the Bot

```bash
curl -X POST http://localhost:8083/admin/weixin/wx_test_001/start
```

Response:
```json
{
  "success": true,
  "status": "running",
  "message": "微信 Bot 已启动，正在接收消息"
}
```

### 5. Send a Test Message

From another WeChat account, send a text message to the bot's personal WeChat account. You should see in the as-dispatch logs:

```
[weixin] 收到消息: sender=用户昵称, content=你好...
[weixin] 收到消息: chat_id=direct:wxid_xxx, chat_type=direct, from=用户昵称
```

The message enters the unified pipeline and is forwarded to the configured AI agent.

## Verification Checklist

### QR Login (User Story 1)

- [ ] `POST /admin/weixin/{bot_key}/qr-login` returns QR code URL within 5s
- [ ] `GET /admin/weixin/{bot_key}/qr-status` cycles through `wait` → `scaned` → `confirmed`
- [ ] On `confirmed`, credentials are persisted to `platform_config`
- [ ] QR auto-refreshes up to 3 times on expiry

### Messaging (User Story 2)

- [ ] Text message from WeChat user is received by as-dispatch
- [ ] Message is parsed into InboundMessage and enters pipeline
- [ ] AI agent reply is sent back to the user's WeChat
- [ ] Non-text messages receive friendly placeholder reply
- [ ] Typing indicator is shown before reply

### Lifecycle (User Story 3)

- [ ] `POST /admin/weixin/{bot_key}/start` starts the long-poll loop
- [ ] `POST /admin/weixin/{bot_key}/stop` stops the loop gracefully
- [ ] `GET /admin/weixin/{bot_key}/status` returns current state
- [ ] Stopping and restarting resumes from persisted `get_updates_buf`

### Recovery (User Story 4)

- [ ] Transient network errors trigger exponential backoff
- [ ] `errcode=-14` triggers 1-hour pause then retry
- [ ] Service restart resumes polling from persisted cursor

### Multi-Account (User Story 5)

- [ ] Two bots can run simultaneously without interference
- [ ] `GET /admin/weixin/list` shows all bots with individual status

## Common Commands

```bash
# Check bot status
curl http://localhost:8083/admin/weixin/wx_test_001/status

# List all weixin bots
curl http://localhost:8083/admin/weixin/list

# Stop a bot
curl -X POST http://localhost:8083/admin/weixin/wx_test_001/stop

# Restart a bot
curl -X POST http://localhost:8083/admin/weixin/wx_test_001/start
```

## Running Unit Tests

```bash
cd platform/as-dispatch/.worktrees/weixin
uv run pytest tests/unit/test_channel_weixin.py -v
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| QR login returns error | iLinkAI service unreachable | Check network, verify `https://ilinkai.weixin.qq.com` is accessible |
| Bot starts but no messages | `get_updates_buf` stale | Stop bot, clear `get_updates_buf` in platform_config, restart |
| Session expired after 1 hour pause | Normal session expiry | Re-trigger QR login: `POST /admin/weixin/{bot_key}/qr-login` |
| Reply not sent | Missing `context_token` | Check logs for `context_token` cache miss; send another message to repopulate |
| Multiple bots interfere | Same `bot_key` used | Ensure each WeChat account uses a unique `bot_key` |
