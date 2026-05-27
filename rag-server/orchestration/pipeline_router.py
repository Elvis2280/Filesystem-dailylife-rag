# orchestration/pipeline_router.py

from pathlib import Path
import os

from services.ingestion_pipeline import (
    ingest_document,
)


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
}

def route_pipeline(file_path: str):
    _, ext = os.path.splitext(file_path)

    if not ext:
        raise ValueError(f"Cannot detect file extension from: {file_path}")

    ext = ext.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    return ingest_document

# def route_pipeline(file_path: str):
#     ext = Path(file_path or "").suffix.lower()

#     if not ext:
#         raise ValueError(f"Cannot detect file extension from: {file_path}")

#     if ext not in SUPPORTED_EXTENSIONS:
#         raise ValueError(f"Unsupported file type: {ext}")

#     return ingest_document