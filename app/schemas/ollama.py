from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import StringConstraints

ModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class OllamaModelInfo(BaseModel):
    name: str
    size: int | None = None
    digest: str | None = None
    modified_at: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    eligible_roles: list[str] = Field(default_factory=list)
    selected_roles: list[str] = Field(default_factory=list)
    recommended_roles: list[str] = Field(default_factory=list)


class OllamaStatusResponse(BaseModel):
    """Ollama connectivity and installed model metadata."""

    is_reachable: bool = Field(
        ..., description="Whether the Ollama service is reachable"
    )
    available_models: list[str] = Field(
        ..., description="List of available Ollama models if reachable"
    )
    models: list[OllamaModelInfo] = Field(
        default_factory=list,
        description="Installed models with metadata and eligible roles",
    )
    selected_models: dict[str, str] = Field(
        default_factory=dict,
        description="Current model selection for each server role",
    )


class OllamaPreferencesResponse(BaseModel):
    ocr: str
    translation: str
    embedding: str
    answer: str
    formatting: str
    cleaning: str
    editable_roles: list[str] = Field(default_factory=list)


class OllamaPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocr: ModelName | None = None
    translation: ModelName | None = None
    answer: ModelName | None = None
    formatting: ModelName | None = None
    cleaning: ModelName | None = None


class OllamaModelPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelName
    destination: Literal[
        "ocr", "translation", "agent", "answer", "formatting", "cleaning"
    ]


class OllamaFileOcrResponse(BaseModel):
    """Response schema for Ollama OCR endpoint."""

    file_text: str = Field(..., description="The extracted text from the file")
    ollama_model: str = Field(..., description="The Ollama model used for OCR")
