"""Object-key and checksum helpers for persisted document artifacts."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise ValueError("Object filename must not be empty")
    return name


def workspace_object_prefix(workspace_id: uuid.UUID | str) -> str:
    return f"workspaces/{workspace_id}"


def document_object_prefix(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
) -> str:
    return f"{workspace_object_prefix(workspace_id)}/documents/{root_document_id}"


def original_document_key(
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    filename: str,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, document_id)}/original/"
        f"{_safe_filename(filename)}"
    )


def converted_document_key(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
    converted_document_id: uuid.UUID | str,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, root_document_id)}/converted/"
        f"{converted_document_id}.pdf"
    )


def split_object_key(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
    source_document_id: uuid.UUID | str,
    page_number: int,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, root_document_id)}/splits/"
        f"{source_document_id}/page-{page_number:04d}.png"
    )


def ocr_object_key(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
    source_document_id: uuid.UUID | str,
    page_number: int,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, root_document_id)}/ocr/"
        f"{source_document_id}/page-{page_number:04d}.txt"
    )


def markdown_object_key(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
    page_number: int,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, root_document_id)}/markdown/"
        f"page-{page_number:04d}.md"
    )


def translation_object_key(
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
    language: str,
    page_number: int,
) -> str:
    return (
        f"{document_object_prefix(workspace_id, root_document_id)}/translations/"
        f"{language.lower()}/page-{page_number:04d}.md"
    )


def pipeline_temp_dir(
    temp_root: str,
    workspace_id: uuid.UUID | str,
    root_document_id: uuid.UUID | str,
) -> Path:
    return Path(temp_root) / str(workspace_id) / str(root_document_id)
