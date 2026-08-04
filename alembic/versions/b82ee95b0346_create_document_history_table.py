"""create_document_history_table

Revision ID: b82ee95b0346
Revises: 701cb8d59932
Create Date: 2026-07-22 18:55:43.256557
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b82ee95b0346"
down_revision: Union[str, None] = "701cb8d59932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("step", sa.String(length=10), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_history_document_id"),
        "document_history",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_history_document_id"), table_name="document_history"
    )
    op.drop_table("document_history")
