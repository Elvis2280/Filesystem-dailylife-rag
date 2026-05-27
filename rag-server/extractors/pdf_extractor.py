
from pathlib import Path

from docling.document_converter import DocumentConverter

from extractors.common import logger

converter = DocumentConverter()


def pdf_extract(file_path: Path) -> str:
    try:
        logger.info("Extracting PDF text...")

        conversion_result = converter.convert(file_path)

        text_parts = []

        total_pages = len(conversion_result.document.pages)

        for i in range(total_pages):

            page_no = i + 1

            try:
                page_text = conversion_result.document.export_to_text(
                    page_no=page_no
                )

                if page_text.strip():
                    text_parts.append(page_text.strip())

            except Exception as e:
                logger.warning(f"Failed PDF page {page_no}: {e}")

        return "\n\n".join(text_parts)

    except Exception as e:
        raise RuntimeError(
            f"PDF extraction failed: {e}"
        ) from e