"""add analysis_gaps and whole_diff_skipped to reports

Revision ID: a1b2c3d4e5f6
Revises: f5b660ec8f08
Create Date: 2026-07-11 13:06:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f5b660ec8f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('analysis_gaps', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('reports', sa.Column('whole_diff_skipped', sa.Boolean(), nullable=True, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('reports', 'whole_diff_skipped')
    op.drop_column('reports', 'analysis_gaps')
