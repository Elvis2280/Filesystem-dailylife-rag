"""add deleted_at rename display_name to name

Revision ID: d1e2f3a4b5c6
Revises: 03bb640a8e9c
Create Date: 2026-07-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "03bb640a8e9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Add name column
    op.add_column(
        "workspaces",
        sa.Column("name", sa.String(), nullable=True),
    )

    # Copy display_name into name
    conn.execute(sa.text("UPDATE workspaces SET name = display_name"))

    # Make name non-nullable
    op.alter_column("workspaces", "name", nullable=False)

    # Drop display_name
    op.drop_column("workspaces", "display_name")

    # Add deleted_at
    op.add_column(
        "workspaces",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Restore display_name
    op.add_column(
        "workspaces",
        sa.Column("display_name", sa.String(), nullable=True),
    )
    conn.execute(sa.text("UPDATE workspaces SET display_name = name"))
    op.alter_column("workspaces", "display_name", nullable=False)

    # Drop name
    op.drop_column("workspaces", "name")

    # Drop deleted_at
    op.drop_column("workspaces", "deleted_at")
