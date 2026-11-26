"""Workspace lifecycle and filesystem tree services."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import WorkspaceStatus
from app.core.logging import configure_logging
from app.core.utility import generate_slug
from app.models.document import Document
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.services.storage.file_metadata import workspace_object_prefix

logger = configure_logging("INFO")


class WorkspaceAlreadyDisabledError(Exception):
    pass


def _artifact_file_node(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "name": document.original_filename,
        "file_role": document.file_role,
        "path": document.storage_key,
        "status": document.status,
        "mime_type": document.mime_type,
        "created_at": document.created_at,
    }


def _page_image_node(split: DocumentSplitModel) -> dict[str, Any]:
    return {
        "id": str(split.id),
        "name": split.filename,
        "document_id": str(split.document_id),
        "page_number": split.page_number,
        "path": split.storage_key,
        "status": split.status,
        "mime_type": split.file_type,
    }


async def _build_workspace_files(
    workspace_id: str, db_session: AsyncSession
) -> list[dict[str, Any]]:
    documents = (
        (
            await db_session.execute(
                select(Document)
                .where(Document.workspace_id == workspace_id)
                .order_by(Document.created_at, Document.original_filename)
            )
        )
        .scalars()
        .all()
    )
    if not documents:
        return []

    roots = sorted(
        (document for document in documents if document.parent_document_id is None),
        key=lambda document: (
            document.created_at,
            document.original_filename.casefold(),
            str(document.id),
        ),
    )
    documents_by_parent: dict[str, list[Document]] = defaultdict(list)
    for document in documents:
        if document.parent_document_id:
            documents_by_parent[str(document.parent_document_id)].append(document)

    split_rows = (
        (
            await db_session.execute(
                select(DocumentSplitModel).where(
                    DocumentSplitModel.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    translations = (
        (
            await db_session.execute(
                select(TranslationModel).where(
                    TranslationModel.workspace_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    document_map = {str(document.id): document for document in documents}
    root_id_by_document: dict[str, str] = {}
    for document in documents:
        document_id = str(document.id)
        parent_id = (
            str(document.parent_document_id) if document.parent_document_id else None
        )
        root_id_by_document[document_id] = (
            parent_id if parent_id in document_map else document_id
        )

    pages_by_root: dict[str, list[DocumentSplitModel]] = defaultdict(list)
    splits_by_id = {str(split.id): split for split in split_rows}
    for split in split_rows:
        root_id = root_id_by_document.get(str(split.document_id))
        if root_id is not None:
            pages_by_root[root_id].append(split)

    translations_by_root: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"japanese": [], "english": []}
    )
    language_names = {"JP": "japanese", "EN": "english"}
    for translation in translations:
        split = splits_by_id.get(str(translation.document_split_id))
        language_name = language_names.get(translation.language.upper())
        if split is None or language_name is None:
            continue
        root_id = root_id_by_document.get(str(split.document_id))
        if root_id is None:
            continue
        translations_by_root[root_id][language_name].append(
            {
                "id": str(translation.id),
                "name": translation.filename,
                "language": translation.language.upper(),
                "page_number": split.page_number,
                "path": translation.storage_key,
                "status": translation.status,
                "mime_type": translation.file_type,
                "created_at": translation.created_at,
            }
        )

    files: list[dict[str, Any]] = []
    for root in roots:
        root_id = str(root.id)
        converted_files = sorted(
            documents_by_parent.get(root_id, []),
            key=lambda document: (
                document.file_role,
                document.created_at,
                str(document.id),
            ),
        )
        pages = sorted(
            pages_by_root.get(root_id, []),
            key=lambda split: (split.page_number, str(split.id)),
        )
        file_translations = translations_by_root[root_id]
        for language_files in file_translations.values():
            language_files.sort(key=lambda node: (node["page_number"], node["id"]))

        files.append(
            {
                "id": root_id,
                "name": root.original_filename,
                "status": root.status,
                "language": root.language,
                "mime_type": root.mime_type,
                "page_count": root.page_count,
                "created_at": root.created_at,
                "original_files": [
                    _artifact_file_node(root),
                    *(_artifact_file_node(document) for document in converted_files),
                ],
                "translations": file_translations,
                "pages": [_page_image_node(split) for split in pages],
            }
        )

    return files


async def get_workspaces_tree_json(
    db_session: AsyncSession,
) -> list[dict[str, Any]]:
    result = await db_session.execute(
        select(WorkspaceModel)
        .where(WorkspaceModel.status == WorkspaceStatus.ACTIVE)
        .order_by(WorkspaceModel.name, WorkspaceModel.created_at, WorkspaceModel.id)
    )
    workspaces = result.scalars().all()
    return [
        {
            "id": str(workspace.id),
            "name": workspace.name,
            "status": workspace.status,
            "files": await _build_workspace_files(str(workspace.id), db_session),
        }
        for workspace in workspaces
    ]


async def list_workspaces(db_session: AsyncSession) -> list[WorkspaceModel]:
    result = await db_session.execute(
        select(WorkspaceModel)
        .where(WorkspaceModel.status == WorkspaceStatus.ACTIVE)
        .order_by(WorkspaceModel.name, WorkspaceModel.created_at)
    )
    return list(result.scalars().all())


async def disable_workspace(workspace_id: str, db_session: AsyncSession) -> str:
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise ValueError("Workspace does not exist")
    if workspace.status == WorkspaceStatus.DISABLED:
        raise WorkspaceAlreadyDisabledError("Workspace is already disabled")

    workspace.status = WorkspaceStatus.DISABLED
    workspace.disabled_at = datetime.now(timezone.utc)
    try:
        await db_session.commit()
        await db_session.refresh(workspace)
    except (IntegrityError, SQLAlchemyError) as exc:
        await db_session.rollback()
        logger.error("Failed to disable workspace '%s': %s", workspace_id, exc)
        raise RuntimeError(f"Failed to disable workspace '{workspace_id}'") from exc
    return workspace.name


async def create_workspace(
    workspace_name: str, db_session: AsyncSession
) -> WorkspaceModel:
    slug = generate_slug(workspace_name)
    workspace_id = uuid.uuid4()

    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.slug == slug)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.status == WorkspaceStatus.DISABLED:
            raise ValueError(f"Workspace '{workspace_name}' exists but is disabled")
        raise ValueError(f"Workspace '{workspace_name}' already exists")

    try:
        new_workspace = WorkspaceModel(
            id=workspace_id,
            name=workspace_name,
            slug=slug,
            storage_key=workspace_object_prefix(workspace_id),
        )
        db_session.add(new_workspace)
        await db_session.commit()
        await db_session.refresh(new_workspace)
        return new_workspace
    except (IntegrityError, SQLAlchemyError) as exc:
        await db_session.rollback()
        logger.error("Failed to create workspace '%s': %s", workspace_name, exc)
        raise RuntimeError(f"Failed to create workspace '{workspace_name}'") from exc
