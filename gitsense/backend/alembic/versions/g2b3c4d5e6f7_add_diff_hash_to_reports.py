"""add diff_hash to reports

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-02 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('diff_hash', sa.String(), nullable=True))
    op.create_index(op.f('ix_reports_diff_hash'), 'reports', ['diff_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reports_diff_hash'), table_name='reports')
    op.drop_column('reports', 'diff_hash')
