"""make url_template nullable and add target_url

Revision ID: c1a2b3d4e5f6
Revises: 5b6ee90a9767
Create Date: 2026-01-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = '5b6ee90a9767'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 兼容的方式：使用 batch_alter_table
    with op.batch_alter_table('chatbots', schema=None) as batch_op:
        # 1. 添加 target_url 字段
        batch_op.add_column(sa.Column(
            'target_url', 
            sa.String(length=500), 
            nullable=True,
            comment='转发目标 URL (完整地址，推荐使用)'
        ))
        
        # 2. 将 url_template 改为可空（batch mode 会重建表）
        batch_op.alter_column('url_template',
            existing_type=sa.String(length=500),
            nullable=True,
            comment='URL 模板 (已废弃，保留用于数据迁移)'
        )
    
    # 3. 将现有数据从 url_template 复制到 target_url
    op.execute("""
        UPDATE chatbots 
        SET target_url = url_template 
        WHERE target_url IS NULL AND url_template IS NOT NULL AND url_template != ''
    """)


def downgrade() -> None:
    # SQLite 兼容的方式：使用 batch_alter_table
    with op.batch_alter_table('chatbots', schema=None) as batch_op:
        # 回滚：删除 target_url 字段
        batch_op.drop_column('target_url')
        
        # 将 url_template 改回非空（注意：如果有空数据会失败）
        batch_op.alter_column('url_template',
            existing_type=sa.String(length=500),
            nullable=False,
            comment='转发目标 URL 模板 (支持 {agent_id} 占位符)'
        )
