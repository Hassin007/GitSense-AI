"""add documentation_reason and documentation_suggestion to reports

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
Create Date: 2026-08-07 16:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3c4d5e6f7g8'
down_revision: Union[str, None] = 'g2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('documentation_reason', sa.String(), nullable=True))
    op.add_column('reports', sa.Column('documentation_suggestion', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('reports', 'documentation_suggestion')
    op.drop_column('reports', 'documentation_reason')
