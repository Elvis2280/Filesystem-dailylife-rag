import shutil
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import WorkspaceLanguage
from app.core.logging import configure_logging
from app.models.workspace import WorkspaceModel
from app.core.utility import generate_slug
from app.core.config import settings

logger = configure_logging("INFO")


async def create_workspace(
    workspace_name: str, db_session: AsyncSession
) -> WorkspaceModel:
    """Create a new workspace with filesystem directories and database record."""
    base_dir = Path(settings.BRAIN_PATH)
    slug = generate_slug(workspace_name)

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
