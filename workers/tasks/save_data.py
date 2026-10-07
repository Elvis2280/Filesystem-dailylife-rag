import json
import logging
from datetime import datetime

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.constant import FilePipelineStage, FileStatus
from app.core.database import get_sync_db
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.services.format.cleaner_llm import clean_text
from app.services.rag.embedding import embedding
from app.services.rag.qdrant_client import upsert_embeddings
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


def _chunk_english(text: str) -> list[str]:
    """Split the cleaned English markdown into chunks.

    Uses langchain's RecursiveCharacterTextSplitter with sensible defaults
    tuned for bilingual document pages.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_text(text)


@celery_app.task(
    name="workers.tasks.process_save_data",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_save_data(self, document_id: str) -> None:
    """Read the OCR and translation files for every page of a document.

    Runs after the file pipeline finishes. For each page (1..page_count)
    the raw OCR text, English markdown and Japanese markdown are read from
    disk and surfaced to the next stage (embedding + Qdrant indexing).
    """
    db_session: Session | None = None
    document: Document | None = None
    original_filename = ""
    workspace_name = ""
    try:
        with get_sync_db() as db_session:
            document = db_session.query(Document).filter_by(id=document_id).first()
            if not document:
                raise ValueError(f"No document with ID {document_id}")

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

                raw_text = clean_text(raw_text)
                english_markdown = clean_text(english_markdown)
                japanese_markdown = clean_text(japanese_markdown)

                logger.info("raw_text cleaned: %s", raw_text)
                logger.info("english_markdown cleaned: %s", english_markdown)
                logger.info("japanese_markdown cleaned: %s", japanese_markdown)

                if not (
                    raw_text.strip()
                    or english_markdown.strip()
                    or japanese_markdown.strip()
                ):
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

                chunk_data = _chunk_english(english_markdown)
                if not chunk_data:
                    logger.info(
                        "save_data: page %d for document %s has no English "
                        "chunks; skipping",
                        page,
                        document_id,
                    )
                    continue
                embedding_data = embedding(chunk_data)

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

                upsert_embeddings(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    page_number=page,
                    language="en",
                    texts=chunk_data,
                    vectors=embedding_data,
                    raw_ocr=raw_text,
                    japanese_text=japanese_markdown,
                )

            publish_status(
                document_id,
                FilePipelineStage.SAVING_DATA,
                message="Saving data to vector store...",
                total_pages=page_count,
                db_session=db_session,
            )

            _set_status(document, FileStatus.COMPLETED, db_session)
            publish_status(
                document_id,
                FilePipelineStage.COMPLETED,
                message=f"Vector indexing finished for {page_count} pages.",
                total_pages=page_count,
                status=FileStatus.COMPLETED.value,
                db_session=db_session,
            )

    except Exception as e:
        if document is not None and db_session is not None:
            document.status = FileStatus.FAILED.value
            document.last_error = str(e)
            db_session.commit()
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
