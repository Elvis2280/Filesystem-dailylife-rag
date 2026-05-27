# services/extract_file.py

from pathlib import Path

from extractors.pdf_extractor import pdf_extract
from extractors.docx_extractor import docx_extract
from extractors.image_extractor import image_extract
from extractors.pptx_extractor import pptx_extract
from extractors.excel_extractor import excel_extract

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
}


def extract_file(file_path: Path) -> str:

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return pdf_extract(file_path)

    elif ext == ".docx":
        return docx_extract(file_path)

    elif ext in IMAGE_EXTENSIONS:
        return image_extract(file_path)

    elif ext == ".pptx":
        return pptx_extract(file_path)

    elif ext in [".xlsx", ".xls"]:
        return excel_extract(file_path)

    else:
        raise ValueError(
            f"Unsupported file type: {ext}"
        )