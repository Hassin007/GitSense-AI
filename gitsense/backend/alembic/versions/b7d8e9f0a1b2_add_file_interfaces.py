"""add file_interfaces table

Revision ID: b7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d8e9f0a1b2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_interfaces",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("connected_repos.id"), nullable=False),
        sa.Column("filepath", sa.String(), nullable=False),
        sa.Column("signatures", sa.JSON(), nullable=True),
        sa.Column("last_commit_sha", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_file_interfaces_repo_filepath", "file_interfaces", ["repo_id", "filepath"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_file_interfaces_repo_filepath", "file_interfaces", type_="unique")
    op.drop_table("file_interfaces")
