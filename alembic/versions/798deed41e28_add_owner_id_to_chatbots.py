"""add owner_id to chatbots

Revision ID: 798deed41e28
Revises: 553d78018b0a
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '798deed41e28'
down_revision: Union[str, None] = '553d78018b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 为 chatbots 表添加 owner_id 字段
    op.add_column('chatbots', sa.Column(
        'owner_id',
        sa.String(length=100),
        nullable=True,
        comment='Bot 管理员用户 ID（首次 /register 的用户）'
    ))
    op.create_index(op.f('ix_chatbots_owner_id'), 'chatbots', ['owner_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chatbots_owner_id'), table_name='chatbots')
    op.drop_column('chatbots', 'owner_id')
