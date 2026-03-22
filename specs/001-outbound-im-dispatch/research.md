# Research: Outbound IM Dispatch

**Feature**: 001-outbound-im-dispatch
**Date**: 2026-03-22

---

## Decision 1: Outbound short_id 命名空间隔离

**问题**: OutboundMessageContext 的 `message_id`（作为 short_id）需要与 HITL-MCP 的 UserSession `short_id` 区分，避免回调路由时产生冲突。

**决策**: 使用 `ob_` 前缀 + 6 位十六进制随机字符（共 8 字符）作为 outbound_short_id，格式为 `ob_xxxxxx`。

**Rationale**:
- 现有 UserSession.short_id 是 session_id 的前 8 位十六进制（无前缀），格式为 `[a-f0-9]{8}`
- 加 `ob_` 前缀后，正则 `SHORT_ID_PATTERN` 仍能匹配 `[#ob_abc123 MyProject]`，因为 pattern 是 `[a-f0-9]{6,8}`，但 `ob_` 包含下划线和非 hex 字符
- 因此需要扩展 `SHORT_ID_PATTERN` 为同时支持 `ob_` 前缀的格式
- 回调路由时：先尝试 outbound context 匹配（`ob_` 前缀），再 fallback 到 HITL session 匹配

**Alternatives considered**:
- 使用不同长度区分（如 outbound 用 10 位）：不够直观，长度差异不明确
- 使用完全分离的标记格式（如 `[!short_id]`）：需要改动更多解析逻辑
- 使用 UUID：太长，企微消息显示不友好

**Trade-offs**:
- (+) 前缀区分简单可靠，一眼可辨
- (+) 8 字符总长度与现有 short_id 一致，视觉一致
- (-) 需要更新 `SHORT_ID_PATTERN` 正则以支持 `ob_` 前缀

---

## Decision 2: 企微 Webhook 不返回 msgid 的应对方案

**问题**: fly-pigeon 调用企微 Webhook API 发送消息后，API 响应中不包含所发消息的 `msgid`。因此无法通过企微原生的 `quoted_msgid` 字段匹配回复。

**决策**: 完全依赖应用层 `[#short_id project_name]` 头部嵌入消息内容，从引用的文本中解析 short_id 进行路由。

**Rationale**:
- 企微 Webhook（fly-pigeon）的 `bot.text()` 返回的 response 只包含 `errcode` 和 `errmsg`，不包含 `msgid`
- 已有的 HITL-MCP 模式也使用这种 text-based 路由，已验证可行
- 企微引用回复格式稳定：`"引用内容"\n------\n@bot 回复内容`，解析可靠

**Alternatives considered**:
- 使用企微应用消息 API（非 Webhook）获取 msgid：需要企业管理员授权，权限门槛高
- 在发送后立即查询消息列表获取 msgid：企微不提供此 API

**Trade-offs**:
- (+) 无需额外 API 权限，与现有 HITL 模式完全一致
- (-) 依赖用户"引用回复"操作，直接回复（非引用）无法匹配
- (-) 引用文本被企微截断时可能丢失 short_id（长消息场景）

---

## Decision 3: POST /api/im/send 端点设计

**问题**: 需要设计一个统一的出站消息发送 API，支持 AgentStudio Web UI 和 scheduled task 两种调用方。

**决策**: 在 as-dispatch 新增 `POST /api/im/send` 端点，使用 JWT 鉴权。

**Rationale**:
- 复用现有 `require_enterprise_jwt` 鉴权，与 `/api/outbound-context`、`/api/bots` 一致
- 端点职责：接收消息内容 + 目标配置 → 生成 outbound_short_id → 注入路由头 → 调用 fly-pigeon 发送 → 保存 OutboundMessageContext → 返回 short_id
- AgentStudio 通过其 backend 代理调用此端点（不从前端直接调用），保持 JWT 密钥安全

**Alternatives considered**:
- 直接在 AgentStudio backend 调用 fly-pigeon：违反关注点分离，fly-pigeon 是 Python 库
- 在 `/api/outbound-context` 中合并发送逻辑：语义不清，context 是存储 API，send 是动作 API

**Trade-offs**:
- (+) 单一入口，统一路由头生成和 context 保存
- (+) 与现有 auth 体系一致
- (-) AgentStudio → as-dispatch 多一跳网络调用

---

## Decision 4: 回调路由优先级

**问题**: 回调消息可能同时匹配 outbound context（通过 `ob_` 前缀 short_id）和 HITL session（通过普通 short_id）。需要明确路由优先级。

**决策**: 路由优先级：outbound_short_id（`ob_` 前缀） > quoted_message_id（原始 msgid，已有逻辑） > HITL quoted_short_id > active session。

**Rationale**:
- outbound dispatch 是明确的用户意图（引用了带 `[#ob_xxx]` 标识的消息），应优先
- 如果 short_id 没有 `ob_` 前缀，则走现有 HITL 路由逻辑
- 不修改现有的 `quoted_message_id` 逻辑，保持向后兼容

**Alternatives considered**:
- 统一所有路由到一个查找函数：重构范围太大，违反 P9 最小变更
- Outbound context 和 HITL session 使用相同 table：语义不同，不应合并

**Trade-offs**:
- (+) 完全向后兼容，不影响现有 HITL 流程
- (+) 前缀区分使路由逻辑简单明确
- (-) callback.py 需要增加一段 outbound short_id 解析逻辑

---

## Decision 5: AgentStudio 端 API 设计

**问题**: 前端需要通过 AgentStudio backend 调用 as-dispatch 发送消息，而非直接调用 as-dispatch（JWT 密钥不能暴露给前端）。

**决策**: AgentStudio backend 新增 `POST /api/agui/dispatch-im` 代理端点。

**Rationale**:
- 前端调用 AgentStudio backend → backend 使用 JWT 调用 as-dispatch `/api/im/send`
- 端点接收 `{ sessionId, messageContent, botKey, chatId, projectName }` 
- 返回 `{ success, shortId, error }` 给前端
- 前端根据返回更新 UI 状态（成功/失败/已转发）

**Alternatives considered**:
- 前端直接调用 as-dispatch：需要暴露 JWT，安全风险
- 使用 WebSocket 推送结果：增加复杂度，HTTP 请求-响应足够

**Trade-offs**:
- (+) 安全，JWT 密钥仅在 backend 之间传递
- (+) 前端接口简单，无需知道 as-dispatch 地址
- (-) 多一层代理

---

## Decision 6: 前端 UI 交互模式

**问题**: 如何在 AI 消息气泡上添加"转发到企微"功能？

**决策**: 在 AI 消息气泡上添加一个 icon button（转发图标），点击后弹出确认弹窗（显示目标群信息），确认后调用 dispatch-im API。

**Rationale**:
- 单次点击 + 确认弹窗，避免误操作
- 弹窗中展示：目标群名/chat_id、消息预览
- 消息气泡上新增 forwarded 状态标识（如小图标 + tooltip）
- 状态管理：消息级别的 `dispatchStatus: 'idle' | 'sending' | 'sent' | 'error'`

**Alternatives considered**:
- 右键菜单中添加选项：发现性差
- 消息底部操作栏：占用空间

**Trade-offs**:
- (+) 操作直觉，UI 反馈明确
- (+) 确认弹窗防止误发
- (-) 需要在消息组件中新增状态管理

---

## Decision 7: 回复注入目标端点

**问题**: 当 as-dispatch 回调匹配到 outbound context 后，如何将回复注入 AgentStudio 会话？

**决策**: 调用 AgentStudio 的 `POST /api/agui/sessions/:sessionId/inject` 端点。

**Rationale**:
- 该端点已存在且功能完整：接收 `{ message, sender, workspace }` 参数
- 会广播 USER_MESSAGE 事件给所有 session observers
- 会调用 AI engine 处理消息并返回结果
- as-dispatch 拿到 outbound context 中的 `session_id` 后直接调用

**Alternatives considered**:
- 新建专用的 reply-injection 端点：重复功能
- 通过 WebSocket 推送：inject 端点已封装好

**Trade-offs**:
- (+) 复用已有端点，零新开发
- (+) 完整的消息处理管线（AI 会继续对话）
- (-) 需要 as-dispatch 知道 AgentStudio 的地址（通过 bot 配置中的 target_url 可获取）

---

## Decision 8: OutboundMessageContext 模型扩展

**问题**: 现有 `OutboundMessageContext` 模型的 `message_id` 字段用于存储企微 msgid，但在 outbound dispatch 场景中企微不返回 msgid。需要用 outbound_short_id 替代。

**决策**: 复用现有 `message_id` 字段存储 `outbound_short_id`（`ob_xxxxxx` 格式），不新增字段。

**Rationale**:
- `message_id` 语义上就是"消息标识"，outbound_short_id 就是消息的应用层标识
- 现有的 `find_context_by_message_id()` 方法可直接复用
- 已有索引 `idx_outbound_ctx_message_id` 直接生效
- 默认过期时间需要从 24 小时改为 7 天（与 spec 一致）

**Alternatives considered**:
- 新增 `outbound_short_id` 字段：增加 schema migration，且 `message_id` 字段会冗余
- 创建新表：context 语义相同，不必分表

**Trade-offs**:
- (+) 零 schema 变更，零 migration
- (+) 复用已有查询方法和索引
- (-) `message_id` 字段名在 outbound dispatch 场景下语义略有偏差，但文档可解释
