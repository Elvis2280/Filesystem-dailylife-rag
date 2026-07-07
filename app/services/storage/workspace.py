"""Workspace lifecycle management service.

Handles creation, disabling, and retrieval of workspaces. Each workspace
exists as a UUID-named directory under brain/workspaces/{uuid}/ with
subdirectories for files, translations, etc.
"""

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constant import WorkspaceStatus
from app.core.logging import configure_logging
from app.core.requirements_checker import ensure_workspace_dirs
from app.core.utility import generate_slug
from app.models.disabled_workspace import DisabledWorkspace
from app.models.workspace import WorkspaceModel

logger = configure_logging("INFO")

logger = configure_logging("INFO")


class WorkspaceAlreadyDisabledError(Exception):
    pass


async def _build_workspace_children(
    workspace_id: str, db_session: AsyncSession
) -> list[dict]:
    workspace_path = Path(settings.workspace_path(workspace_id))

    def _list_files(directory: Path) -> list[dict]:
        if not directory.exists() or not directory.is_dir():
            return []
        return [
            {"type": "file", "id": entry.name, "name": entry.name}
            for entry in sorted(directory.iterdir())
            if entry.is_file()
        ]

    files_dir = workspace_path / "files"
    translation_en_dir = workspace_path / "translation" / "english"
    translation_jp_dir = workspace_path / "translation" / "japanese"

    return [
        {
            "type": "folder",
            "name": "Files",
            "path": "files",
            "children": _list_files(files_dir),
        },
        {
            "type": "folder",
            "name": "Translation",
            "path": "translation",
            "children": [
                {
                    "type": "folder",
                    "name": "English",
                    "path": "translation/english",
                    "children": _list_files(translation_en_dir),
                },
                {
                    "type": "folder",
                    "name": "Japanese",
                    "path": "translation/japanese",
                    "children": _list_files(translation_jp_dir),
                },
            ],
        },
    ]


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
