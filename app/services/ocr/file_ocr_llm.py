"""Image OCR using GLM-ocr vision model.

This module encapsulates OCR model selection and delegates execution to
the sync or async Ollama clients. Prompts are imported from
app.core.prompts to keep prompt engineering centralized.
"""

from pathlib import Path

from app.core.config import settings
from app.core.prompts import OCR_PROMPT
from app.services.ai.ollama_client import OllamaClient
from app.services.ai.ollama_sync import OllamaSyncClient


def extract_image_text(image_path: str | Path) -> str:
    """Extract text from image using GLM-ocr vision model (sync).

    Creates a fresh OllamaSyncClient and sends the image for
    vision-based text extraction with a detailed structural prompt
    optimized for document analysis.

    Args:
        image_path: Path to the image file (PNG, JPG, JPEG).

    Returns:
        Extracted raw text from the image.
    """
    client = OllamaSyncClient()
    return client.generate(
        model=settings.OLLAMA_MODEL_OCR,
        prompt=OCR_PROMPT,
        image=str(image_path),
        num_ctx=16384,
        num_predict=8192,
    )


async def extract_image_text_async(image_base64: str) -> str:
    """Extract text from image using GLM-ocr vision model (async).

    Creates a fresh OllamaClient and sends the base64-encoded image
    for vision-based text extraction with a simple verbatim prompt.

    Args:
        image_base64: Base64-encoded image string.

    Returns:
        Extracted raw text from the image.
    """
    client = OllamaClient()
    return await client.generate_async(
        model=settings.OLLAMA_MODEL_OCR,
        prompt=OCR_PROMPT,
        image_base64=image_base64,
    )
