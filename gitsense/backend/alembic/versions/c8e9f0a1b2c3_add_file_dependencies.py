"""add file_dependencies table

Revision ID: c8e9f0a1b2c3
Revises: b7d8e9f0a1b2
Create Date: 2026-07-24 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e9f0a1b2c3'
down_revision: Union[str, None] = 'b7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_dependencies",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("connected_repos.id"), nullable=False),
        sa.Column("importer_filepath", sa.String(), nullable=False),
        sa.Column("imported_filepath", sa.String(), nullable=False),
        sa.Column("last_seen_commit_sha", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_file_dependencies_edge", "file_dependencies", ["repo_id", "importer_filepath", "imported_filepath"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_file_dependencies_edge", "file_dependencies", type_="unique")
    op.drop_table("file_dependencies")
