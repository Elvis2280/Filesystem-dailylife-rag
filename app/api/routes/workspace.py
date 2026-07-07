from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.workspace import (
    DisableWorkspaceResponse,
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
    try:
        workspace = await create_workspace(request.name, db)
        return WorkspaceResponse.model_validate(workspace)
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
    tree = await get_workspaces_tree_json(db)
    return WorkspaceTreeResponse(workspaces=tree)


@router.post(
    "/workspace/{workspace_id}/disable",
    response_model=DisableWorkspaceResponse,
    status_code=status.HTTP_200_OK,
)
async def disable_workspace_endpoint(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        name = await disable_workspace(workspace_id, db)
        return DisableWorkspaceResponse(
            message=f"Workspace '{name}' disabled successfully",
        )
    except WorkspaceAlreadyDisabledError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
