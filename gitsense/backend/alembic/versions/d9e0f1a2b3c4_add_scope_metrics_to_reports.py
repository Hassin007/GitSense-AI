"""add scope_metrics to reports

Revision ID: d9e0f1a2b3c4
Revises: c8e9f0a1b2c3
Create Date: 2026-07-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('scope_metrics', sa.JSON(), nullable=True, server_default='{}'))


def downgrade() -> None:
    op.drop_column('reports', 'scope_metrics')
