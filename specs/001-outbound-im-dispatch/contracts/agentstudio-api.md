# API Contract: AgentStudio — Dispatch IM Proxy

**Base URL**: `http://<agentstudio-host>:<port>`
**Auth**: None (internal backend route, accessed from frontend)

---

## POST /api/agui/dispatch-im

Proxy endpoint for the frontend to dispatch a message to an IM channel via as-dispatch.

### Request

```http
POST /api/agui/dispatch-im HTTP/1.1
Content-Type: application/json
```

```json
{
  "sessionId": "sess_abc123def456",
  "messageContent": "这是 AI 生成的回复内容...",
  "botKey": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "chatId": "wrkSFfxxxxxx",
  "projectName": "MyProject",
  "agentId": "agent-001"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| sessionId | string | Yes | AgentStudio 会话 ID |
| messageContent | string | Yes | 要转发的消息内容 |
| botKey | string | Yes | 企微 Bot Webhook Key |
| chatId | string | Yes | 目标群/会话 ID |
| projectName | string | No | 项目名称 |
| agentId | string | No | Agent ID |

### Response — Success (200)

```json
{
  "success": true,
  "shortId": "ob_a1b2c3"
}
```

### Response — as-dispatch error (200, success=false)

```json
{
  "success": false,
  "error": "dispatch failed: invalid bot_key"
}
```

### Response — Server error (500)

```json
{
  "error": "Failed to dispatch message to IM"
}
```

### Behavior

1. Receive request from frontend
2. Construct JWT token using shared `JWT_SECRET_KEY`
3. Call `POST <as-dispatch-url>/api/im/send` with:
   - `message_content` = body.messageContent
   - `bot_key` = body.botKey
   - `chat_id` = body.chatId
   - `session_id` = body.sessionId
   - `agent_id` = body.agentId
   - `project_name` = body.projectName
4. Forward as-dispatch response to frontend
5. On network error: return `{ success: false, error: "..." }`

### Configuration

AgentStudio backend needs the following environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| AS_DISPATCH_URL | as-dispatch service base URL | `http://localhost:8083` |
| JWT_SECRET_KEY | Shared JWT secret with as-dispatch | `your-secret-key` |

---

## POST /api/agui/sessions/:sessionId/inject (existing)

Inject a message into an active AgentStudio session.

Used by as-dispatch callback handler to inject IM replies back into the Agent conversation.

### Request

```http
POST /api/agui/sessions/{sessionId}/inject HTTP/1.1
Content-Type: application/json
```

```json
{
  "message": "用户在企微群中回复的内容",
  "sender": "wecom-reply",
  "workspace": "MyProject"
}
```

### Response — Success (200)

```json
{
  "success": true,
  "sessionId": "sess_abc123def456",
  "events": [...]
}
```

No changes required. Already implemented.
