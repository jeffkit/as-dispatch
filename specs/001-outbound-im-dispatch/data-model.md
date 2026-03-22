# Data Model: Outbound IM Dispatch

**Feature**: 001-outbound-im-dispatch
**Date**: 2026-03-22

---

## Entity 1: OutboundMessageContext (existing — reused)

**Table**: `outbound_message_contexts`
**Status**: Already exists, no schema changes required.

| Field | Type | Nullable | Default | Description |
|-------|------|----------|---------|-------------|
| id | int (PK) | No | auto | 主键 |
| message_id | varchar(100) | No | — | 消息标识；outbound dispatch 场景存储 `ob_xxxxxx` 格式的 outbound_short_id |
| task_id | varchar(50) | Yes | null | 关联任务 ID（P2 scheduled task 场景使用） |
| agent_id | varchar(100) | Yes | null | 发送消息的 Agent ID |
| session_id | varchar(100) | Yes | null | AgentStudio 会话 ID（回复注入目标） |
| bot_key | varchar(100) | No | — | 发送使用的 Bot Key |
| chat_id | varchar(200) | No | — | 目标群/会话 ID |
| content_preview | varchar(200) | Yes | null | 消息预览（截断到 200 字符） |
| status | varchar(20) | No | 'pending' | pending → replied / expired |
| created_at | datetime | No | now(utc) | 创建时间 |
| replied_at | datetime | Yes | null | 回复时间 |
| expires_at | datetime | No | now + 7 days | 过期时间 |

**Indexes**:
- `idx_outbound_ctx_message_id` on `message_id`
- `idx_outbound_ctx_status` on `status`
- `idx_outbound_ctx_expires_at` on `expires_at`

**Usage in outbound dispatch**:
- `message_id` 存储 `ob_xxxxxx` 格式的 outbound_short_id
- `expires_at` 默认值需要在代码中调整为 7 天（当前硬编码为 24 小时）
- 查找方法 `find_context_by_message_id()` 直接复用

**State transitions**:
```
pending → replied    (用户引用回复并成功注入 AgentStudio)
pending → expired    (超过 expires_at 未收到回复，由 cleanup job 处理)
```

---

## Entity 2: DispatchRequest (API request model, not persisted)

**Type**: Pydantic BaseModel (request body for `POST /api/im/send`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| message_content | str | Yes | 要发送到 IM 的消息内容 |
| bot_key | str | Yes | 使用的企微 Bot Key |
| chat_id | str | Yes | 目标群/会话 ID |
| session_id | str | Yes | AgentStudio 会话 ID（用于回复路由） |
| agent_id | str | No | Agent ID |
| project_name | str | No | 项目名称（显示在消息头部） |
| msg_type | str | No | 消息格式，默认 'text' |

---

## Entity 3: DispatchResult (API response model, not persisted)

**Type**: dict (response body for `POST /api/im/send`)

| Field | Type | Description |
|-------|------|-------------|
| success | bool | 是否发送成功 |
| short_id | str | 生成的 outbound_short_id（如 `ob_abc123`） |
| error | str | null | 错误信息 |

---

## Entity 4: AgentStudio DispatchIMRequest (API request model for AgentStudio proxy)

**Type**: TypeScript interface (request body for `POST /api/agui/dispatch-im`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| sessionId | string | Yes | AgentStudio 会话 ID |
| messageContent | string | Yes | 要转发的消息内容 |
| botKey | string | Yes | 企微 Bot Key |
| chatId | string | Yes | 目标群 ID |
| projectName | string | No | 项目名称 |
| agentId | string | No | Agent ID |

---

## Entity Relationships

```
AgentStudio Frontend
       │
       │ POST /api/agui/dispatch-im
       ▼
AgentStudio Backend ──── JWT ────► as-dispatch POST /api/im/send
                                         │
                                         ├── 1. Generate ob_xxxxxx
                                         ├── 2. Prepend [#ob_xxxxxx project] header
                                         ├── 3. Send via fly-pigeon
                                         └── 4. Save OutboundMessageContext
                                                  │
                                                  │ (later, when user replies)
                                                  ▼
                                    WeChat Work callback
                                         │
                                         ├── Parse quoted text for [#ob_xxxxxx]
                                         ├── Find OutboundMessageContext
                                         └── Inject reply via AgentStudio /inject
```

---

## Validation Rules

### OutboundMessageContext (on create via /api/im/send)
- `message_content` must be non-empty string
- `bot_key` must correspond to an active bot in the chatbots table
- `chat_id` must be non-empty string
- `session_id` must be non-empty string
- `outbound_short_id` is generated server-side (not user-provided)

### Short ID Generation
- Format: `ob_` + 6 hex chars = 8 chars total
- Generated via `secrets.token_hex(3)` → `ob_{hex}`
- Uniqueness checked against existing pending OutboundMessageContext records
- Collision probability: ~1 in 16M for 6 hex chars, acceptable for 7-day window
