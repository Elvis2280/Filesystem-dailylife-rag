from app.services.storage.workspace import create_workspace
from app.schemas.workspace import WorkspaceCreateRequest, WorkspaceResponse
from fastapi import APIRouter, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from fastapi.exceptions import HTTPException

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
        return workspace
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
