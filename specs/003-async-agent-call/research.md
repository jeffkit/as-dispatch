# Research: Async Agent Call — Technical Decisions

**Feature**: 003-async-agent-call  
**Date**: 2026-03-26  
**Status**: Final

---

## 1. Problem Statement

当前 `callback.py` 的调用链是完全同步的：

```
WeChat callback → as-dispatch → forward_to_agent_with_user_project() → HTTP POST → wait → send_reply()
```

整个过程可能持续 1800 秒（当前 timeout 配置）。WeChat Work 要求回调方在 **3 秒内**返回 HTTP 200，否则触发重试，最终引发 504 Gateway Timeout。

---

## 2. Decision 1: Async Task Execution Approach

### 候选方案

| 方案 | 机制 | 优点 | 缺点 |
|------|------|------|------|
| A: 纯 in-memory asyncio.create_task | Python asyncio 任务 | 简单，无额外依赖 | 服务重启后任务丢失，违反 FR-006 |
| B: 数据库支撑 + asyncio 执行 | DB 记录任务状态，asyncio 执行 | 任务可持久化，支持重启恢复 | 需要 DB schema 变更 |
| C: 外部任务队列 (Celery/RQ) | 独立 worker 进程 | 工业级可靠性，横向扩展 | 引入新中间件（Redis/RabbitMQ），运维复杂度大幅提升 |

### 决策：方案 B（数据库支撑 + asyncio 执行）

**理由**：
- as-dispatch 已有完善的 SQLAlchemy + Alembic 基础设施（P4 合规）
- 无需引入 Redis/RabbitMQ 等新中间件
- asyncio 在 FastAPI 的 uvicorn event loop 上执行，与现有 async I/O 模型一致（P3 合规）
- DB 记录提供重启恢复能力（FR-006）
- 满足当前规模需求（单实例 as-dispatch）

**执行机制**：
```python
# 在 callback.py 中：
task_id = await async_task_service.submit_task(task_data)
asyncio.create_task(async_task_service.execute_task(task_id))
# 立即返回 WeChat 200
```

**重启恢复**：在 FastAPI `lifespan` 启动事件中，扫描 `PENDING`/`PROCESSING` 状态任务并重新调度。

---

## 3. Decision 2: SSE Stream Consumption Strategy

### 候选方案

| 方案 | 机制 | 优点 | 缺点 |
|------|------|------|------|
| A: 全量积累后发送 | 消费完整 SSE 流，组装结果，最后发送 | 简单，WeChat 消息完整 | 用户等待时间=完整处理时间 |
| B: 渐进式发送（每 chunk 一条微信消息） | 每个 SSE chunk 发送一条企微消息 | 用户实时感知进度 | WeChat API 频率限制，消息碎片化，用户体验差 |
| C: 定时聚合发送（每 N 秒聚合一次） | 缓冲区累积一段时间后发送中间更新 | 平衡实时性和完整性 | 实现复杂，需要"更新消息"API（企微不支持编辑已发消息） |

### 决策：方案 A（全量积累后发送）

**理由**：
- 企业微信**不支持编辑已发消息**，方案 B/C 会导致大量碎片消息
- 已有 P1 "正在处理" 确认消息解决用户等待反馈问题
- 与现有 `forward_to_agent_with_user_project()` 模型完全兼容——该函数已处理 HTTP 直连和隧道两种方式，返回完整的 `AgentResult`
- P11 (SSE Stream Handling) 合规：正确使用 `+=` 积累，在 `content_block_stop` 时解析

**对现有代码的影响**：
- 异步任务执行器直接调用现有的 `forward_to_agent_with_user_project()` 函数
- 该函数内部已处理隧道/直连两种路由，无需修改
- timeout 通过 `max_task_duration_seconds` 从任务配置读取（P9 合规）

---

## 4. Decision 3: Database Schema for Task State

### AsyncAgentTask 表设计原则

- **任务完整性**：任务创建时必须持久化所有执行所需信息（bot_key, chat_id, message, target_url 等）
- **状态机**：PENDING → PROCESSING → COMPLETED / FAILED / TIMEOUT
- **关联现有模型**：通过 `bot_key` 关联 `chatbots`，不使用外键约束（允许 Bot 删除后任务记录保留，便于审计）
- **扩展 Chatbot 模型**：新增 `async_mode`、`processing_message`、`sync_timeout_seconds`、`max_task_duration_seconds` 四个字段

### 不引入 StreamBuffer 实体的理由

spec.md 中提到 `StreamBuffer` 实体，但经过分析：
- 异步任务调用 `forward_to_agent_with_user_project()` 时，SSE 流在函数内部已被消费并返回完整文本
- 不需要跨函数调用传递流缓冲区
- `AsyncAgentTask.response_text` 字段足以存储结果

---

## 5. Decision 4: WeChat Reply Mechanism

### 候选方案

| 方案 | 机制 | 复杂度 |
|------|------|--------|
| A: 使用现有 send_reply() + pigeon | 直接调用已有模块 | 低 |
| B: 新的 Webhook URL 直接调用 | 存储企微 Webhook URL，直接 POST | 中 |
| C: 通过企微应用 API | 需要企微应用 Token | 高 |

### 决策：方案 A（使用现有 send_reply()）

**理由**：
- `send_reply()` 已封装消息分拆、多类型支持（text/markdown_v2）、错误处理
- `bot_key` 存储在 AsyncAgentTask 中，足以路由到正确的机器人
- `fly-pigeon` 库通过 bot_key 解析 Webhook URL，无需额外存储
- 零新增依赖

**Retry 策略**：
- 最多 3 次重试（指数退避：2s, 4s, 8s）
- 所有重试失败后记录 `delivery_failed` 状态到日志，不静默丢失（P8 合规）

---

## 6. Decision 5: Backward Compatibility

### 设计

在 `Chatbot` 模型新增 `async_mode` 字段（默认 `False`），保持向后兼容：

```python
# callback.py 的新流程
if bot.async_mode:
    # 新的异步流程
    await _handle_async_mode(...)
    return {"errcode": 0, "errmsg": "ok"}
else:
    # 原有同步流程（完全不变）
    result = await forward_to_agent_with_user_project(...)
    ...
```

**FR-011（同步模式自动降级为异步）**：
- 同步模式下，如果 agent 调用在 `sync_timeout_seconds`（默认 30s）内未完成，自动发送"处理中"消息并转为后台任务
- 实现方式：`asyncio.wait_for()` + timeout 捕获

---

## 7. Concurrent Message Handling (FR-013)

### 现状

已有 `ProcessingSession` 锁机制（DB-backed）阻止同一会话并发处理。异步模式下：
- 收到消息 → 创建 AsyncTask（状态 PENDING）→ 立即返回（释放 WeChat 3 秒限制）
- 如果同一会话再来消息，ProcessingSession 锁已释放（因为 callback 已返回）

### 新策略

异步模式下不使用 `ProcessingSession` 锁。改为：
- 检查该会话是否有 `PENDING` 或 `PROCESSING` 状态的任务
- 若有，向用户发送"仍在处理上一条消息（已等待 X 秒）"提示
- 若无，正常创建新任务（支持并发多任务，每个任务独立追踪）

---

## 8. Restart Recovery Strategy

### 启动时恢复流程

在 FastAPI `lifespan` 的 `startup` 阶段：

```python
async def recover_tasks():
    # 1. 查询 PENDING + PROCESSING 任务
    pending = await repo.get_tasks_by_status(["PENDING", "PROCESSING"])
    
    for task in pending:
        elapsed = now() - task.created_at
        if elapsed > task.max_task_duration_seconds:
            # 已超时：标记 TIMEOUT，发送超时通知
            await repo.mark_timeout(task.id)
            await send_reply(task.chat_id, "⏱️ 任务已超时...", bot_key=task.bot_key)
        else:
            # 未超时：重新提交执行
            asyncio.create_task(execute_task(task.task_id))
```

**注意**：对于 PROCESSING 状态（服务崩溃时正在执行的任务），重新提交会导致 Agent 收到重复请求。这是可接受的权衡——对 Agent 的幂等性要求是合理的（通过 `session_id` 继续会话）。

---

## 9. Constitution Validation

| 原则 | 合规状态 | 说明 |
|------|----------|------|
| P1 · Package Manager | ✅ | 使用 uv，无 pip 直调 |
| P2 · Type Safety | ✅ | 全部使用 Pydantic 模型和 SQLAlchemy Mapped 类型 |
| P3 · Async-First | ✅ | asyncio.create_task，无阻塞 I/O，async def 贯穿 |
| P4 · Database Migration Discipline | ✅ | 所有 schema 变更通过 Alembic migration |
| P6 · Security | ✅ | bot_key 不记录完整日志，API Key 不存入任务表 |
| P8 · Observability | ✅ | 每个状态转换都有结构化日志，request_id 全程追踪 |
| P9 · Configuration over Hardcoding | ✅ | timeout/retry 等从 DB 配置读取，有合理默认值 |
| P11 · SSE Stream Handling | ✅ | 使用 `+=` 积累，`content_block_stop` 触发最终解析 |

---

## 10. Identified Risks

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Agent 幂等性：重启后重复发送请求 | 低 | 中 | 通过 session_id 继续会话，Agent 侧幂等 |
| WeChat Webhook 失效（30min 后 bot_key 可能无效） | 低 | 高 | fly-pigeon 实时验证，失败记录日志 |
| 大量并发任务耗尽 DB 连接池 | 中 | 中 | asyncio.Semaphore 限制并发执行数（默认 10） |
| 服务无限增长的 PENDING 任务 | 低 | 中 | 定期清理（Cron 任务）30+ 天的已完成记录 |

---

## 11. A2A Async Capability Verification（T002b）

**结论**：`forward_to_agent_with_user_project()` **不提供**「提交 task_id 立即返回」的非阻塞 API；其为 **async 函数，会 await 完整 HTTP/隧道往返**（含 SSE 消费后的聚合结果），直到 Agent 返回或 `httpx`/隧道超时。

**适配策略（已实现）**：

1. 在企微回调路径中，`async_mode=True` 时 **不再 await** `forward_to_agent_with_user_project()`；改为 `AsyncTaskService.submit_task()` 写库后 `asyncio.create_task(self.execute_task(task_id))`，回调立即返回 `{"errcode":0}`。
2. 后台 `execute_task()` 内 **照常 await** `forward_to_agent_with_user_project(..., forward_config_override=快照)`，与同步路径共享同一套直连/隧道与响应解析逻辑（符合 research §3 / P11）。
3. 总执行时长由外层 `asyncio.wait_for(..., timeout=task.max_duration_seconds)` 约束，与 httpx read timeout 一致。

**相关文件**：`forward_service/services/forwarder.py`（`forward_config_override`）、`forward_service/services/async_task_service.py`。
