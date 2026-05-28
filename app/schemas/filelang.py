from pydantic import BaseModel, Field


class FileLangRequest(BaseModel):
    workspace_id: str = Field(..., description="The workspace ID to process")


class FileLangResponse(BaseModel):
    workspace_id: str = Field(..., description="The workspace ID that was processed")
