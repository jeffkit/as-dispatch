# API Contract: Weixin Bot Admin API

**Base Path**: `/admin/weixin`
**Tags**: `weixin-admin`
**Date**: 2026-03-22

---

## 1. Trigger QR Code Login

Initiates the QR code login flow for a WeChat bot account. Returns a QR code image URL for the admin to scan with their WeChat mobile app.

### Request

```
POST /admin/weixin/{bot_key}/qr-login
```

**Path Parameters**:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `bot_key` | `str` | Yes | Bot identifier in as-dispatch |

### Response — Success (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "qrcode": "qr_abc123",
  "qrcode_url": "https://ilinkai.weixin.qq.com/qrcode/qr_abc123.png",
  "message": "请使用微信扫描二维码完成登录"
}
```

### Response — Error (200)

```json
{
  "success": false,
  "error": "Bot 'wx_bot_001' 不存在"
}
```

**Error cases**:
- Bot does not exist: `"Bot '{bot_key}' 不存在"`
- Bot is not weixin platform: `"Bot '{bot_key}' 不是微信平台"`
- iLinkAI API failure: `"获取二维码失败: {error_detail}"`

---

## 2. Poll QR Code Login Status

Polls the current status of a QR code login attempt. The admin should call this endpoint repeatedly (e.g., every 2-3 seconds) until the status is `confirmed` or the attempt fails.

### Request

```
GET /admin/weixin/{bot_key}/qr-status
```

**Path Parameters**:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `bot_key` | `str` | Yes | Bot identifier |

### Response — Waiting (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "status": "wait",
  "qrcode_url": "https://ilinkai.weixin.qq.com/qrcode/qr_abc123.png",
  "refresh_count": 0,
  "message": "等待扫码..."
}
```

### Response — Scanned (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "status": "scaned",
  "message": "已扫码，请在手机上确认"
}
```

### Response — Confirmed (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "status": "confirmed",
  "ilink_bot_id": "bot_123456",
  "message": "登录成功！可以使用 POST /{bot_key}/start 启动消息接收"
}
```

### Response — Expired & Auto-Refreshed (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "status": "wait",
  "qrcode_url": "https://ilinkai.weixin.qq.com/qrcode/qr_new456.png",
  "refresh_count": 1,
  "message": "二维码已过期，已自动刷新（第 1/3 次）"
}
```

### Response — Failed (200)

```json
{
  "success": false,
  "bot_key": "wx_bot_001",
  "status": "expired",
  "error": "二维码已过期且自动刷新次数已达上限（3 次），请重新触发登录"
}
```

### Response — No Active Login (200)

```json
{
  "success": false,
  "error": "没有进行中的登录流程，请先调用 POST /{bot_key}/qr-login"
}
```

**Status values**: `wait` | `scaned` | `confirmed` | `expired`

---

## 3. Start Bot

Starts the long-polling loop for a logged-in WeChat bot. The bot must have valid credentials from a previous QR login.

### Request

```
POST /admin/weixin/{bot_key}/start
```

**Path Parameters**:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `bot_key` | `str` | Yes | Bot identifier |

### Response — Success (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "status": "running",
  "ilink_bot_id": "bot_123456",
  "message": "微信 Bot 已启动，正在接收消息"
}
```

### Response — Error (200)

```json
{
  "success": false,
  "error": "Bot 'wx_bot_001' 未登录，请先完成二维码登录"
}
```

**Error cases**:
- Bot not found: `"Bot '{bot_key}' 不存在"`
- Not weixin platform: `"Bot '{bot_key}' 不是微信平台"`
- No credentials: `"Bot '{bot_key}' 未登录，请先完成二维码登录"`
- Already running: stops and restarts (idempotent)

---

## 4. Stop Bot

Stops the long-polling loop for a running WeChat bot. Graceful shutdown — completes the current poll cycle and stops.

### Request

```
POST /admin/weixin/{bot_key}/stop
```

**Path Parameters**:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `bot_key` | `str` | Yes | Bot identifier |

### Response — Success (200)

```json
{
  "success": true,
  "bot_key": "wx_bot_001",
  "message": "微信 Bot 已停止"
}
```

### Response — Error (200)

```json
{
  "success": false,
  "error": "微信 Bot 'wx_bot_001' 未在运行"
}
```

---

## 5. Get Bot Status

Returns the current status of a WeChat bot instance.

### Request

```
GET /admin/weixin/{bot_key}/status
```

**Path Parameters**:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `bot_key` | `str` | Yes | Bot identifier |

### Response — Running (200)

```json
{
  "running": true,
  "bot_key": "wx_bot_001",
  "status": "running",
  "ilink_bot_id": "bot_123456",
  "consecutive_failures": 0,
  "last_poll_at": "2026-03-22T10:30:00Z",
  "active_users": 5
}
```

### Response — Not Running (200)

```json
{
  "running": false,
  "bot_key": "wx_bot_001",
  "status": "stopped"
}
```

**Status values**: `stopped` | `running` | `paused` | `expired` | `login_pending`

---

## 6. List All Weixin Bots

Returns the status of all registered WeChat bot instances.

### Request

```
GET /admin/weixin/list
```

### Response (200)

```json
{
  "bots": [
    {
      "bot_key": "wx_bot_001",
      "running": true,
      "status": "running",
      "ilink_bot_id": "bot_123456"
    },
    {
      "bot_key": "wx_bot_002",
      "running": false,
      "status": "expired",
      "ilink_bot_id": "bot_789012"
    }
  ],
  "total": 2,
  "running_count": 1
}
```

---

## Internal API: iLinkAI Protocol Endpoints

These are the iLinkAI protocol endpoints consumed by `WeixinClient`. Not exposed to admin — documented here for reference.

### Base URL
```
https://ilinkai.weixin.qq.com
```

### Common Headers
```
Authorization: Bearer <bot_token>
AuthorizationType: ilink_bot_token
X-WECHAT-UIN: <random_base64>
Content-Type: application/json
```

### Endpoints Used

| Method | Path | Purpose | Timeout |
|---|---|---|---|
| GET | `/ilink/bot/get_bot_qrcode?bot_type=3` | Generate QR code for login | 10s |
| GET | `/ilink/bot/get_qrcode_status?qrcode={qrcode}` | Poll QR login status | 10s |
| POST | `/ilink/bot/getupdates` | Long-poll for inbound messages | 40s (35s server + 5s buffer) |
| POST | `/ilink/bot/sendmessage` | Send outbound text message | 30s |
| POST | `/ilink/bot/getconfig` | Get typing_ticket for typing indicator | 10s |
| POST | `/ilink/bot/sendtyping` | Send typing indicator | 10s |

### Error Codes

| errcode | Meaning | Action |
|---|---|---|
| 0 | Success | Continue |
| -14 | Session expired | Pause 1 hour, then retry |
| Other negative | API error | Log + retry with backoff |
