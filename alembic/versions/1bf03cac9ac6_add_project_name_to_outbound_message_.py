"""add project_name to outbound_message_contexts

Revision ID: 1bf03cac9ac6
Revises: e919da388f6f
Create Date: 2026-03-23 15:17:13.340996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1bf03cac9ac6'
down_revision: Union[str, Sequence[str], None] = 'e919da388f6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('outbound_message_contexts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_name', sa.String(length=200), nullable=True, comment='项目名称（用于回复注入时定位 workspace）'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('outbound_message_contexts', schema=None) as batch_op:
        batch_op.drop_column('project_name')
