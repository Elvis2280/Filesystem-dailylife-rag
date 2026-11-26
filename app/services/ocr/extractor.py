"""Main OCR dispatcher - routes files to the correct extractor based on MIME type.

For PDFs: delegates to pdf_extractor.py (embedded text first, then OCR fallback).
For images: delegates to file_ocr.py (GLM-ocr vision model).
Unsupported types: raises ValueError with clear error message.
"""

from pathlib import Path

from app.services.ocr.file_ocr_llm import extract_image_text
from app.services.ocr.pdf_extractor import extract_pdf_text
from app.services.ocr.utils import get_handler_category


def extract_text(file_path: str, mime_type: str) -> str:
    """Extract text from a file by routing to the appropriate handler.

    Args:
        file_path: Absolute path to the file on disk.
        mime_type: Detected MIME type of the file.

    Returns:
        Extracted text.

    Raises:
        FileNotFoundError: If the file does not exist on disk.
        ValueError: If the MIME type is not supported.
    """
    category = get_handler_category(mime_type)
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if category == "pdf":
        return extract_pdf_text(path)
    elif category == "image":
        return extract_image_text(str(path))
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")
