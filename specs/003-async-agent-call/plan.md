# Implementation Plan: Async Agent Call via JSON-RPC Message Stream

**Feature**: 003-async-agent-call  
**Date**: 2026-03-26  
**Status**: Ready for Task Breakdown  
**Estimated Complexity**: Medium-High (6 phases, ~15 implementation tasks)

---

## Architecture Overview

### Current Flow (Synchronous — Problematic)

```
WeChat Work
    │ callback POST
    ▼
callback.py
    │ await forward_to_agent_with_user_project()  ← 最长等待 1800s
    │
    ▼
AgentStudio / Tunnel
    │ HTTP response (full)
    ▼
callback.py
    │ send_reply()
    ▼
WeChat Work (结果)
```

**问题**: WeChat 要求 3 秒内返回 HTTP 200，但 Agent 处理可能需要数分钟，引发 504 超时。

---

### Target Flow (Async)

```
WeChat Work
    │ callback POST
    ▼
callback.py
    │ [async_mode=True]
    ├─ send_reply("正在为您处理...")  ← <3s 内完成
    ├─ async_task_service.submit_task(...)  ← 写 DB，spawn asyncio.create_task
    └─ return {"errcode": 0, "errmsg": "ok"}  ← 立即返回 WeChat
    
    │ [后台 asyncio 任务]
    ▼
AsyncTaskExecutor
    │ status: PENDING → PROCESSING
    │ await forward_to_agent_with_user_project()  ← 可等待数十分钟
    │
    ▼
AgentStudio / Tunnel
    │ HTTP response (full, SSE stream consumed)
    ▼
AsyncTaskExecutor
    │ status: PROCESSING → COMPLETED
    │ await send_reply(response_text, ...)
    ▼
WeChat Work (结果)
```

---

### Component Map

```
forward_service/
├── models.py                    ← [修改] 新增 AsyncAgentTask 模型 + Chatbot 新字段
├── repository.py                ← [修改] 新增 AsyncTaskRepository
├── config.py                    ← [修改] 新增 3 个环境变量读取
├── services/
│   ├── forwarder.py             ← [不变] 直接复用
│   └── async_task_service.py   ← [新建] 核心执行器
├── routes/
│   ├── callback.py              ← [修改] 新增异步分支 + 同步降级逻辑
│   ├── bots_api.py              ← [修改] 新增 async 相关字段的 CRUD
│   └── async_tasks_api.py      ← [新建] 管理员任务状态查询 API
├── app.py                       ← [修改] lifespan 启动时调用 recover_pending_tasks()
│                                          注册 async_tasks_api 路由
└── alembic/versions/
    ├── xxxx_add_async_fields_to_chatbots.py   ← [新建] Migration 1
    └── xxxx_create_async_agent_tasks.py       ← [新建] Migration 2
```

---

## Implementation Phases

---

### Phase 1: Database Schema

**目标**: 建立数据基础，所有后续阶段依赖此 schema。

#### Task 1.1: 扩展 `Chatbot` 模型

文件：`forward_service/models.py`

- 新增字段：`async_mode`, `processing_message`, `sync_timeout_seconds`, `max_task_duration_seconds`
- 参考 data-model.md 第 3 节的完整字段定义
- 所有字段有 `server_default` 以保证向后兼容

#### Task 1.2: 新建 `AsyncAgentTask` 模型

文件：`forward_service/models.py`

- 参考 data-model.md 第 1 节的完整模型定义
- 实现 `to_dict()` 方法（用于 Admin API 响应）
- 实现 `is_timed_out` 属性（`created_at + max_duration_seconds < now()`）

#### Task 1.3: 生成 Alembic Migration

```bash
cd platform/as-dispatch
alembic revision --autogenerate -m "add_async_mode_to_chatbots_and_create_async_agent_tasks"
```

- 人工审查生成的 migration（检查列类型、默认值、索引）
- 本地 SQLite 测试：`alembic upgrade head`
- 生成 SQL 预览：`alembic upgrade head --sql > migration_preview.sql`

**验收**: 所有 existing bot 的 `async_mode` 默认为 `False`，现有功能完全不受影响。

---

### Phase 2: Repository & Service Foundation

**目标**: 建立数据访问层和核心服务骨架。

#### Task 2.1: 新增 `AsyncTaskRepository`

文件：`forward_service/repository.py`

实现以下方法：
```python
async def create_async_task(session, task: AsyncAgentTask) -> AsyncAgentTask
async def get_async_task_by_id(session, task_id: str) -> AsyncAgentTask | None
async def get_async_tasks_by_status(session, statuses: list[str]) -> list[AsyncAgentTask]
async def get_active_tasks_by_chat(session, chat_id: str, bot_key: str) -> list[AsyncAgentTask]
async def update_async_task_status(session, task_id: str, **kwargs) -> None
async def list_async_tasks_for_admin(session, **filters) -> list[AsyncAgentTask]
async def cleanup_old_async_tasks(session, older_than_days: int) -> int
```

遵循现有 repository 模式（`get_db_manager().get_session()` async context manager）。

#### Task 2.2: 新增环境变量读取

文件：`forward_service/config.py`

在 `ServiceConfig` 类中新增：
```python
async_task_max_concurrency: int = 10
async_task_default_timeout: int = 1800
async_task_default_processing_msg: str = "正在为您处理，请稍候..."
```
从环境变量读取：`ASYNC_TASK_MAX_CONCURRENCY` 等（参见 contracts/internal-async-interface.md 第 6 节）。

---

### Phase 3: Async Task Executor

**目标**: 实现核心的异步任务执行引擎。

#### Task 3.1: 创建 `AsyncTaskService`

文件：`forward_service/services/async_task_service.py`（新建）

```python
class AsyncTaskService:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(config.async_task_max_concurrency)
    
    async def submit_task(self, *, bot_key, chat_id, ...) -> str:
        """创建 DB 记录，spawn asyncio 任务，返回 task_id"""
    
    async def execute_task(self, task_id: str) -> None:
        """后台执行：PENDING → PROCESSING → COMPLETED/FAILED/TIMEOUT"""
    
    async def recover_pending_tasks(self) -> None:
        """服务启动时恢复挂起任务"""
    
    async def get_task_status(self, task_id: str) -> AsyncTaskStatus | None:
        """查询单个任务状态"""
```

#### Task 3.2: 实现 `execute_task()` 核心逻辑

关键实现点：

```python
async def execute_task(self, task_id: str) -> None:
    async with self._semaphore:  # 并发控制
        try:
            # 1. 从 DB 加载任务（最新状态）
            task = await repo.get_async_task_by_id(task_id)
            if not task or task.status != "PENDING":
                return  # 已被其他 worker 处理或已完成
            
            # 2. 更新为 PROCESSING
            await repo.update_async_task_status(
                task_id, status="PROCESSING", started_at=now()
            )
            
            # 3. 调用 Agent（带 max_duration 超时）
            try:
                result = await asyncio.wait_for(
                    forward_to_agent_with_user_project(
                        bot_key=task.bot_key,
                        chat_id=task.chat_id,
                        content=task.message,
                        timeout=task.max_duration_seconds,
                        session_id=task.session_id,
                        current_project_id=task.project_id,
                        image_urls=json.loads(task.image_urls) if task.image_urls else None,
                    ),
                    timeout=task.max_duration_seconds
                )
            except asyncio.TimeoutError:
                await self._handle_timeout(task)
                return
            
            # 4. 投递结果（带重试）
            await self._deliver_result(task, result)
            
        except Exception as e:
            logger.error(f"[AsyncTask:{task_id}] 执行异常: {e}", exc_info=True)
            await self._handle_failure(task_id, str(e))
```

#### Task 3.3: 实现结果投递与重试

```python
async def _deliver_result(self, task: AsyncAgentTask, result: AgentResult | None) -> None:
    """投递 Agent 结果到企微，最多 3 次重试（指数退避）"""
    for attempt in range(task.max_retries + 1):
        try:
            if result and result.reply:
                send_result = await send_reply(
                    chat_id=task.chat_id,
                    message=result.reply,
                    msg_type=result.msg_type,
                    bot_key=task.bot_key,
                    short_id=result.session_id[:8] if result.session_id else None,
                    project_name=result.project_name,
                    mentioned_list=json.loads(task.mentioned_list) if task.mentioned_list else None,
                )
                if send_result.get("success"):
                    await repo.update_async_task_status(
                        task.task_id,
                        status="COMPLETED",
                        completed_at=now(),
                        response_text=result.reply[:10000],
                        new_session_id=result.session_id,
                    )
                    # 更新 UserSession（记录新 session_id）
                    if result.session_id:
                        await session_mgr.record_session(...)
                    return
            
        except Exception as e:
            logger.warning(f"[AsyncTask:{task.task_id}] 投递失败 attempt={attempt}: {e}")
        
        if attempt < task.max_retries:
            await asyncio.sleep(2 ** attempt * 2)  # 2s, 4s, 8s
    
    # 所有重试失败
    await self._handle_failure(task.task_id, "结果投递失败（重试耗尽）")
```

---

### Phase 4: Callback Integration

**目标**: 修改 `callback.py` 支持异步模式，保持同步模式完全不变。

#### Task 4.1: 异步模式分支

文件：`forward_service/routes/callback.py`

在通过所有前置检查（鉴权、Bot 查找、访问控制、命令处理、去重）之后，新增 `async_mode` 判断：

```python
# === 核心转发逻辑 ===
if bot.async_mode:
    result = await _handle_async_mode(
        bot=bot, chat_id=chat_id, ...
    )
    return result
else:
    # 原有同步逻辑（完全不变）
    result = await forward_to_agent_with_user_project(...)
    ...
```

#### Task 4.2: 实现 `_handle_async_mode()`

```python
async def _handle_async_mode(...) -> dict:
    # 1. 检查是否有活跃任务（FR-013）
    active_tasks = await repo.get_active_tasks_by_chat(chat_id, bot.bot_key)
    if active_tasks:
        elapsed = compute_elapsed(active_tasks[0].created_at)
        elapsed_str = format_elapsed(elapsed)
        await send_reply(
            chat_id=chat_id,
            message=f"⏳ 前一条消息仍在处理中（已等待 {elapsed_str}），请稍候...",
            bot_key=bot.bot_key,
            mentioned_list=mentioned_list,
        )
        return {"errcode": 0, "errmsg": "task_already_active"}
    
    # 2. 获取 ForwardConfig
    try:
        forward_config = await get_forward_config_for_user(bot.bot_key, chat_id, current_project_id)
    except ValueError as e:
        await send_reply(chat_id, f"⚠️ {e}", bot_key=bot.bot_key)
        return {"errcode": 0, "errmsg": "config_error"}
    
    # 3. 发送"处理中"消息（P1 of spec - 5s 内用户看到确认）
    processing_msg = bot.processing_message or config.async_task_default_processing_msg
    await send_reply(chat_id, processing_msg, bot_key=bot.bot_key, mentioned_list=mentioned_list)
    
    # 4. 提交异步任务（写 DB + spawn asyncio task）
    task_id = await async_task_service.submit_task(
        bot_key=bot.bot_key,
        chat_id=chat_id,
        from_user_id=from_user_id,
        chat_type=chat_type,
        message=forward_content,
        session_id=current_session_id,
        forward_config=forward_config,
        mentioned_list=mentioned_list,
        image_urls=image_urls,
        processing_message=processing_msg,
        max_duration_seconds=bot.max_task_duration_seconds,
    )
    
    logger.info(f"[Async] 任务已提交: task_id={task_id}, chat_id={chat_id}, bot={bot.name}")
    
    # 5. 更新 ForwardLog
    if log_id:
        await update_request_log(log_id, status="async_submitted")
    
    return {"errcode": 0, "errmsg": "ok"}
```

#### Task 4.3: 同步模式自动降级（FR-011）

在同步流程中，用 `asyncio.wait_for()` 包裹 Agent 调用：

```python
# 同步模式（原有逻辑入口）
sync_timeout = bot.sync_timeout_seconds if hasattr(bot, 'sync_timeout_seconds') else 30

try:
    result = await asyncio.wait_for(
        forward_to_agent_with_user_project(...),
        timeout=float(sync_timeout)
    )
except asyncio.TimeoutError:
    # 降级：发送处理中消息，提交异步任务
    logger.info(f"同步超时，降级为异步: chat_id={chat_id}, timeout={sync_timeout}s")
    processing_msg = bot.processing_message or config.async_task_default_processing_msg
    await send_reply(chat_id, processing_msg, bot_key=bot.bot_key, mentioned_list=mentioned_list)
    await async_task_service.submit_task(...)
    return {"errcode": 0, "errmsg": "ok"}
```

---

### Phase 5: Admin API & Bot Config

**目标**: 提供操作可见性和配置界面。

#### Task 5.1: 新建 `async_tasks_api.py`

文件：`forward_service/routes/async_tasks_api.py`

```python
router = APIRouter(prefix="/api/admin/async-tasks", tags=["async-tasks"])

@router.get("")
async def list_async_tasks(
    status: str | None = None,
    bot_key: str | None = None,
    chat_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    auth: str = Depends(verify_admin_key),
) -> dict: ...

@router.get("/{task_id}")
async def get_async_task(
    task_id: str,
    auth: str = Depends(verify_admin_key),
) -> dict: ...
```

参照 contracts/internal-async-interface.md 第 3 节的 API 规范。

#### Task 5.2: 扩展 Bot Config API

文件：`forward_service/routes/bots_api.py`

- 在 Bot 创建/更新的 Pydantic 模型中新增 `async_mode`, `processing_message`, `sync_timeout_seconds`, `max_task_duration_seconds`
- Bot 查询响应中新增 `async_config` 字段

#### Task 5.3: 注册新路由 + 启动恢复

文件：`forward_service/app.py`

```python
# 注册路由
app.include_router(async_tasks_api.router)

# lifespan 启动时恢复任务
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ...existing startup...
    await async_task_service.recover_pending_tasks()
    yield
    # ...existing shutdown...
```

---

### Phase 6: Testing & Deployment

**目标**: 验证所有 Success Criteria，安全部署。

#### Task 6.1: 本地验证测试

**SC-001 验证（3秒内确认）**：
```bash
# 发送消息 → 用 curl 模拟 WeChat callback
curl -X POST http://localhost:8083/callback \
  -H "Content-Type: application/json" \
  -d '{"chatid":"test", "msgtype":"text", "text":{"content":"hello"}, ...}'
# 测量响应时间 < 3s
```

**SC-003 验证（5秒内看到"处理中"消息）**：
- 启用 async_mode 的 bot
- 发送消息
- 观察用户侧是否在 5s 内收到"正在为您处理"

**SC-005 验证（重启不丢任务）**：
1. 提交一个长任务（模拟 Agent 慢响应）
2. 重启 as-dispatch 服务
3. 验证任务继续执行并最终投递结果

**SC-006 验证（向后兼容）**：
- 现有 bot（`async_mode=False`）保持原有行为
- 快速 Agent 响应（< 30s）直接回复，无"处理中"消息

#### Task 6.2: Alembic Migration 生产部署

```bash
# 1. 生成 SQL 预览（人工审查）
alembic upgrade head --sql > migration_003_preview.sql

# 2. 本地 SQLite 验证
alembic upgrade head

# 3. 生产 MySQL 部署
alembic upgrade head
```

#### Task 6.3: Bot 配置启用异步模式

通过 Admin API 对需要异步的 bot 启用：
```bash
curl -X PATCH /api/admin/bots/{bot_key} \
  -d '{"async_mode": true, "processing_message": "🤔 正在处理您的请求，稍后回复..."}'
```

---

## Risk Mitigation

| 风险 | 缓解措施 |
|------|----------|
| asyncio.create_task 在 FastAPI worker 进程中可能被 kill | 使用 lifespan 的 shutdown 钩子，等待活跃任务完成（设置 graceful shutdown timeout） |
| fly-pigeon 同步调用阻塞事件循环 | 确认 pigeon 库是否有异步版本；若无，用 `asyncio.to_thread()` 包裹（P3 合规） |
| 大量并发任务导致 Agent 过载 | `asyncio.Semaphore(max_concurrency)` 限制并发数 |
| WeChat Webhook URL 过期（bot_key 失效） | 错误记录到 ForwardLog + AsyncAgentTask，不静默失败 |

---

## Constitution Compliance Checklist

- [x] **P1 Package Manager**: 无 pip 直调，使用 uv
- [x] **P2 Type Safety**: Pydantic 模型用于所有 API 边界，SQLAlchemy Mapped 类型
- [x] **P3 Async-First**: `async def` 贯穿，`asyncio.create_task`，`asyncio.wait_for`，无 `time.sleep`
- [x] **P4 DB Migration Discipline**: Alembic 管理所有 schema 变更，migration 与代码同 PR 提交
- [x] **P6 Security**: API Key 不写入日志，bot_key 截断显示，env var 管理配置
- [x] **P8 Observability**: 每个状态转换结构化日志，request_id 追踪，无静默异常
- [x] **P9 Configuration**: timeout/message/concurrency 全部从 env var / DB 读取
- [x] **P11 SSE Stream**: 复用 `forward_to_agent_with_user_project()` 的正确积累实现

---

## Readiness for Task Breakdown

本计划已覆盖：
- ✅ 所有 13 条 Functional Requirements (FR-001 ~ FR-013)
- ✅ 所有 7 条 Success Criteria (SC-001 ~ SC-007)
- ✅ 所有 Edge Cases 均有处理策略
- ✅ 向后兼容（async_mode 默认 False）
- ✅ Constitution P1-P11 全部合规

**下一步**: 拆解为具体可执行的 checklist tasks，每个 task 对应一个可独立测试的代码变更。
