"""create_async_agent_tasks

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "async_agent_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=50), nullable=False),
        sa.Column("bot_key", sa.String(length=100), nullable=False),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("from_user_id", sa.String(length=100), nullable=False),
        sa.Column("chat_type", sa.String(length=20), nullable=False, server_default="group"),
        sa.Column("mentioned_list", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("image_urls", sa.Text(), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("api_key", sa.String(length=200), nullable=True),
        sa.Column("project_id", sa.String(length=100), nullable=True),
        sa.Column("project_name", sa.String(length=200), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("new_session_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column(
            "processing_message",
            sa.String(length=500),
            nullable=False,
            server_default="正在为您处理，请稍候...",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_async_agent_tasks_task_id"),
    )
    op.create_index("idx_async_tasks_status", "async_agent_tasks", ["status"], unique=False)
    op.create_index("idx_async_tasks_bot_key", "async_agent_tasks", ["bot_key"], unique=False)
    op.create_index("idx_async_tasks_chat_id", "async_agent_tasks", ["chat_id"], unique=False)
    op.create_index("idx_async_tasks_created_at", "async_agent_tasks", ["created_at"], unique=False)
    op.create_index(
        "idx_async_tasks_status_created",
        "async_agent_tasks",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index("ix_async_agent_tasks_task_id", "async_agent_tasks", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_async_agent_tasks_task_id", table_name="async_agent_tasks")
    op.drop_index("idx_async_tasks_status_created", table_name="async_agent_tasks")
    op.drop_index("idx_async_tasks_created_at", table_name="async_agent_tasks")
    op.drop_index("idx_async_tasks_chat_id", table_name="async_agent_tasks")
    op.drop_index("idx_async_tasks_bot_key", table_name="async_agent_tasks")
    op.drop_index("idx_async_tasks_status", table_name="async_agent_tasks")
    op.drop_table("async_agent_tasks")
