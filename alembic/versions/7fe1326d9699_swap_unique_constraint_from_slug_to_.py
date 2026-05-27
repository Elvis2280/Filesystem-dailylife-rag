"""swap unique constraint from slug to storage_key

Revision ID: 7fe1326d9699
Revises: 771b30272481
Create Date: 2026-05-21 08:21:42.850601
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7fe1326d9699"
down_revision: Union[str, None] = "771b30272481"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'workspaces_slug_key'")
    ).fetchone()
    if result:
        op.drop_constraint(op.f("workspaces_slug_key"), "workspaces", type_="unique")

    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'workspaces'::regclass AND contype = 'u' "
            "AND conkey @> ("
            "  SELECT array_agg(attnum) FROM pg_attribute "
            "  WHERE attrelid = 'workspaces'::regclass AND attname = 'storage_key'"
            ")"
        )
    ).fetchone()
    if not result:
        op.create_unique_constraint(None, "workspaces", ["storage_key"])


def downgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'workspaces'::regclass AND contype = 'u' "
            "AND conkey @> ("
            "  SELECT array_agg(attnum) FROM pg_attribute "
            "  WHERE attrelid = 'workspaces'::regclass AND attname = 'storage_key'"
            ")"
        )
    ).fetchone()
    if result:
        op.drop_constraint(result[0], "workspaces", type_="unique")

    result = conn.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'workspaces_slug_key'")
    ).fetchone()
    if not result:
        op.create_unique_constraint(
            op.f("workspaces_slug_key"),
            "workspaces",
            ["slug"],
            postgresql_nulls_not_distinct=False,
        )
