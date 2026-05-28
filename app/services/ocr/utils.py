"""Utility functions for OCR service."""


def is_text_too_small(text: str, min_chars: int = 40) -> bool:
    """Check if extracted text is below minimum character threshold."""
    return len(text.strip()) < min_chars


def get_handler_category(mime_type: str) -> str:
    """Map MIME type to OCR handler category."""
    category_map = {
        "application/pdf": "pdf",
        "image/png": "image",
        "image/jpeg": "image",
    }
    return category_map.get(mime_type, "")
