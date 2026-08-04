"""Workspace lifecycle management service.

Handles creation, disabling, and retrieval of workspaces. Each workspace
exists as a UUID-named directory under brain/workspaces/{uuid}/ with
subdirectories for files, translations, etc.
"""

import re
import shutil
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constant import DocumentsType, WorkspaceStatus
from app.core.logging import configure_logging
from app.core.requirements_checker import ensure_workspace_dirs
from app.core.utility import generate_slug
from app.models.disabled_workspace import DisabledWorkspace
from app.models.document import Document
from app.models.file_conversions import FileConversionModel
from app.models.workspace import WorkspaceModel

logger = configure_logging("INFO")


class WorkspaceAlreadyDisabledError(Exception):
    pass


async def _build_workspace_children(
    workspace_id: str, db_session: AsyncSession
) -> list[dict]:
    docs_result = await db_session.execute(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at, Document.original_filename)
    )
    documents = docs_result.scalars().all()

    if not documents:
        return _empty_workspace_tree(workspace_id)

    conversions = (
        (
            await db_session.execute(
                select(FileConversionModel).where(
                    FileConversionModel.file_id.in_([d.id for d in documents])
                )
            )
        )
        .scalars()
        .all()
    )

    by_doc: dict[str, list[FileConversionModel]] = defaultdict(list)
    for c in conversions:
        by_doc[str(c.file_id)].append(c)

    doc_name_map = {str(d.id): d.original_filename for d in documents}

    document_nodes = []
    seen_counts: dict[str, int] = {}
    for doc in documents:
        doc_id_str = str(doc.id)
        doc_convs = by_doc.get(doc_id_str, [])
        children = _build_doc_children(doc_convs, doc.original_filename)
        seen = seen_counts.get(doc.original_filename, 0)
        name = (
            f"{doc.original_filename}_({seen})" if seen > 0 else doc.original_filename
        )
        seen_counts[doc.original_filename] = seen + 1
        document_nodes.append(
            {
                "type": "folder",
                "id": doc_id_str,
                "name": name,
                "path": None,
                "original_name": doc.original_filename,
                "status": doc.status,
                "language": doc.language,
                "mime_type": doc.mime_type,
                "page_count": doc.page_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "children": children,
            }
        )

    en_nodes, ja_nodes = _translation_nodes(by_doc, doc_name_map)

    workspace_path = Path(settings.workspace_path(workspace_id))
    _log_orphan_warnings(workspace_id, workspace_path, documents, conversions)

    return [
        {
            "type": "folder",
            "id": f"{workspace_id}::files",
            "name": "Files",
            "path": "files",
            "children": document_nodes,
        },
        {
            "type": "folder",
            "id": f"{workspace_id}::translation",
            "name": "Translation",
            "path": "translation",
            "children": [
                {
                    "type": "folder",
                    "id": f"{workspace_id}::translation/english",
                    "name": "English",
                    "path": "translation/english",
                    "children": en_nodes,
                },
                {
                    "type": "folder",
                    "id": f"{workspace_id}::translation/japanese",
                    "name": "Japanese",
                    "path": "translation/japanese",
                    "children": ja_nodes,
                },
            ],
        },
    ]


def _empty_workspace_tree(workspace_id: str) -> list[dict]:
    return [
        {
            "type": "folder",
            "id": f"{workspace_id}::files",
            "name": "Files",
            "path": "files",
            "children": [],
        },
        {
            "type": "folder",
            "id": f"{workspace_id}::translation",
            "name": "Translation",
            "path": "translation",
            "children": [
                {
                    "type": "folder",
                    "id": f"{workspace_id}::translation/english",
                    "name": "English",
                    "path": "translation/english",
                    "children": [],
                },
                {
                    "type": "folder",
                    "id": f"{workspace_id}::translation/japanese",
                    "name": "Japanese",
                    "path": "translation/japanese",
                    "children": [],
                },
            ],
        },
    ]


def _page_number_from_path(path: str) -> int | None:
    m = re.search(r"_page_(\d+)\.md$", path)
    return int(m.group(1)) if m else None


def _build_doc_children(
    convs: list[FileConversionModel],
    original_name: str,
) -> list[dict]:
    out = []
    pdf_rows = [
        c
        for c in convs
        if c.document_type
        in (DocumentsType.ORIGINAL_FILE.value, DocumentsType.CONVERTED_PDF.value)
    ]
    pdf_rows.sort(key=lambda c: c.created_at or datetime.min)
    for c in pdf_rows:
        ext = c.converted_to_extension or ""
        out.append(
            {
                "type": "file",
                "id": str(c.id),
                "name": f"{original_name}.{ext}" if ext else original_name,
                "original_name": original_name,
                "document_id": str(c.file_id),
                "kind": "pdf",
                "page_number": None,
                "mime_type": c.converted_mime_type,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )

    md_rows = [c for c in convs if c.document_type == DocumentsType.MD_ORIGINAL.value]
    md_rows.sort(key=lambda c: _page_number_from_path(c.converted_file_path) or 0)
    for c in md_rows:
        ext = c.converted_to_extension or ""
        out.append(
            {
                "type": "document",
                "id": str(c.id),
                "name": f"{original_name}.{ext}" if ext else original_name,
                "original_name": original_name,
                "document_id": str(c.file_id),
                "kind": "markdown",
                "page_number": _page_number_from_path(c.converted_file_path),
                "mime_type": c.converted_mime_type,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )
    return out


def _translation_nodes(
    by_doc: dict[str, list[FileConversionModel]],
    doc_name_map: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    en_groups: dict[str, list[FileConversionModel]] = defaultdict(list)
    ja_groups: dict[str, list[FileConversionModel]] = defaultdict(list)

    for doc_id_str, convs in by_doc.items():
        for c in convs:
            if c.document_type != DocumentsType.MD_TRANSLATED.value:
                continue
            if "/translation/english/" in c.converted_file_path:
                en_groups[doc_id_str].append(c)
            elif "/translation/japanese/" in c.converted_file_path:
                ja_groups[doc_id_str].append(c)

    en_nodes = _build_lang_nodes(en_groups, doc_name_map, "en")
    ja_nodes = _build_lang_nodes(ja_groups, doc_name_map, "ja")
    return en_nodes, ja_nodes


def _build_lang_nodes(
    groups: dict[str, list[FileConversionModel]],
    doc_name_map: dict[str, str],
    lang: str,
) -> list[dict]:
    nodes = []
    for doc_id_str, convs in groups.items():
        if not convs:
            continue
        last = max((c.created_at for c in convs if c.created_at), default=None)
        original_name = doc_name_map.get(doc_id_str, doc_id_str)
        nodes.append(
            {
                "type": "file",
                "id": f"{doc_id_str}:{lang}",
                "name": f"{original_name}.md",
                "original_name": original_name,
                "document_id": doc_id_str,
                "kind": "markdown",
                "language": lang,
                "page_count": len(convs),
                "created_at": last.isoformat() if last else None,
            }
        )
    nodes.sort(key=lambda n: n["name"])
    return nodes


def _is_orphan_for_known_doc(filename: str, existing_ids: set[str]) -> bool:
    m = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        filename,
        re.IGNORECASE,
    )
    if m is None:
        return False
    return m.group(1) in existing_ids


def _log_orphan_warnings(
    workspace_id: str,
    workspace_path: Path,
    documents: list[Document],
    conversions: list[FileConversionModel],
) -> None:
    existing_doc_ids = {str(d.id) for d in documents}

    files_dir = workspace_path / "files"
    if files_dir.is_dir():
        tracked_types = {
            DocumentsType.ORIGINAL_FILE.value,
            DocumentsType.CONVERTED_PDF.value,
            DocumentsType.MD_ORIGINAL.value,
        }
        tracked_exts = {"pdf", "txt", "md"}
        expected_filenames = {
            Path(c.converted_file_path).name
            for c in conversions
            if c.document_type in tracked_types
            or c.converted_to_extension in tracked_exts
        }
        expected_filenames |= {
            doc.stored_filename for doc in documents if doc.stored_filename
        }
        on_disk = {f.name for f in files_dir.iterdir() if f.is_file()}
        orphans = {
            f
            for f in (on_disk - expected_filenames)
            if not _is_orphan_for_known_doc(f, existing_doc_ids)
        }
        if orphans:
            logger.warning(
                "Workspace %s has %d orphan files in files/: %s",
                workspace_id,
                len(orphans),
                sorted(orphans),
            )

    for lang_subdir, lang_path_segment in [
        ("english", "/translation/english/"),
        ("japanese", "/translation/japanese/"),
    ]:
        trans_dir = workspace_path / "translation" / lang_subdir
        if not trans_dir.is_dir():
            continue
        expected_paths = {
            c.converted_file_path
            for c in conversions
            if c.document_type == DocumentsType.MD_TRANSLATED.value
            and lang_path_segment in c.converted_file_path
        }
        on_disk = {str(f) for f in trans_dir.iterdir() if f.is_file()}
        orphans = {
            p
            for p in (on_disk - expected_paths)
            if not _is_orphan_for_known_doc(Path(p).name, existing_doc_ids)
        }
        if orphans:
            logger.warning(
                "Workspace %s has %d orphan files in translation/%s/: %s",
                workspace_id,
                len(orphans),
                lang_subdir,
                sorted(orphans),
            )


async def get_workspaces_tree_json(
    db_session: AsyncSession,
) -> list[dict]:
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.status == WorkspaceStatus.ACTIVE)
    )
    workspaces = result.scalars().all()

    tree = []
    for w in workspaces:
        children = await _build_workspace_children(str(w.id), db_session)
        tree.append(
            {
                "id": str(w.id),
                "name": w.name,
                "status": w.status,
                "children": children,
            }
        )

    return tree


async def disable_workspace(workspace_id: str, db_session: AsyncSession) -> str:
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise ValueError("Workspace does not exist")
    if workspace.status == WorkspaceStatus.DISABLED:
        raise WorkspaceAlreadyDisabledError("Workspace is already disabled")

    workspace_root = Path(settings.workspace_path(str(workspace.id)))
    folder_exists = workspace_root.exists()

    if folder_exists:
        db_session.add(
            DisabledWorkspace(
                workspace_storage_key=workspace.storage_key,
                lang="all",
                slug=workspace.slug,
            )
        )

    workspace.status = WorkspaceStatus.DISABLED
    workspace.disabled_at = datetime.now(timezone.utc)
    try:
        await db_session.commit()
        await db_session.refresh(workspace)
    except (IntegrityError, SQLAlchemyError) as e:
        await db_session.rollback()
        logger.error("Failed to disable workspace '%s': %s", workspace_id, e)
        raise RuntimeError(f"Failed to disable workspace '{workspace_id}'") from e

    return workspace.name


async def create_workspace(
    workspace_name: str, db_session: AsyncSession
) -> WorkspaceModel:
    base_dir = Path(settings.BRAIN_WORKSPACES_PATH)
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

    workspace_dir = base_dir / str(workspace_id)
    if workspace_dir.exists():
        raise ValueError(f"Workspace '{workspace_name}' already exists")

    try:
        workspace_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ValueError(f"Workspace '{workspace_name}' already exists")

    created = ensure_workspace_dirs(str(workspace_id))
    logger.info("Created workspace directories: %s", created)

    new_workspace = WorkspaceModel(
        id=workspace_id,
        name=workspace_name,
        slug=slug,
        storage_key=str(uuid.uuid4()),
    )

    try:
        db_session.add(new_workspace)
        await db_session.commit()
        await db_session.refresh(new_workspace)
        logger.info("Created workspace: %s (%s)", workspace_name, str(workspace_id))
        return new_workspace
    except (IntegrityError, SQLAlchemyError, OSError) as e:
        await db_session.rollback()

        if workspace_dir.exists():
            try:
                shutil.rmtree(workspace_dir, ignore_errors=True)
            except Exception as cleanup_error:
                logger.error(
                    "Failed to clean up workspace directory %s: %s",
                    workspace_dir,
                    cleanup_error,
                )
        logger.error("Failed to create workspace '%s': %s", workspace_name, e)
        raise RuntimeError(f"Failed to create workspace '{workspace_name}'") from e
