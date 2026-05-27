import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import WorkspaceLanguage, WorkspaceStatus
from app.core.logging import configure_logging
from app.models.disabled_workspace import DisabledWorkspace
from app.models.workspace import WorkspaceModel
from app.core.utility import generate_slug
from app.core.config import settings

logger = configure_logging("INFO")


class WorkspaceAlreadyDisabledError(Exception):
    pass


async def get_workspaces_tree_json(
    db_session: AsyncSession,
) -> dict[str, list[dict[str, str]]]:
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.status != WorkspaceStatus.DISABLED)
    )
    workspaces = result.scalars().all()

    entries = [{"display_name": w.display_name, "slug": w.slug} for w in workspaces]

    return {
        "english": entries,
        "japanese": entries,
    }


async def disable_workspace(
    slug: str, db_session: AsyncSession
) -> tuple[str, dict[str, list[dict[str, str]]]]:
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.slug == slug)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise ValueError("Workspace does not exist")
    if workspace.status == WorkspaceStatus.DISABLED:
        raise WorkspaceAlreadyDisabledError("Workspace is already disabled")

    base_dir = Path(settings.BRAIN_PATH)
    folder_langs: list[str] = []
    for lang in WorkspaceLanguage:
        if (base_dir / lang / slug).exists():
            folder_langs.append(lang.value)

    if not folder_langs:
        raise ValueError("Workspace folders do not exist")

    for lang in folder_langs:
        db_session.add(
            DisabledWorkspace(
                workspace_storage_key=workspace.storage_key,
                lang=lang,
                slug=slug,
            )
        )

    workspace.status = WorkspaceStatus.DISABLED
    workspace.disabled_at = datetime.now(timezone.utc)
    try:
        await db_session.commit()
        await db_session.refresh(workspace)
    except (IntegrityError, SQLAlchemyError) as e:
        await db_session.rollback()
        logger.error("Failed to disable workspace '%s': %s", slug, e)
        raise RuntimeError(f"Failed to disable workspace '{slug}'") from e

    tree = await get_workspaces_tree_json(db_session)
    return workspace.display_name, tree


async def create_workspace(
    workspace_name: str, db_session: AsyncSession
) -> WorkspaceModel:
    base_dir = Path(settings.BRAIN_PATH)
    slug = generate_slug(workspace_name)

    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.slug == slug)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.status == WorkspaceStatus.DISABLED:
            raise ValueError(f"Workspace '{workspace_name}' exists but is disabled")
        raise ValueError(f"Workspace '{workspace_name}' already exists")

    for lang in WorkspaceLanguage:
        workspace_dir = base_dir / lang / slug
        if workspace_dir.exists():
            raise ValueError(f"Workspace '{workspace_name}' already exists")

    for lang in WorkspaceLanguage:
        workspace_dir = base_dir / lang / slug
        workspace_dir.mkdir(parents=True, exist_ok=False)

    new_workspace = WorkspaceModel(
        display_name=workspace_name,
        slug=slug,
        storage_key=str(uuid.uuid4()),
    )

    try:
        db_session.add(new_workspace)
        await db_session.commit()
        await db_session.refresh(new_workspace)
        logger.info("Created workspace: %s (%s)", workspace_name, slug)
        return new_workspace
    except (IntegrityError, SQLAlchemyError, OSError) as e:
        await db_session.rollback()
        for lang in WorkspaceLanguage:
            workspace_dir = base_dir / lang / slug
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
