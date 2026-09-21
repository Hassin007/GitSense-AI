"""add exported_symbols to file_interfaces

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-07-26 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('file_interfaces', sa.Column('exported_symbols', sa.JSON(), nullable=True, server_default='[]'))


def downgrade() -> None:
    op.drop_column('file_interfaces', 'exported_symbols')
