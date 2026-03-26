"""add_async_fields_to_chatbots

Revision ID: d4e5f6a7b8c9
Revises: f1a2b3c4d5e6
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chatbots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "async_mode",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
                comment="是否启用异步模式（企微先 200，后台执行 Agent）",
            )
        )
        batch_op.add_column(
            sa.Column(
                "processing_message",
                sa.String(length=500),
                nullable=True,
                comment="异步模式下发给用户的处理中提示（None 时用系统默认）",
            )
        )
        batch_op.add_column(
            sa.Column(
                "sync_timeout_seconds",
                sa.Integer(),
                server_default=sa.text("30"),
                nullable=False,
                comment="同步模式等待 Agent 的超时（秒）",
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_task_duration_seconds",
                sa.Integer(),
                server_default=sa.text("1800"),
                nullable=False,
                comment="异步任务最大允许时长（秒）",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("chatbots", schema=None) as batch_op:
        batch_op.drop_column("max_task_duration_seconds")
        batch_op.drop_column("sync_timeout_seconds")
        batch_op.drop_column("processing_message")
        batch_op.drop_column("async_mode")
