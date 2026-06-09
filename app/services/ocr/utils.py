"""Utility functions for the OCR service.

Provides shared helpers used by extractors and dispatchers:
text validation, MIME type mapping, and handler routing.
"""


def is_text_too_small(text: str, min_chars: int = 40) -> bool:
    """Check if extracted text is below minimum character threshold.

    Used by pdf_extractor.py to decide whether embedded text extraction
    was sufficient or if fallback OCR is needed for scanned documents.

    Args:
        text: The raw extracted text string.
        min_chars: Minimum character count to consider text valid.

    Returns:
        True if the stripped text has fewer than min_chars characters.
    """
    return len(text.strip()) < min_chars


def get_handler_category(mime_type: str) -> str:
    """Map MIME type to OCR handler category string.

    Returns the category key used by the OCR dispatcher to route
    files to the correct extraction backend.

    Args:
        mime_type: Detected MIME type string (e.g., 'application/pdf').

    Returns:
        One of 'pdf', 'image', or empty string for unsupported types.
    """
    category_map = {
        "application/pdf": "pdf",
        "image/png": "image",
        "image/jpeg": "image",
    }
    return category_map.get(mime_type, "")


def build_libreoffice_command(file_path: str, output_path: str) -> list[str]:
    """Construct the command to open a file with LibreOffice for conversion.

    This is used as a fallback for non-PDF files that need to be converted
    to PDF before OCR processing. The command opens the file in LibreOffice,
    allowing the user to manually save it as PDF if needed.

    Args:
        file_path: Absolute path to the input file.
        output_path: Desired output path for the converted PDF.

    Returns:
        List of command arguments to execute.
    """
    command = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "pdf",
        str(file_path),
        "--outdir",
        str(output_path),
    ]
    return command
