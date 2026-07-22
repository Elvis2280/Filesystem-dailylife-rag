"""add_document_type_to_file_conversions

Revision ID: 701cb8d59932
Revises: b9429a3fa554
Create Date: 2026-07-22 16:42:26.318985
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "701cb8d59932"
down_revision: Union[str, None] = "b9429a3fa554"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "file_conversions",
        sa.Column("document_type", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_file_conversions_document_type",
        "file_conversions",
        ["document_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_conversions_document_type", table_name="file_conversions")
    op.drop_column("file_conversions", "document_type")
