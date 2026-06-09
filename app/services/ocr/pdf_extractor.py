"""PDF text extraction: embedded text + OCR fallback for scanned PDFs.

Extraction strategy (ordered by priority):
    1. Extract embedded text using PyMuPDF (text blocks sorted by position).
    2. Extract tables using pdfplumber.
    3. If combined text is too short (< min_chars threshold), fall back to
       page-by-page OCR: render each page to a PNG, then run GLM-ocr.
"""

import uuid
from pathlib import Path

import fitz
import pdfplumber
from PIL import Image

from app.services.ocr.file_ocr import extract_image_text
from app.services.ocr.utils import is_text_too_small


def extract_pdf_text(pdf_path: Path, dpi: int = 200) -> str:
    """Extract text from a PDF with embedded text extraction and OCR fallback.

    First attempts to extract embedded text and tables. If the result is
    too short (likely a scanned PDF with no embedded text), falls back to
    rendering each page as an image and running vision-based OCR.

    Args:
        pdf_path: Path to the PDF file on disk.
        dpi: Resolution for page rendering during OCR fallback (default 200).

    Returns:
        Extracted text from all pages, with page markers and table data.
    """
    text = _extract_embedded_text(pdf_path)
    # If sufficient embedded text found, return immediately
    if not is_text_too_small(text):
        return text

    # Fall back to image-based OCR for scanned PDFs
    return _pdf_to_images_ocr(pdf_path, dpi)


def _extract_embedded_text(pdf_path: Path) -> str:
    """Extract embedded text and tables from PDF using PyMuPDF and pdfplumber.

    Text blocks are sorted by vertical position (top-to-bottom), then
    horizontal position (left-to-right) within each page. Tables are
    extracted separately to preserve their structure.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Newline-separated text with page headers (e.g., 'Page 1') and
        tab-separated table rows, or empty string if extraction fails.
    """
    final: list[str] = []

    # --- PyMuPDF: text block extraction ---
    # Sort blocks by (y, x) to approximate reading order
    try:
        doc = fitz.open(str(pdf_path))
        for page_index, page in enumerate(doc, start=1):
            blocks = page.get_text("blocks")
            blocks_sorted = sorted(blocks, key=lambda b: (b[1], b[0]))
            page_lines = []
            for block in blocks_sorted:
                text = block[4].strip()
                if text:
                    page_lines.append(text)
            if page_lines:
                final.append(f"Page {page_index}")
                final.append("\n".join(page_lines))
        doc.close()
    except Exception:
        # PyMuPDF failure is non-fatal; continue to pdfplumber
        pass

    # --- pdfplumber: table extraction ---
    # Extracts structured table data as tab-separated rows
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                if not tables:
                    continue
                final.append(f"Page {page_index} Tables")
                for t_index, table in enumerate(tables, start=1):
                    final.append(f"Table {t_index}")
                    for row in table:
                        if row is None:
                            continue
                        cleaned = [cell if cell is not None else "" for cell in row]
                        final.append("\t".join(cleaned))
    except Exception:
        # Non-fatal: tables may simply not be present
        pass

    return "\n".join(final).strip()


def _pdf_to_images_ocr(pdf_path: Path, dpi: int = 200) -> str:
    """Render PDF pages to images and OCR each one via GLM-ocr.

    Used as fallback when embedded text extraction yields insufficient text.
    Each page is rendered to a temporary PNG, processed through the vision
    model, then the temp file is cleaned up.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Rendering resolution (default 200 DPI).

    Returns:
        Double-newline-separated OCR text from all pages.
    """
    doc = fitz.open(str(pdf_path))
    # Convert DPI to PyMuPDF zoom matrix: 72 is the base DPI
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    results: list[str] = []

    for page_num, page in enumerate(doc):
        # Render page to pixel buffer
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Save to a unique temp file for the vision model to read
        temp_path = Path(
            f"/tmp/pdf_page_{page_num}_{pdf_path.stem}_{uuid.uuid4().hex[:8]}.png"
        )
        img.save(temp_path, format="PNG")

        # Run OCR on the rendered page image
        text = extract_image_text(temp_path)
        results.append(text)

        # Clean up temporary image immediately after processing
        temp_path.unlink(missing_ok=True)

    doc.close()
    return "\n\n".join(results)
