from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1", tags=["workspace"])


@router.get("/workspace")
async def get_workspace():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "workspaces": [
                {
                    "id": "default",
                    "name": "Default Workspace",
                    "path": "/app/storage/uploads",
                }
            ]
        },
    )
