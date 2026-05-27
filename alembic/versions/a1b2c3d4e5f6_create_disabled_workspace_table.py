"""create disabled workspace table

Revision ID: a1b2c3d4e5f6
Revises: 62f714cc3741
Create Date: 2026-05-27 07:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "62f714cc3741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "disabled_workspace",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_storage_key", sa.String(), nullable=False),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_disabled_workspace_workspace_storage_key"),
        "disabled_workspace",
        ["workspace_storage_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_disabled_workspace_workspace_storage_key"),
        table_name="disabled_workspace",
    )
    op.drop_table("disabled_workspace")
