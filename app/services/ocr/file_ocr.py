"""Image OCR using GLM-ocr vision model.

This module delegates to the synchronous Ollama client for extracting
text from images. It is called both directly (for image uploads) and
as a fallback from pdf_extractor.py (for scanned PDF pages).
"""

from pathlib import Path
from app.services.ai.ollama_sync import OllamaSyncClient


def extract_image_text(image_path: str | Path) -> str:
    """Extract text from image using GLM-ocr vision model.

    Creates a fresh OllamaSyncClient and sends the image for
    vision-based text extraction. The client handles prompt
    engineering internally (verbatim extraction, no commentary).

    Args:
        image_path: Path to the image file (PNG, JPG, JPEG).

    Returns:
        Extracted raw text from the image.
    """
    client = OllamaSyncClient()
    return client.generate_ocr(str(image_path))
