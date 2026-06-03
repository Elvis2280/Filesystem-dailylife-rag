from pydantic import BaseModel, Field


class OllamaStatusResponse(BaseModel):
    is_reachable: bool = Field(
        ..., description="Whether the Ollama service is reachable"
    )
    available_models: list[str] = Field(
        ..., description="List of available Ollama models if reachable"
    )


class OllamaFileOcrResponse(BaseModel):
    file_text: str = Field(..., description="The extracted text from the file")
    ollama_model: str = Field(..., description="The Ollama model used for OCR")
