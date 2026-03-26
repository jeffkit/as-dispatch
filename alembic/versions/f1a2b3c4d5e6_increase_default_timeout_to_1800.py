"""increase_default_timeout_to_1800

Revision ID: f1a2b3c4d5e6
Revises: e919da388f6f
Create Date: 2026-03-26 10:00:00.000000

将 bot_forward_configs 和 user_projects 表中超时时间的旧默认值（60s / 300s）统一更新为 1800s（30 分钟）。
自定义设置的超时值（不等于 60 或 300）保持不变。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e919da388f6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 将 bot_forward_configs 中旧默认值（60 或 300）更新为 1800
    op.execute(
        "UPDATE bot_forward_configs SET timeout = 1800 WHERE timeout IN (60, 300)"
    )
    # 将 user_projects 中旧默认值（60 或 300）更新为 1800
    op.execute(
        "UPDATE user_projects SET timeout = 1800 WHERE timeout IN (60, 300)"
    )


def downgrade() -> None:
    # 回滚：将 1800 还原为 300（不能精确还原 60，统一还原为 300）
    op.execute(
        "UPDATE bot_forward_configs SET timeout = 300 WHERE timeout = 1800"
    )
    op.execute(
        "UPDATE user_projects SET timeout = 300 WHERE timeout = 1800"
    )
