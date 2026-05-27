# extractors/docx_extractor.py

import shutil
import subprocess
import tempfile

from pathlib import Path

from extractors.common import logger
from extractors.pdf_extractor import pdf_extract


def convert_docx_to_pdf(docx_path: Path):

    temp_dir = Path(tempfile.mkdtemp())

    subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            str(docx_path),
            "--outdir",
            str(temp_dir),
        ],
        check=True,
    )

    pdf_path = temp_dir / f"{docx_path.stem}.pdf"

    if not pdf_path.exists():
        raise RuntimeError(
            "DOCX to PDF conversion failed"
        )

    return pdf_path, temp_dir


def docx_extract(file_path: Path) -> str:
    try:
        logger.info("Converting DOCX to PDF...")

        pdf_path, temp_dir = convert_docx_to_pdf(file_path)

        text = pdf_extract(pdf_path)

        shutil.rmtree(temp_dir, ignore_errors=True)

        return text

    except Exception as e:
        raise RuntimeError(
            f"DOCX extraction failed: {e}"
        ) from e