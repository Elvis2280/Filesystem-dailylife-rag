from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.workspace import (
    DeleteWorkspaceResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
    WorkspaceTreeResponse,
)
from app.services.storage.workspace import (
    WorkspaceAlreadyDisabledError,
    create_workspace,
    disable_workspace,
    get_workspaces_tree_json,
)

router = APIRouter(prefix="/api/v1", tags=["workspace"])


@router.post(
    "/workspace",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_endpoint(
    request: WorkspaceCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new bilingual workspace with directories and database record."""
    try:
        workspace = await create_workspace(request.name, db)
        tree = await get_workspaces_tree_json(db)
        response = WorkspaceResponse.model_validate(workspace)
        response.tree = tree
        return response
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get(
    "/workspace/tree",
    response_model=WorkspaceTreeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_workspace_tree_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all active workspaces grouped by language."""
    tree = await get_workspaces_tree_json(db)
    return WorkspaceTreeResponse(tree=tree)


@router.delete(
    "/workspace/{slug}",
    response_model=DeleteWorkspaceResponse,
    status_code=status.HTTP_200_OK,
)
async def disable_workspace_endpoint(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Soft-disable a workspace by marking it in the database."""
    try:
        display_name, tree = await disable_workspace(slug, db)
        return DeleteWorkspaceResponse(
            message=f"Workspace '{display_name}' disabled successfully",
            tree=tree,
        )
    except WorkspaceAlreadyDisabledError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
