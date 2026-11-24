"""Image OCR using GLM-ocr vision model.

This module encapsulates OCR model selection and delegates execution to
the sync or async Ollama clients. Prompts are imported from
app.core.prompts to keep prompt engineering centralized.
"""

import logging
from pathlib import Path
from time import perf_counter

from PIL import Image

from app.core.prompts import OCR_PROMPT
from app.services.ai.model_preferences import (
    ModelRole,
    get_model_name_async,
    get_model_name_sync,
)
from app.services.ai.ollama_client import OllamaClient
from app.services.ai.ollama_sync import OllamaSyncClient

logger = logging.getLogger("memory_rag.ocr")
NATIVE_OCR_PROMPT = "Text Recognition:"


def is_glm_ocr_model_selected() -> bool:
    """Return whether the shared OCR preference selects GLM-OCR."""
    model = get_model_name_sync(ModelRole.OCR)
    model_name = model.rsplit("/", 1)[-1].split(":", 1)[0]
    return model_name.casefold() == "glm-ocr"


def extract_image_text(
    image_path: str | Path,
    *,
    document_id: str | None = None,
    page_number: int | None = None,
    attempt: int = 1,
    prompt: str | None = None,
    num_predict: int = 8192,
) -> str:
    """Extract text from image using GLM-ocr vision model (sync).

    Creates a fresh OllamaSyncClient and sends the image for
    vision-based text extraction with a detailed structural prompt
    optimized for document analysis.

    Args:
        image_path: Path to the image file (PNG, JPG, JPEG).

    Returns:
        Extracted raw text from the image.
    """
    context = "document=%s page=%s attempt=%d"
    identifiers = (document_id, page_number, attempt)
    prompt_text = prompt or OCR_PROMPT
    prompt_mode = "native" if prompt == NATIVE_OCR_PROMPT else "detailed"
    started = perf_counter()
    try:
        model = get_model_name_sync(ModelRole.OCR)
        with Image.open(image_path) as image:
            width, height = image.size
        logger.info(
            "OCR request " + context + " image=%s dimensions=%dx%d model=%s "
            "prompt_mode=%s num_ctx=16384 num_predict=%d temperature=0 stream=False think=False",
            *identifiers,
            str(image_path),
            width,
            height,
            model,
            prompt_mode,
            num_predict,
        )
        client = OllamaSyncClient()
        text = client.generate(
            model=model,
            prompt=prompt_text,
            image=str(image_path),
            num_ctx=16384,
            num_predict=num_predict,
        )
    except Exception:
        logger.exception(
            "OCR request failed " + context + " elapsed_seconds=%.3f",
            *identifiers,
            perf_counter() - started,
        )
        raise
    logger.info(
        "OCR response "
        + context
        + " elapsed_seconds=%.3f chars=%d blank=%s preview=%r",
        *identifiers,
        perf_counter() - started,
        len(text),
        not text.strip(),
        text[:500],
    )
    return text


async def extract_image_text_async(
    image_base64: str,
    model_name: str | None = None,
) -> str:
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
        model=model_name or await get_model_name_async(ModelRole.OCR),
        prompt=OCR_PROMPT,
        image_base64=image_base64,
    )
