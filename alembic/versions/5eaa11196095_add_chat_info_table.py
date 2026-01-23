"""add_chat_info_table

Revision ID: 5eaa11196095
Revises: c1a2b3d4e5f6
Create Date: 2026-01-18 22:40:14.662975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5eaa11196095'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建 chat_info 表，用于存储 chat_id -> chat_type 的映射
    op.create_table('chat_info',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('chat_id', sa.String(length=200), nullable=False, comment='Chat ID (群ID或私聊ID)'),
    sa.Column('chat_type', sa.String(length=20), nullable=False, comment='Chat 类型: group (群聊) / single (私聊)'),
    sa.Column('chat_name', sa.String(length=200), nullable=True, comment='Chat 名称（群名/用户名）'),
    sa.Column('first_bot_key', sa.String(length=100), nullable=True, comment='首次收到消息的 Bot Key'),
    sa.Column('message_count', sa.Integer(), nullable=False, comment='收到的消息总数'),
    sa.Column('first_seen_at', sa.DateTime(), nullable=False, comment='首次收到消息的时间'),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False, comment='最后收到消息的时间'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_info', schema=None) as batch_op:
        batch_op.create_index('idx_chat_info_chat_id', ['chat_id'], unique=False)
        batch_op.create_index('idx_chat_info_chat_type', ['chat_type'], unique=False)
        batch_op.create_index('idx_chat_info_last_seen', ['last_seen_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_info_chat_id'), ['chat_id'], unique=True)

    # 注意：user_sessions 的变更已在之前的迁移 5b6ee90a9767 中处理


def downgrade() -> None:
    """Downgrade schema."""
    # 删除 chat_info 表
    with op.batch_alter_table('chat_info', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_info_chat_id'))
        batch_op.drop_index('idx_chat_info_last_seen')
        batch_op.drop_index('idx_chat_info_chat_type')
        batch_op.drop_index('idx_chat_info_chat_id')

    op.drop_table('chat_info')
