"""rename files table to documents, update schema

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename the table
    op.rename_table("files", "documents")

    # Drop obsolete columns
    op.drop_column("documents", "storage_path")
    op.drop_column("documents", "file_size")
    op.drop_column("documents", "file_extension")
    op.drop_column("documents", "extracted_text")
    op.drop_column("documents", "detected_language")
    op.drop_column("documents", "processed_at")

    # Rename uploaded_at → created_at
    op.alter_column("documents", "uploaded_at", new_column_name="created_at")

    # Add new columns
    op.add_column(
        "documents",
        sa.Column("stored_filename", sa.String(length=255), nullable=True),
    )
    op.execute(
        "UPDATE documents SET stored_filename = "
        "LOWER(SUBSTRING(original_filename FROM '\\.([^.]+)$'))"
    )
    op.execute(
        "UPDATE documents SET stored_filename = "
        "id::text || '_original.' || stored_filename "
        "WHERE stored_filename IS NOT NULL"
    )
    op.execute(
        "UPDATE documents SET stored_filename = "
        "id::text || '_original' "
        "WHERE stored_filename IS NULL"
    )
    op.alter_column("documents", "stored_filename", nullable=False)

    op.add_column(
        "documents",
        sa.Column("language", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )

    # Update the FK in file_conversions to point to documents
    # We can't ALTER the FK constraint inline easily, so drop and recreate
    op.drop_constraint(
        "file_conversions_file_id_fkey", "file_conversions", type_="foreignkey"
    )
    op.create_foreign_key(
        "file_conversions_file_id_fkey",
        "file_conversions",
        "documents",
        ["file_id"],
        ["id"],
    )


def downgrade() -> None:
    # Revert FK
    op.drop_constraint(
        "file_conversions_file_id_fkey", "file_conversions", type_="foreignkey"
    )
    op.create_foreign_key(
        "file_conversions_file_id_fkey",
        "file_conversions",
        "files",
        ["file_id"],
        ["id"],
    )

    # Drop new columns
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "language")
    op.drop_column("documents", "stored_filename")

    # Rename back
    op.alter_column("documents", "created_at", new_column_name="uploaded_at")

    # Restore dropped columns
    op.add_column(
        "documents",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("detected_language", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("extracted_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "file_extension", sa.String(length=20), nullable=False, server_default=""
        ),
    )
    op.alter_column("documents", "file_extension", server_default=None)
    op.add_column(
        "documents",
        sa.Column(
            "file_size", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.alter_column("documents", "file_size", server_default=None)
    op.add_column(
        "documents",
        sa.Column(
            "storage_path", sa.String(length=500), nullable=False, server_default=""
        ),
    )
    op.alter_column("documents", "storage_path", server_default=None)

    # Rename table back
    op.rename_table("documents", "files")
