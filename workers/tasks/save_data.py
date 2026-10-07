import json
import logging
import re
from datetime import datetime

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.constant import FilePipelineStage, FileStatus
from app.core.config import settings
from app.core.database import get_sync_db
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.services.format.cleaner_llm import clean_text
from app.services.rag.embedding import embedding
from app.services.rag.qdrant_client import (
    COLLECTION_NAME,
    HYBRID_COLLECTION_NAME,
    delete_document_embeddings_after_page,
    delete_page_embeddings,
    upsert_embeddings,
)
from app.services.storage.object_storage import get_text
from workers.celery_app import celery_app

logger = logging.getLogger("memory_rag.save_data")


def _publish_status(
    document_id: str,
    stage: FilePipelineStage,
    original_filename: str,
    workspace_name: str,
    message: str | None = None,
    page_number: int | None = None,
    total_pages: int | None = None,
    status: str = "PROGRESS",
    db_session: Session | None = None,
) -> None:
    payload = {
        "status": status,
        "step": stage.step_number,
        "stepTotal": stage.step_total,
        "stage": stage.value,
        "message": message or stage.message,
        "document_id": document_id,
        "original_filename": original_filename,
        "workspace_name": workspace_name,
        "page_number": page_number,
        "total_pages": total_pages,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        redis_client.publish(
            f"document_updates:{document_id}",
            json.dumps(payload),
        )
    except Exception as e:
        logger.warning(
            "Failed to publish status to Redis for document %s: %s",
            document_id,
            e,
        )

    if db_session is not None:
        document = db_session.query(Document).filter_by(id=document_id).first()
        if document is None:
            return
        history = DocumentEventModel(
            document_id=document_id,
            workspace_id=document.workspace_id,
            status=status,
            stage=stage.value,
            step=stage.step,
            message=message or stage.message,
            page_number=page_number,
            total_pages=total_pages,
        )
        db_session.add(history)
        db_session.commit()


def _read_text(object_key: str, label: str) -> str:
    try:
        return get_text(object_key)
    except Exception as exc:
        raise FileNotFoundError(f"Missing {label}: {object_key}") from exc


def _set_status(
    document: Document,
    file_status: FileStatus,
    db_session: Session,
) -> None:
    document.status = file_status.value
    db_session.commit()


def _page_object_keys(
    document_id: str, page: int, db_session: Session
) -> tuple[str, str, str]:
    split = db_session.execute(
        select(DocumentSplitModel)
        .join(Document, Document.id == DocumentSplitModel.document_id)
        .where(
            DocumentSplitModel.page_number == page,
            or_(
                DocumentSplitModel.document_id == document_id,
                and_(
                    Document.parent_document_id == document_id,
                    Document.file_role == "converted_pdf",
                ),
            ),
        )
    ).scalar_one_or_none()
    if split is None or not split.ocr_storage_key:
        raise FileNotFoundError(f"Missing persisted split/OCR record for page {page}")

    translations = (
        db_session.execute(
            select(TranslationModel).where(
                TranslationModel.document_split_id == split.id,
                TranslationModel.language.in_(("EN", "JP")),
            )
        )
        .scalars()
        .all()
    )
    by_language = {translation.language: translation for translation in translations}
    if "EN" not in by_language or "JP" not in by_language:
        raise FileNotFoundError(f"Missing translations for page {page}")
    return (
        split.ocr_storage_key,
        by_language["EN"].storage_key,
        by_language["JP"].storage_key,
    )


def _extract_document_title(markdown: str, fallback: str) -> str:
    """Use the first Markdown heading as a stable document-level retrieval hint."""
    match = re.search(r"^#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback.strip() or "Untitled document"


def _chunk_english(
    text: str,
    document_title: str,
) -> list[tuple[str, str, str]]:
    """Return answer text, retrieval text, and section for each Markdown chunk.

    The retrieval text carries document and section context across page splits;
    the answer text remains unchanged for grounding and display.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    chunks = splitter.split_text(text)
    chunked: list[tuple[str, str, str]] = []
    current_section = ""
    for chunk in chunks:
        chunk_headings = [
            heading.strip()
            for heading in re.findall(
                r"^\s{0,3}#{1,6}\s+(.+?)\s*$",
                chunk,
                flags=re.MULTILINE,
            )
        ]
        if chunk_headings:
            current_section = " | ".join(dict.fromkeys(chunk_headings))
        section_title = current_section
        retrieval_parts = [f"Document: {document_title}"]
        if section_title:
            retrieval_parts.append(f"Section: {section_title}")
        retrieval_parts.append(chunk)
        chunked.append((chunk, "\n".join(retrieval_parts), section_title))
    return chunked


@celery_app.task(
    name="workers.tasks.process_save_data",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_save_data(
    self,
    document_id: str,
    target_collections: list[str] | None = None,
    clean_source_text: bool = True,
    maintenance_reindex: bool = False,
) -> dict[str, int]:
    """Read the OCR and translation files for every page of a document.

    Runs after the file pipeline finishes. For each page (1..page_count)
    the raw OCR text, English markdown and Japanese markdown are read from
    disk and surfaced to the next stage (embedding + Qdrant indexing).
    """
    db_session: Session | None = None
    document: Document | None = None
    original_filename = ""
    workspace_name = ""
    indexed_pages = 0
    indexed_chunks = 0
    empty_pages = 0
    try:
        with get_sync_db() as db_session:
            document = db_session.query(Document).filter_by(id=document_id).first()
            if not document:
                raise ValueError(f"No document with ID {document_id}")

            if not maintenance_reindex:
                document.attempt_count += 1
                document.last_error = None
                db_session.commit()

            original_filename = document.original_filename
            workspace = (
                db_session.query(WorkspaceModel)
                .filter_by(id=document.workspace_id)
                .first()
            )
            if workspace is None:
                raise ValueError(
                    f"Workspace with ID {document.workspace_id} not found in database."
                )
            workspace_name = workspace.name

            def publish_status(
                status_document_id: str,
                stage: FilePipelineStage,
                message: str | None = None,
                page_number: int | None = None,
                total_pages: int | None = None,
                status: str = "PROGRESS",
                db_session: Session | None = None,
            ) -> None:
                if maintenance_reindex:
                    return
                _publish_status(
                    status_document_id,
                    stage,
                    original_filename=original_filename,
                    workspace_name=workspace_name,
                    message=message,
                    page_number=page_number,
                    total_pages=total_pages,
                    status=status,
                    db_session=db_session,
                )

            page_count = document.page_count
            if not page_count or page_count < 1:
                raise ValueError(
                    f"Document {document_id} has no page_count; "
                    "file_pipeline must finish before indexing."
                )

            publish_status(
                document_id,
                FilePipelineStage.VERIFY_FILES,
                message=f"Verifying required files for {page_count} pages...",
                total_pages=page_count,
                db_session=db_session,
            )
            self.update_state(state="PROGRESS", meta={"stage": "verify_files"})

            workspace_id = str(document.workspace_id)
            document_title = document.original_filename.rsplit(".", 1)[0]
            if target_collections is None:
                target_collections = [settings.QDRANT_COLLECTION or COLLECTION_NAME]
                if settings.QDRANT_DUAL_WRITE_HYBRID:
                    target_collections.append(
                        settings.QDRANT_HYBRID_COLLECTION or HYBRID_COLLECTION_NAME
                    )
            if not target_collections:
                raise ValueError("At least one Qdrant collection must be targeted")
            for page in range(1, page_count + 1):
                publish_status(
                    document_id,
                    FilePipelineStage.COLLECTING_DATA,
                    message=f"Collecting data on page {page} of {page_count}...",
                    page_number=page,
                    total_pages=page_count,
                    db_session=db_session,
                )

                ocr_key, english_key, japanese_key = _page_object_keys(
                    document_id, page, db_session
                )

                raw_text = _read_text(ocr_key, f"OCR page {page}")
                english_markdown = _read_text(english_key, f"English page {page}")
                japanese_markdown = _read_text(japanese_key, f"Japanese page {page}")

                publish_status(
                    document_id,
                    FilePipelineStage.PREPARING_DATA,
                    message=f"Preparing data on page {page} of {page_count}...",
                    page_number=page,
                    total_pages=page_count,
                    db_session=db_session,
                )

                if clean_source_text:
                    raw_text = clean_text(raw_text)
                    english_markdown = clean_text(english_markdown)
                    japanese_markdown = clean_text(japanese_markdown)

                if page == 1:
                    document_title = _extract_document_title(
                        english_markdown,
                        document_title,
                    )

                if not (
                    raw_text.strip()
                    or english_markdown.strip()
                    or japanese_markdown.strip()
                ):
                    for collection_name in target_collections:
                        delete_page_embeddings(
                            document_id,
                            page,
                            collection_name,
                        )
                    empty_pages += 1
                    logger.info(
                        "save_data: page %d for document %s has no content "
                        "after cleaning; skipping",
                        page,
                        document_id,
                    )
                    continue

                logger.info(
                    "save_data: page %d cleaned for document %s "
                    "(raw=%d chars, en=%d chars, ja=%d chars)",
                    page,
                    document_id,
                    len(raw_text),
                    len(english_markdown),
                    len(japanese_markdown),
                )

                chunk_records = _chunk_english(english_markdown, document_title)
                if not chunk_records:
                    for collection_name in target_collections:
                        delete_page_embeddings(
                            document_id,
                            page,
                            collection_name,
                        )
                    empty_pages += 1
                    logger.info(
                        "save_data: page %d for document %s has no English "
                        "chunks; skipping",
                        page,
                        document_id,
                    )
                    continue
                chunk_data = [record[0] for record in chunk_records]
                retrieval_data = [record[1] for record in chunk_records]
                section_data = [record[2] for record in chunk_records]
                embedding_data = embedding(retrieval_data)

                logger.info(
                    "save_data: page %d produced %d English chunks",
                    page,
                    len(chunk_data),
                )
                logger.info(
                    "save_data: page %d embedded %d vectors",
                    page,
                    len(embedding_data),
                )

                for collection_name in target_collections:
                    upsert_embeddings(
                        document_id=document_id,
                        workspace_id=workspace_id,
                        page_number=page,
                        language="en",
                        texts=chunk_data,
                        vectors=embedding_data,
                        retrieval_texts=retrieval_data,
                        document_title=document_title,
                        section_titles=section_data,
                        raw_ocr=raw_text,
                        japanese_text=japanese_markdown,
                        collection_name=collection_name,
                    )
                indexed_pages += 1
                indexed_chunks += len(chunk_data)

            for collection_name in target_collections:
                delete_document_embeddings_after_page(
                    document_id,
                    page_count,
                    collection_name,
                )

            publish_status(
                document_id,
                FilePipelineStage.SAVING_DATA,
                message="Saving data to vector store...",
                total_pages=page_count,
                db_session=db_session,
            )

            if not maintenance_reindex:
                _set_status(document, FileStatus.COMPLETED, db_session)
            publish_status(
                document_id,
                FilePipelineStage.COMPLETED,
                message=f"Vector indexing finished for {page_count} pages.",
                total_pages=page_count,
                status=FileStatus.COMPLETED.value,
                db_session=db_session,
            )
            return {
                "indexed_pages": indexed_pages,
                "indexed_chunks": indexed_chunks,
                "empty_pages": empty_pages,
            }

    except Exception as e:
        if document is not None and db_session is not None and not maintenance_reindex:
            document.status = FileStatus.FAILED.value
            document.last_error = str(e)
            db_session.commit()
        if not maintenance_reindex:
            _publish_status(
                document_id,
                FilePipelineStage.FAILED,
                original_filename=original_filename,
                workspace_name=workspace_name,
                message=str(e),
                status=FileStatus.FAILED.value,
                db_session=db_session,
            )
        raise


@celery_app.task(name="workers.tasks.reindex_qdrant_hybrid", bind=True)
def reindex_qdrant_hybrid(self) -> dict[str, int]:
    """Backfill completed source documents into the versioned hybrid index.

    Invoke this task once before setting QDRANT_USE_HYBRID=true. It reuses the
    persisted OCR and Markdown artifacts and leaves the current collection in
    place for rollback.
    """
    with get_sync_db() as db_session:
        document_ids = [
            str(document_id)
            for (document_id,) in db_session.query(Document.id)
            .filter(
                Document.file_role == "original",
                Document.status == FileStatus.COMPLETED.value,
            )
            .order_by(Document.id)
            .all()
        ]

    target_collection = settings.QDRANT_HYBRID_COLLECTION or HYBRID_COLLECTION_NAME
    totals = {"indexed_documents": 0, "indexed_pages": 0, "indexed_chunks": 0}
    for document_id in document_ids:
        result = process_save_data.apply(
            args=[document_id],
            kwargs={
                "target_collections": [target_collection],
                "clean_source_text": False,
                "maintenance_reindex": True,
            },
            throw=True,
        )
        indexed = result.result if isinstance(result.result, dict) else {}
        totals["indexed_documents"] += 1
        totals["indexed_pages"] += int(indexed.get("indexed_pages", 0))
        totals["indexed_chunks"] += int(indexed.get("indexed_chunks", 0))
        self.update_state(
            state="PROGRESS",
            meta={
                "completed_documents": totals["indexed_documents"],
                "total_documents": len(document_ids),
            },
        )

    logger.info(
        "Hybrid Qdrant backfill complete documents=%d pages=%d chunks=%d",
        totals["indexed_documents"],
        totals["indexed_pages"],
        totals["indexed_chunks"],
    )
    return totals
