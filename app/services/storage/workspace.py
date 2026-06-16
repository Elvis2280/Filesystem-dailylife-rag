"""Workspace lifecycle management service.

Handles creation, disabling, and retrieval of workspaces. Each workspace
exists as a bilingual directory structure under brain/english/{slug}/
and brain/japanese/{slug}/, backed by a Postgres record.

Key workflows:
    - create_workspace: Validates uniqueness, creates directories, inserts DB row
    - disable_workspace: Marks workspace as disabled, logs disabled workspace records
    - get_workspaces_tree_json: Returns active workspaces as JSON for API responses
"""

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constant import WorkspaceLanguage, WorkspaceStatus
from app.core.logging import configure_logging
from app.core.utility import generate_slug
from app.models.disabled_workspace import DisabledWorkspace
from app.models.workspace import WorkspaceModel

logger = configure_logging("INFO")


class WorkspaceAlreadyDisabledError(Exception):
    """Raised when attempting to disable an already-disabled workspace."""

    pass


async def get_workspaces_tree_json(
    db_session: AsyncSession,
) -> dict[str, list[dict[str, str]]]:
    """Retrieve all active workspaces as a JSON-serializable tree.

    Queries Postgres for workspaces not marked as DISABLED and returns
    them grouped by language (english/japanese). Both language groups
    contain identical workspace lists since each workspace exists in
    both languages.

    Args:
        db_session: Async SQLAlchemy session.

    Returns:
        Dictionary with 'english' and 'japanese' keys, each mapping to
        a list of workspace dicts containing display_name, slug, and
        workspace_id.
    """
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.status == WorkspaceStatus.ACTIVE)
    )
    workspaces = result.scalars().all()

    entries = [
        {
            "display_name": w.display_name,
            "slug": w.slug,
            "workspace_storage_key": w.storage_key,
        }
        for w in workspaces
    ]

    return {
        "english": entries,
        "japanese": entries,
    }


async def disable_workspace(
    slug: str, db_session: AsyncSession
) -> tuple[str, dict[str, list[dict[str, str]]]]:
    """Disable a workspace by marking it in Postgres and logging audit records.

    A workspace is soft-disabled: its database status is set to DISABLED
    and DisabledWorkspace audit records are created for each language
    directory that exists on disk. Files remain on disk for possible
    re-enablement.

    Args:
        slug: URL-friendly workspace identifier.
        db_session: Async SQLAlchemy session.

    Returns:
        Tuple of (workspace display name, updated workspace tree JSON).

    Raises:
        ValueError: If the workspace does not exist or has no folders on disk.
        WorkspaceAlreadyDisabledError: If the workspace is already disabled.
        RuntimeError: If the database transaction fails.
    """
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.slug == slug)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise ValueError("Workspace does not exist")
    if workspace.status == WorkspaceStatus.DISABLED:
        raise WorkspaceAlreadyDisabledError("Workspace is already disabled")

    # Determine which language directories exist on disk to create audit records
    base_dir = Path(settings.BRAIN_PATH)
    folder_langs: list[str] = []
    for lang in WorkspaceLanguage:
        if (base_dir / lang / slug).exists():
            folder_langs.append(lang.value)

    if not folder_langs:
        raise ValueError("Workspace folders do not exist")

    # Create a DisabledWorkspace audit record per language directory
    for lang in folder_langs:
        db_session.add(
            DisabledWorkspace(
                workspace_storage_key=workspace.storage_key,
                lang=lang,
                slug=slug,
            )
        )

    # Mark the workspace as disabled in the main table
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
    """Create a new bilingual workspace with directories and database record.

    Performs the following in order:
    1. Generates a URL-friendly slug from the display name.
    2. Validates the slug is not already in use (including disabled ones).
    3. Checks that no directory collision exists on disk.
    4. Creates brain/{lang}/{slug}/ directories for each supported language.
    5. Inserts a WorkspaceModel row in Postgres.

    If any step fails, created directories are cleaned up and the
    database transaction is rolled back.

    Args:
        workspace_name: Human-readable workspace display name.
        db_session: Async SQLAlchemy session.

    Returns:
        The newly created WorkspaceModel instance (refreshed from DB).

    Raises:
        ValueError: If the workspace already exists (active or disabled).
        RuntimeError: If the database insert or directory creation fails.
    """
    base_dir = Path(settings.BRAIN_PATH)
    slug = generate_slug(workspace_name)

    # --- Uniqueness validation ---
    # Check both active and disabled workspaces to prevent slug collisions
    result = await db_session.execute(
        select(WorkspaceModel).where(WorkspaceModel.slug == slug)
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.status == WorkspaceStatus.DISABLED:
            raise ValueError(f"Workspace '{workspace_name}' exists but is disabled")
        raise ValueError(f"Workspace '{workspace_name}' already exists")

    # Defense in depth: also verify no directory collision on disk
    for lang in WorkspaceLanguage:
        workspace_dir = base_dir / lang / slug
        if workspace_dir.exists():
            raise ValueError(f"Workspace '{workspace_name}' already exists")

    # --- Create bilingual directory structure ---
    # Both language directories must be created before the DB insert
    for lang in WorkspaceLanguage:
        workspace_dir = base_dir / lang / slug
        try:
            workspace_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise ValueError(f"Workspace '{workspace_name}' already exists")

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
        # Transaction rollback
        await db_session.rollback()

        # Clean up directories that were created before the failure
        # Best-effort cleanup: log errors but don't propagate them
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
