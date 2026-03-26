-- =============================================================================
-- 003-async-agent-call: MySQL 8 DDL 预览（由 alembic 版本 d4e5f6a7b8c9 + e5f6a7b8c9d0 归纳）
-- 正式环境请以实际输出为准重新生成：
--   cd platform/as-dispatch && alembic upgrade head --sql > specs/003-async-agent-call/migration_003_preview.sql
-- 评审要点：表/列字符集 utf8mb4；中文 server_default 在 MySQL 8 中为字符串字面量；索引名冲突。
-- =============================================================================

-- --- Revision d4e5f6a7b8c9: add_async_fields_to_chatbots ---

ALTER TABLE chatbots
  ADD COLUMN async_mode TINYINT(1) NOT NULL DEFAULT 0
    COMMENT '是否启用异步模式（企微先 200，后台执行 Agent）',
  ADD COLUMN processing_message VARCHAR(500) NULL
    COMMENT '异步模式下发给用户的处理中提示（NULL 时用系统默认）',
  ADD COLUMN sync_timeout_seconds INT NOT NULL DEFAULT 30
    COMMENT '同步模式等待 Agent 的超时（秒）',
  ADD COLUMN max_task_duration_seconds INT NOT NULL DEFAULT 1800
    COMMENT '异步任务最大允许时长（秒）';

-- --- Revision e5f6a7b8c9d0: create_async_agent_tasks ---

CREATE TABLE async_agent_tasks (
  id INT AUTO_INCREMENT NOT NULL,
  task_id VARCHAR(50) NOT NULL,
  bot_key VARCHAR(100) NOT NULL,
  chat_id VARCHAR(200) NOT NULL,
  from_user_id VARCHAR(100) NOT NULL,
  chat_type VARCHAR(20) NOT NULL DEFAULT 'group',
  mentioned_list TEXT NULL,
  message TEXT NOT NULL,
  image_urls TEXT NULL,
  target_url TEXT NOT NULL,
  api_key VARCHAR(200) NULL,
  project_id VARCHAR(100) NULL,
  project_name VARCHAR(200) NULL,
  session_id VARCHAR(100) NULL,
  new_session_id VARCHAR(100) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  retry_count INT NOT NULL DEFAULT 0,
  max_retries INT NOT NULL DEFAULT 3,
  response_text TEXT NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL,
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  max_duration_seconds INT NOT NULL DEFAULT 1800,
  processing_message VARCHAR(500) NOT NULL DEFAULT '正在为您处理，请稍候...',
  PRIMARY KEY (id),
  CONSTRAINT uq_async_agent_tasks_task_id UNIQUE (task_id)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_async_tasks_status ON async_agent_tasks (status);
CREATE INDEX idx_async_tasks_bot_key ON async_agent_tasks (bot_key);
CREATE INDEX idx_async_tasks_chat_id ON async_agent_tasks (chat_id);
CREATE INDEX idx_async_tasks_created_at ON async_agent_tasks (created_at);
CREATE INDEX idx_async_tasks_status_created ON async_agent_tasks (status, created_at);
CREATE INDEX ix_async_agent_tasks_task_id ON async_agent_tasks (task_id);
