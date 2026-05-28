"""PDF text extraction: embedded text + OCR fallback for scanned PDFs."""

import uuid
from pathlib import Path

import fitz
import pdfplumber
from PIL import Image

from app.services.ocr.image_ocr import extract_image_text
from app.services.ocr.utils import is_text_too_small


def extract_pdf_text(pdf_path: Path, dpi: int = 200) -> str:
    """Extract text from PDF.

    Tries embedded text extraction first.
    Falls back to page-by-page OCR via GLM-ocr if insufficient text is found.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for page rendering during OCR fallback (default 200).

    Returns:
        Extracted text from the PDF.
    """
    text = _extract_embedded_text(pdf_path)
    if not is_text_too_small(text):
        return text

    return _pdf_to_images_ocr(pdf_path, dpi)


def _extract_embedded_text(pdf_path: Path) -> str:
    """Extract embedded text and tables from PDF.

    Uses PyMuPDF for text blocks sorted by position,
    and pdfplumber for table extraction.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted text with page/table markers.
    """
    final: list[str] = []

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
        pass

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
        pass

    return "\n".join(final).strip()


def _pdf_to_images_ocr(pdf_path: Path, dpi: int = 200) -> str:
    """Render PDF pages to images and OCR each one via GLM-ocr.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Rendering resolution.

    Returns:
        Concatenated OCR text from all pages.
    """
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    results: list[str] = []

    for page_num, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        temp_path = Path(
            f"/tmp/pdf_page_{page_num}_{pdf_path.stem}_{uuid.uuid4().hex[:8]}.png"
        )
        img.save(temp_path, format="PNG")
        text = extract_image_text(temp_path)
        results.append(text)
        temp_path.unlink(missing_ok=True)

    doc.close()
    return "\n\n".join(results)
