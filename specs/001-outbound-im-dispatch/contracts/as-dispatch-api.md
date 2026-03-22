# API Contract: as-dispatch — Outbound IM Send

**Base URL**: `http://<as-dispatch-host>:<port>`
**Auth**: Bearer JWT (`require_enterprise_jwt`)

---

## POST /api/im/send

Proactively send a message to an IM channel with routing context.

### Request

```http
POST /api/im/send HTTP/1.1
Content-Type: application/json
Authorization: Bearer <jwt_token>
```

```json
{
  "message_content": "这是一条需要转发到企微群的 AI 消息内容...",
  "bot_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "chat_id": "wrkSFfxxxxxx",
  "session_id": "sess_abc123def456",
  "agent_id": "agent-001",
  "project_name": "MyProject",
  "msg_type": "text"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| message_content | string | Yes | — | 消息正文（将自动添加路由头） |
| bot_key | string | Yes | — | 企微 Bot Webhook Key |
| chat_id | string | Yes | — | 目标群/会话 ID |
| session_id | string | Yes | — | AgentStudio 会话 ID |
| agent_id | string | No | null | Agent ID |
| project_name | string | No | null | 项目名称（显示在路由头中） |
| msg_type | string | No | "text" | 消息格式: text / markdown |

### Response — Success (200)

```json
{
  "success": true,
  "short_id": "ob_a1b2c3",
  "message_with_header": "[#ob_a1b2c3 MyProject]\n\n这是一条需要转发到企微群的 AI 消息内容..."
}
```

### Response — Send failure (200, success=false)

```json
{
  "success": false,
  "error": "fly-pigeon 发送失败: errcode=40001, errmsg=invalid bot_key"
}
```

### Response — Validation error (422)

Standard FastAPI validation error for missing required fields.

### Behavior

1. Validate `bot_key` exists in chatbots table (optional — can skip for flexibility)
2. Generate `outbound_short_id`: `ob_` + `secrets.token_hex(3)` → e.g. `ob_a1b2c3`
3. Prepend routing header to message: `[#ob_a1b2c3 MyProject]\n\n<original_content>`
4. Send via `send_to_wecom()` (fly-pigeon) with `bot_key` and `chat_id`
5. On send success: save `OutboundMessageContext` with:
   - `message_id` = `ob_a1b2c3`
   - `session_id`, `agent_id`, `bot_key`, `chat_id`
   - `content_preview` = first 200 chars
   - `expires_at` = now + 7 days
6. Return `{ success: true, short_id: "ob_a1b2c3" }`
7. On send failure: do NOT persist context; return error

---

## GET /api/outbound-context/{message_id} (existing)

Query outbound context by message_id (outbound_short_id).

No changes required. Already implemented.

---

## POST /api/outbound-context (existing)

Create outbound context manually.

No changes required. Already implemented.
