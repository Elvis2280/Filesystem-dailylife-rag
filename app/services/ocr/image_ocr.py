"""Image OCR using GLM-ocr vision model."""

from pathlib import Path

from app.services.ai.ollama_sync import OllamaSyncClient


def extract_image_text(image_path: str | Path) -> str:
    """Extract text from image using GLM-ocr vision model.

    Args:
        image_path: Path to the image file (PNG, JPG, JPEG).

    Returns:
        Extracted raw text from the image.
    """
    client = OllamaSyncClient()
    return client.generate_ocr(str(image_path))
