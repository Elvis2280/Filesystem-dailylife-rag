"""Sandbox endpoints for testing Ollama models in isolation.

These routes are only mounted when IS_DEVELOPMENT is True.
They are not part of the main application flow.
"""

import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies.validators import validate_image_type
from app.core.config import settings
from app.schemas.ollama import OllamaFileOcrResponse, OllamaStatusResponse
from app.services.ai.ollama_client import OllamaClient, get_ollama_client
from app.services.ocr.file_ocr_llm import extract_image_text_async

router = APIRouter(prefix="/ollama", tags=["Ollama"])


@router.get(
    "/status", response_model=OllamaStatusResponse, status_code=status.HTTP_200_OK
)
async def ollama_status(ollama: OllamaClient = Depends(get_ollama_client)):
    """Endpoint to check Ollama service status."""
    health_status = await ollama.health_check()
    if health_status.is_reachable:
        return OllamaStatusResponse(
            is_reachable=True,
            available_models=health_status.available_models,
        )
    else:
        return OllamaStatusResponse(
            is_reachable=False,
            available_models=[],
        )


@router.post(
    "/ocr", response_model=OllamaFileOcrResponse, status_code=status.HTTP_200_OK
)
async def ollama_ocr(
    file: UploadFile = File(...),
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Endpoint to perform OCR on an uploaded Image using Ollama."""
    health_status = await ollama.health_check()
    if not health_status.is_reachable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama server is not reachable",
        )

    validate_image_type(file)

    file_received = await file.read()
    image_base64 = base64.b64encode(file_received).decode("utf-8")

    try:
        ocr_result = await extract_image_text_async(image_base64)
        return OllamaFileOcrResponse(
            file_text=ocr_result,
            ollama_model=settings.OLLAMA_MODEL_OCR,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
