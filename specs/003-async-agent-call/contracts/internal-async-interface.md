# Internal Contracts: Async Agent Call Interface

**Feature**: 003-async-agent-call  
**Date**: 2026-03-26  
**Scope**: 内部接口契约（无新增对外 HTTP API，仅文档化内部模块边界）

---

## 1. AsyncTaskService — 公开接口

位置：`forward_service/services/async_task_service.py`

### 1.1 `submit_task()`

```python
async def submit_task(
    *,
    bot_key: str,
    chat_id: str,
    from_user_id: str,
    chat_type: str,
    message: str,
    session_id: str | None,
    forward_config: ForwardConfig,
    mentioned_list: list[str] | None = None,
    image_urls: list[str] | None = None,
    processing_message: str = "正在为您处理，请稍候...",
    max_duration_seconds: int = 1800,
) -> str:
    """
    创建并提交一个异步 Agent 任务。

    行为:
    1. 在 DB 创建 AsyncAgentTask（status=PENDING）
    2. 使用 asyncio.create_task() 调度后台执行
    3. 返回 task_id（用于追踪）

    调用方（callback.py）职责:
    - 调用 submit_task() 之前，发送"处理中"消息给用户
    - submit_task() 返回后，立即向 WeChat 返回 200

    不抛出异常（内部错误记录到日志）
    """
```

### 1.2 `execute_task()`

```python
async def execute_task(task_id: str) -> None:
    """
    执行异步 Agent 任务（在 asyncio 后台任务中运行）。

    完整流程:
    1. 更新状态为 PROCESSING
    2. 调用 forward_to_agent_with_user_project() 等待响应
    3. 成功: 更新状态为 COMPLETED，调用 send_reply() 投递结果
    4. 失败: 更新状态为 FAILED，向用户发送错误通知
    5. 超时: 更新状态为 TIMEOUT，向用户发送超时通知

    超时控制: asyncio.wait_for(timeout=task.max_duration_seconds)
    结果投递重试: 最多 3 次，指数退避（2s, 4s, 8s）
    绝不静默吞掉异常（P8 合规）
    """
```

### 1.3 `recover_pending_tasks()`

```python
async def recover_pending_tasks() -> None:
    """
    服务启动时恢复挂起的任务（在 FastAPI lifespan startup 中调用）。

    行为:
    - 查询 status IN (PENDING, PROCESSING) 的所有任务
    - 对于超过 max_duration_seconds 的任务: 标记 TIMEOUT + 发送超时通知
    - 对于未超时的任务: 重新调度 asyncio.create_task(execute_task(...))

    日志:
    - 恢复任务数量
    - 每个任务的 task_id 和当前状态
    """
```

### 1.4 `get_task_status()`

```python
async def get_task_status(task_id: str) -> AsyncTaskStatus | None:
    """
    查询单个任务状态（供 Admin API 调用）
    """
```

---

## 2. Callback.py 修改接口

### 新增的异步处理分支

```python
# 调用点：handle_callback() 中，在通过所有检查（鉴权、Bot查找、访问控制、命令处理）之后

# 条件：bot.async_mode is True
async def _handle_async_mode(
    bot: BotConfig,
    chat_id: str,
    from_user_id: str,
    chat_type: str,
    content: str,
    image_urls: list[str],
    session_id: str | None,
    current_project_id: str | None,
    mentioned_list: list[str] | None,
    log_id: int | None,
) -> dict:
    """
    异步模式处理入口

    返回: {"errcode": 0, "errmsg": "ok"} （立即，不等待 Agent）

    内部流程:
    1. 检查是否有活跃任务（FR-013）
    2. 获取 ForwardConfig
    3. 发送"处理中"消息
    4. submit_task()
    5. 更新 ForwardLog 状态为 "async_submitted"
    6. 返回 200
    """
```

### 同步模式降级（FR-011）

```python
async def _handle_sync_with_fallback(
    bot: BotConfig,
    ...
    sync_timeout: int,  # bot.sync_timeout_seconds
) -> AgentResult | None:
    """
    带超时的同步调用，超时后自动降级为异步

    实现:
    try:
        result = await asyncio.wait_for(
            forward_to_agent_with_user_project(...),
            timeout=sync_timeout
        )
        return result
    except asyncio.TimeoutError:
        # 降级：发送"处理中"消息，提交异步任务
        await send_reply(chat_id, processing_message, ...)
        await async_task_service.submit_task(...)
        return None  # 告知调用方已降级处理
    """
```

---

## 3. Admin API — 任务状态查询

位置：`forward_service/routes/admin.py` 或新建 `routes/async_tasks_api.py`

### GET /api/admin/async-tasks

```
Query Parameters:
  status: string (optional) — PENDING | PROCESSING | COMPLETED | FAILED | TIMEOUT
  bot_key: string (optional) — 过滤指定 bot
  chat_id: string (optional) — 过滤指定会话
  limit: int (default=50, max=200)
  offset: int (default=0)

Response 200:
{
  "total": int,
  "tasks": [
    {
      "task_id": string,
      "bot_key": string,
      "chat_id": string,
      "from_user_id": string,
      "message": string (truncated to 100 chars),
      "status": "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "TIMEOUT",
      "created_at": ISO8601,
      "started_at": ISO8601 | null,
      "completed_at": ISO8601 | null,
      "error_message": string | null,
      "retry_count": int,
      "project_id": string | null,
      "session_id": string | null
    }
  ]
}

Auth: X-Api-Key header（与现有 Admin API 一致）
```

### GET /api/admin/async-tasks/{task_id}

```
Response 200:
{
  "task_id": string,
  "bot_key": string,
  "chat_id": string,
  "from_user_id": string,
  "chat_type": string,
  "message": string (full),
  "status": string,
  "response_text": string | null,
  "error_message": string | null,
  "created_at": ISO8601,
  "started_at": ISO8601 | null,
  "completed_at": ISO8601 | null,
  "max_duration_seconds": int,
  "retry_count": int,
  "max_retries": int,
  "project_id": string | null,
  "project_name": string | null,
  "session_id": string | null,
  "new_session_id": string | null,
  "target_url": string (masked — only domain shown)
}

Response 404:
{
  "error": "Task not found"
}
```

---

## 4. Bot Config API 扩展

位置：`forward_service/routes/bots_api.py`（已存在）

### 新增字段（在现有 Bot CRUD API 中）

```
# Bot 创建/更新 Request Body 新增字段:
{
  "async_mode": bool (default: false),
  "processing_message": string | null (default: null → "正在为您处理，请稍候..."),
  "sync_timeout_seconds": int (default: 30, min: 5, max: 300),
  "max_task_duration_seconds": int (default: 1800, min: 60, max: 7200)
}

# Bot 查询 Response 新增字段:
{
  "async_config": {
    "async_mode": bool,
    "processing_message": string,
    "sync_timeout_seconds": int,
    "max_task_duration_seconds": int
  }
}
```

---

## 5. 无变更的模块（稳定契约）

以下模块**不需要修改**，其契约不变：

| 模块 | 原因 |
|------|------|
| `forward_to_agent_with_user_project()` | 异步任务执行器直接调用，接口不变 |
| `send_reply()` / `send_to_wecom()` | 结果投递直接调用，接口不变 |
| `tunnel_proxy.py` | 隧道代理路由不受影响 |
| `session_manager.py` | 会话管理逻辑不变（任务完成后更新 session） |
| `ProcessingSession` 表 | 异步模式下不使用此锁，同步模式保持原有行为 |

---

## 6. 环境变量（新增）

遵循 P9（Configuration over Hardcoding）：

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `ASYNC_TASK_MAX_CONCURRENCY` | int | `10` | 同时执行的最大异步任务数（asyncio.Semaphore） |
| `ASYNC_TASK_DEFAULT_TIMEOUT` | int | `1800` | 全局默认任务超时（秒），Bot 配置可覆盖 |
| `ASYNC_TASK_DEFAULT_PROCESSING_MSG` | str | `"正在为您处理，请稍候..."` | 全局默认处理中提示 |

这些变量在 `forward_service/config.py` 的 `ServiceConfig` 类中统一读取和验证。
