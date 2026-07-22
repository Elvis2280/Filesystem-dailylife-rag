"""add_translations_table

Revision ID: b9429a3fa554
Revises: e2f3a4b5c6d7
Create Date: 2026-07-22 15:24:54.874875
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b9429a3fa554"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_translations_document_id"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_translations_workspace_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translations"),
        sa.UniqueConstraint(
            "document_id",
            "language",
            "file_path",
            name="uq_translation_doc_lang_path",
        ),
    )
    op.create_index("ix_translations_document_id", "translations", ["document_id"])
    op.create_index("ix_translations_workspace_id", "translations", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_translations_workspace_id", table_name="translations")
    op.drop_index("ix_translations_document_id", table_name="translations")
    op.drop_constraint("uq_translation_doc_lang_path", "translations", type_="unique")
    op.drop_table("translations")
