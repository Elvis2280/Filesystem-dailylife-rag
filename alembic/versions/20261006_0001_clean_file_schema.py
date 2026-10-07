"""Create the clean workspace file schema.

Revision ID: 20261006_0001
Revises:
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261006_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
        sa.UniqueConstraint("storage_key", name="uq_workspaces_storage_key"),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "file_role", sa.String(length=30), server_default="original", nullable=False
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "storage_area",
            sa.String(length=20),
            server_default="workspace",
            nullable=False,
        ),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_extension", sa.String(length=20), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("size", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="file_uploaded",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size >= 0", name="ck_documents_size_nonnegative"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_documents_attempt_nonnegative"
        ),
        sa.CheckConstraint(
            "file_role IN ('original', 'converted_pdf')", name="ck_documents_file_role"
        ),
        sa.CheckConstraint(
            "storage_area IN ('workspace', 'temp')", name="ck_documents_storage_area"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_documents_id_workspace"),
        sa.UniqueConstraint(
            "parent_document_id", "file_role", name="uq_documents_parent_role"
        ),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index(
        "ix_documents_parent_document_id", "documents", ["parent_document_id"]
    )
    op.create_index(
        "ix_documents_workspace_status", "documents", ["workspace_id", "status"]
    )
    op.create_index(
        "uq_documents_workspace_original_checksum",
        "documents",
        ["workspace_id", "checksum_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "file_role = 'original' AND checksum_sha256 IS NOT NULL"
        ),
    )

    op.create_table(
        "document_splits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(length=50), server_default="image_ready", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("ocr_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("ocr_size", sa.BigInteger(), nullable=True),
        sa.Column("markdown_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("markdown_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("page_number >= 1", name="ck_document_splits_page_positive"),
        sa.CheckConstraint("size >= 0", name="ck_document_splits_size_nonnegative"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_document_splits_attempt_nonnegative"
        ),
        sa.CheckConstraint(
            "ocr_size IS NULL OR ocr_size >= 0",
            name="ck_document_splits_ocr_size_nonnegative",
        ),
        sa.CheckConstraint(
            "markdown_size IS NULL OR markdown_size >= 0",
            name="ck_document_splits_markdown_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "workspace_id", name="uq_document_splits_id_workspace"
        ),
        sa.UniqueConstraint(
            "document_id", "page_number", name="uq_document_split_page"
        ),
        sa.UniqueConstraint(
            "document_id", "storage_key", name="uq_document_split_path"
        ),
    )
    op.create_index(
        "ix_document_splits_workspace_id", "document_splits", ["workspace_id"]
    )
    op.create_index(
        "ix_document_splits_document_id", "document_splits", ["document_id"]
    )
    op.create_index(
        "ix_document_splits_workspace_status",
        "document_splits",
        ["workspace_id", "status"],
    )

    op.create_table(
        "translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_split_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(length=50), server_default="completed", nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size >= 0", name="ck_translations_size_nonnegative"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_translations_attempt_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_split_id", "workspace_id"],
            ["document_splits.id", "document_splits.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_split_id", "language", name="uq_translations_split_language"
        ),
        sa.UniqueConstraint("id", "workspace_id", name="uq_translations_id_workspace"),
    )
    op.create_index("ix_translations_workspace_id", "translations", ["workspace_id"])
    op.create_index(
        "ix_translations_document_split_id", "translations", ["document_split_id"]
    )
    op.create_index(
        "ix_translations_workspace_status", "translations", ["workspace_id", "status"]
    )

    op.create_table(
        "document_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_split_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("translation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("step", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_split_id", "workspace_id"],
            ["document_splits.id", "document_splits.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["translation_id", "workspace_id"],
            ["translations.id", "translations.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_events_workspace_id", "document_events", ["workspace_id"]
    )
    op.create_index(
        "ix_document_events_document_id", "document_events", ["document_id"]
    )
    op.create_index(
        "ix_document_events_document_split_id", "document_events", ["document_split_id"]
    )
    op.create_index(
        "ix_document_events_translation_id", "document_events", ["translation_id"]
    )


def downgrade() -> None:
    op.drop_table("document_events")
    op.drop_table("translations")
    op.drop_table("document_splits")
    op.drop_table("documents")
    op.drop_table("workspaces")
