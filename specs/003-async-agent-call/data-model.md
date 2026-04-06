# Data Model: Async Agent Call

**Feature**: 003-async-agent-call  
**Date**: 2026-03-26

---

## 1. New Table: `async_agent_tasks`

### SQLAlchemy Model

```python
class AsyncAgentTask(Base):
    """
    异步 Agent 任务表

    记录每一个从企微发往 Agent 的异步任务的完整生命周期。
    任务状态机: PENDING → PROCESSING → COMPLETED / FAILED / TIMEOUT
    """
    __tablename__ = "async_agent_tasks"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 任务标识（业务主键）
    task_id: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="任务唯一标识 (UUID-based short ID)"
    )

    # === 来源上下文（回复所需的全部信息）===

    bot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="触发任务的 Bot Key"
    )

    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="用户/群 ID（用于发送结果）"
    )

    from_user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="发送消息的用户 ID"
    )

    chat_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="group",
        comment="会话类型: group / single"
    )

    mentioned_list: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="需要 @ 的用户列表 (JSON array，群聊场景)"
    )

    # === 任务内容 ===

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="用户发送的原始消息内容"
    )

    image_urls: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="图片 URL 列表 (JSON array，可选)"
    )

    # === Agent 调用配置（从 ForwardConfig 复制，避免运行时依赖）===

    target_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Agent 目标 URL（任务创建时快照）"
    )

    api_key: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Agent API Key（任务创建时快照，不记录完整值到日志）"
    )

    project_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="使用的用户项目 ID"
    )

    project_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="项目名称（用于发送结果时显示）"
    )

    # === 会话上下文 ===

    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="提交任务时使用的 Agent Session ID（任务完成后可能更新）"
    )

    new_session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Agent 返回的新 Session ID（任务完成后从 AgentResult 更新）"
    )

    # === 任务状态 ===

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
        comment="任务状态: PENDING / PROCESSING / COMPLETED / FAILED / TIMEOUT"
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已重试次数"
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="最大重试次数（针对投递结果到企微，非 Agent 调用重试）"
    )

    # === 结果存储 ===

    response_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Agent 返回的完整响应文本（流积累完成后写入）"
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="失败或超时时的错误描述"
    )

    # === 时间追踪 ===

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="任务创建时间（来自 callback 入口）"
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="开始执行时间（状态变为 PROCESSING 时写入）"
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="任务完成/失败/超时时间"
    )

    # === 任务配置（从 Bot 配置快照，避免运行时依赖 bot 配置变更）===

    max_duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1800,
        comment="任务最大允许时长（秒），超时后标记 TIMEOUT"
    )

    processing_message: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="正在为您处理，请稍候...",
        comment="已发送给用户的处理中提示文本（快照）"
    )

    # 索引
    __table_args__ = (
        Index("idx_async_tasks_status", "status"),
        Index("idx_async_tasks_bot_key", "bot_key"),
        Index("idx_async_tasks_chat_id", "chat_id"),
        Index("idx_async_tasks_created_at", "created_at"),
        Index("idx_async_tasks_status_created", "status", "created_at"),
    )
```

---

## 2. Status Enum

```python
from enum import Enum

class AsyncTaskStatus(str, Enum):
    PENDING    = "PENDING"     # 已创建，等待执行器拾取
    PROCESSING = "PROCESSING"  # 正在调用 Agent / 等待流式响应
    COMPLETED  = "COMPLETED"   # Agent 响应已成功投递到企微
    FAILED     = "FAILED"      # Agent 调用失败或投递失败（已重试耗尽）
    TIMEOUT    = "TIMEOUT"     # 超过 max_duration_seconds，已发送超时通知
```

### 状态转换图

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
  [callback]        │              [executor]                 │
  创建任务 ─────▶ PENDING ─────▶ PROCESSING ─────▶ COMPLETED │
                                     │                        │
                                     ├─────▶ FAILED           │
                                     │      (重试耗尽)         │
                                     │                        │
                                     └─────▶ TIMEOUT          │
                                            (超 max_duration) │
                    │                                         │
                    └─────────────────────────────────────────┘
  [startup recovery]:
    PENDING/PROCESSING → 检查时间 → 超时则 TIMEOUT，否则重新入队
```

---

## 3. Modified Table: `chatbots`

在现有 `Chatbot` 模型上新增以下字段（通过 Alembic migration）：

```python
# 新增字段（追加到 Chatbot 类）

async_mode: Mapped[bool] = mapped_column(
    Boolean,
    nullable=False,
    default=False,
    server_default="0",
    comment="是否启用异步模式（默认关闭，保持向后兼容）"
)

processing_message: Mapped[Optional[str]] = mapped_column(
    String(500),
    nullable=True,
    comment="异步模式下向用户发送的处理中提示文本（None 时使用系统默认）"
)

sync_timeout_seconds: Mapped[int] = mapped_column(
    Integer,
    nullable=False,
    default=30,
    server_default="30",
    comment="同步模式下等待 Agent 响应的超时（秒），超时后自动降级为异步"
)

max_task_duration_seconds: Mapped[int] = mapped_column(
    Integer,
    nullable=False,
    default=1800,
    server_default="1800",
    comment="异步任务最大允许时长（秒），默认 30 分钟"
)
```

### 新增字段的默认值语义

| 字段 | 默认值 | 语义 |
|------|--------|------|
| `async_mode` | `False` | 不改变现有 bot 行为，完全向后兼容 |
| `processing_message` | `None` → 使用 `"正在为您处理，请稍候..."` | 可按 bot 定制 |
| `sync_timeout_seconds` | `30` | 同步模式 30s 超时后自动降级异步 |
| `max_task_duration_seconds` | `1800` | 30 分钟任务超时上限 |

---

## 4. Relationships

```
Chatbot (chatbots)
  │  bot_key (non-FK reference, for audit preservation)
  │
  └── AsyncAgentTask (async_agent_tasks) [0..*]
        │  new_session_id → UserSession.session_id (soft ref)
        │  project_id → UserProjectConfig.project_id (soft ref)
        │
        └── (execution produces) → send_reply() → WeChat Work
```

**注意**：`AsyncAgentTask` 不使用外键约束关联 `chatbots`，原因：
- 允许 Bot 配置更新后历史任务记录保持完整
- 允许 Bot 被删除后任务记录保留（审计需求）
- 任务创建时快照所有执行所需信息（target_url, api_key 等）

---

## 5. Alembic Migration 计划

### Migration 1: `add_async_fields_to_chatbots`

```sql
ALTER TABLE chatbots 
  ADD COLUMN async_mode BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN processing_message VARCHAR(500) NULL,
  ADD COLUMN sync_timeout_seconds INTEGER NOT NULL DEFAULT 30,
  ADD COLUMN max_task_duration_seconds INTEGER NOT NULL DEFAULT 1800;
```

### Migration 2: `create_async_agent_tasks`

```sql
CREATE TABLE async_agent_tasks (
  id INTEGER NOT NULL AUTO_INCREMENT,
  task_id VARCHAR(50) NOT NULL,
  bot_key VARCHAR(100) NOT NULL,
  chat_id VARCHAR(200) NOT NULL,
  from_user_id VARCHAR(100) NOT NULL,
  chat_type VARCHAR(20) NOT NULL DEFAULT 'group',
  mentioned_list TEXT,
  message TEXT NOT NULL,
  image_urls TEXT,
  target_url TEXT NOT NULL,
  api_key VARCHAR(200),
  project_id VARCHAR(100),
  project_name VARCHAR(200),
  session_id VARCHAR(100),
  new_session_id VARCHAR(100),
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  response_text TEXT,
  error_message TEXT,
  created_at DATETIME NOT NULL,
  started_at DATETIME,
  completed_at DATETIME,
  max_duration_seconds INTEGER NOT NULL DEFAULT 1800,
  processing_message VARCHAR(500) NOT NULL DEFAULT '正在为您处理，请稍候...',
  PRIMARY KEY (id),
  UNIQUE KEY uq_task_id (task_id),
  INDEX idx_async_tasks_status (status),
  INDEX idx_async_tasks_bot_key (bot_key),
  INDEX idx_async_tasks_chat_id (chat_id),
  INDEX idx_async_tasks_created_at (created_at),
  INDEX idx_async_tasks_status_created (status, created_at)
);
```

---

## 6. Repository Interface

```python
class AsyncTaskRepository:
    """AsyncAgentTask 的数据访问层"""

    async def create(self, task: AsyncAgentTask) -> AsyncAgentTask: ...
    async def get_by_task_id(self, task_id: str) -> AsyncAgentTask | None: ...
    async def get_by_status(self, statuses: list[str]) -> list[AsyncAgentTask]: ...
    async def get_active_by_chat(self, chat_id: str, bot_key: str) -> list[AsyncAgentTask]: ...
    async def update_status(
        self,
        task_id: str,
        status: str,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        response_text: str | None = None,
        new_session_id: str | None = None,
        error_message: str | None = None,
    ) -> None: ...
    async def increment_retry(self, task_id: str) -> int: ...  # returns new retry_count
    async def list_for_admin(
        self,
        bot_key: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AsyncAgentTask]: ...
    async def cleanup_old_completed(self, older_than_days: int = 30) -> int: ...
```
