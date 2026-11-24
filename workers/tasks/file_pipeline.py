import json
import logging
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import UUID

from celery import Task
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constant import (
    ALLOWED_IMAGE_EXTENSIONS,
    FilePipelineStage,
    FileStatus,
)
from app.core.database import document_lock_engine, get_sync_db
from app.core.document_lock import document_lock_key
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.models.workspace import WorkspaceModel
from app.services.format.format import format_all_markdown
from app.services.ocr.file_ocr_llm import extract_image_text
from app.services.storage.document_sync import (
    convert_to_images,
    convert_to_pdf,
    ensure_pdf_in_workspace,
    processing_splits,
    save_ocr_page,
)
from app.services.storage.object_storage import download_file, get_text, object_exists
from workers.celery_app import celery_app


@contextmanager
def document_worker_lock(document_id: str) -> Iterator[None]:
    """Hold a session-level lock for the full lifetime of a document job."""
    key = document_lock_key(UUID(document_id))
    with document_lock_engine.connect() as lock_connection:
        lock_connection.execute(select(func.pg_advisory_lock(key)))
        lock_connection.commit()
        try:
            yield
        finally:
            lock_connection.scalar(select(func.pg_advisory_unlock(key)))
            lock_connection.commit()


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
    if db_session is not None:
        document = db_session.get(Document, UUID(document_id))
        if document is not None:
            event = DocumentEventModel(
                document_id=document.id,
                workspace_id=document.workspace_id,
                status=status,
                stage=stage.value,
                step=stage.step,
                message=message or stage.message,
                page_number=page_number,
                total_pages=total_pages,
            )
            db_session.add(event)
            db_session.commit()

    try:
        redis_client.publish(
            f"document_updates:{document_id}",
            json.dumps(payload),
        )
    except Exception as e:
        logging.getLogger("memory_rag.pipeline").warning(
            "Failed to publish status to Redis for document %s: %s",
            document_id,
            e,
        )


def record_pipeline_failure(
    document_id: str,
    stage: FilePipelineStage,
    error: Exception,
    workspace_name: str,
    page_number: int | None = None,
    *,
    expected_status: FileStatus | None = None,
) -> None:
    """Commit the failure checkpoint before publishing terminal status."""
    message = str(error)[:2000] or type(error).__name__
    try:
        with get_sync_db() as db_session:
            document = db_session.get(Document, UUID(document_id), with_for_update=True)
            if document is None or (
                expected_status and document.status != expected_status.value
            ):
                return
            if not workspace_name:
                workspace = db_session.get(WorkspaceModel, document.workspace_id)
                workspace_name = workspace.name if workspace else ""
            document.status = FileStatus.FAILED.value
            document.last_error = message
            _publish_status(
                document_id,
                stage,
                original_filename=document.original_filename,
                workspace_name=workspace_name,
                message=message,
                page_number=page_number,
                total_pages=document.page_count,
                status=FileStatus.FAILED.value,
                db_session=db_session,
            )
    except Exception:
        logging.getLogger("memory_rag.pipeline").exception(
            "Could not save failure for document %s at stage %s, page %s",
            document_id,
            stage.value,
            page_number,
        )


def _usable_ocr(storage_key: str | None) -> bool:
    if not storage_key or not object_exists(storage_key):
        return False
    try:
        return bool(get_text(storage_key).strip())
    except UnicodeDecodeError:
        return False


def _run_file_pipeline(
    task: Task,
    document_id: str,
    *,
    retry_task_id: UUID | None = None,
    resume_from: FilePipelineStage = FilePipelineStage.OBJECT_STORAGE,
) -> bool:
    """Produce the file artifacts. Return False for an obsolete retry delivery."""
    resume = retry_task_id is not None
    stage = resume_from
    current_page: int | None = None
    workspace_name = ""
    claimed = False
    try:
        with get_sync_db() as db_session:
            document = db_session.scalar(
                select(Document)
                .where(Document.id == UUID(document_id))
                .with_for_update()
            )
            if document is None:
                if resume:
                    return False
                raise ValueError(f"Document {document_id} not found")

            if resume:
                event = db_session.scalar(
                    select(DocumentEventModel)
                    .where(
                        DocumentEventModel.document_id == document.id,
                        DocumentEventModel.status == FileStatus.RETRY_QUEUED.value,
                    )
                    .order_by(
                        DocumentEventModel.created_at.desc(),
                        DocumentEventModel.id.desc(),
                    )
                    .limit(1)
                )
                if (
                    document.status != FileStatus.RETRY_QUEUED.value
                    or event is None
                    or event.id != retry_task_id
                ):
                    return False
                document.status = FileStatus.RETRY_RUNNING.value
            elif document.status != FileStatus.FILE_UPLOADED.value:
                return False
            else:
                document.status = FileStatus.FILE_PROCESSING.value

            document.attempt_count += 1
            document.last_error = None
            db_session.commit()
            claimed = True

            workspace = db_session.get(WorkspaceModel, document.workspace_id)
            if workspace is None:
                raise ValueError(f"Workspace for document {document_id} not found")
            workspace_name = workspace.name

            def progress(
                next_stage: FilePipelineStage,
                message: str,
                status: FileStatus,
                page: int | None = None,
            ) -> None:
                nonlocal stage, current_page
                stage, current_page = next_stage, page
                document.status = status.value
                _publish_status(
                    document_id,
                    stage,
                    document.original_filename,
                    workspace_name,
                    message=message,
                    page_number=page,
                    total_pages=document.page_count,
                    status=status.value,
                    db_session=db_session,
                )
                task.update_state(state="PROGRESS", meta={"stage": stage.value})

            if resume:
                progress(
                    stage,
                    "Retry started. Checking saved progress...",
                    FileStatus.RETRY_RUNNING,
                )
            else:
                progress(
                    FilePipelineStage.OBJECT_STORAGE,
                    "Original file available in Garage; starting processing...",
                    FileStatus.FILE_PROCESSING,
                )

            source = ensure_pdf_in_workspace(document_id, db_session)
            direct_image = f".{document.file_extension}" in ALLOWED_IMAGE_EXTENSIONS
            is_pdf = document.mime_type == "application/pdf"

            def make_pdf() -> Document:
                progress(
                    FilePipelineStage.PDF_CONVERSION,
                    "Converting original file to PDF...",
                    FileStatus.FILE_CONVERSION_STARTED,
                )
                if not object_exists(document.storage_key):
                    raise FileNotFoundError(
                        f"Original document {document_id} is missing from storage"
                    )
                return convert_to_pdf(document_id, db_session)

            def render_missing_pages(
                page: int | None = None,
            ) -> list[DocumentSplitModel]:
                nonlocal source, stage, current_page
                progress(
                    FilePipelineStage.IMAGE_CONVERSION,
                    f"Rendering missing image for page {page}..."
                    if page
                    else "Rendering missing PDF pages...",
                    FileStatus.FILE_CONVERSION_FINISHED,
                    page,
                )
                if not object_exists(source.storage_key):
                    if source.id == document.id:
                        raise FileNotFoundError(
                            f"Original PDF {document_id} is missing from storage"
                        )
                    source = make_pdf()
                stage, current_page = FilePipelineStage.IMAGE_CONVERSION, page
                return convert_to_images(document_id, db_session)

            if not direct_image and not is_pdf and source.id == document.id:
                source = make_pdf()

            expected_pages = 1 if direct_image else source.page_count
            splits = processing_splits(source, db_session)
            pages = [split.page_number for split in splits]
            if not direct_image:
                stage = FilePipelineStage.IMAGE_CONVERSION
            restore_images = not resume or resume_from.step_number <= stage.step_number
            if not direct_image and (
                not expected_pages
                or pages != list(range(1, expected_pages + 1))
                or (
                    restore_images
                    and any(not object_exists(split.storage_key) for split in splits)
                )
            ):
                splits = render_missing_pages()
                expected_pages = source.page_count or len(splits)

            if not expected_pages or [split.page_number for split in splits] != list(
                range(1, expected_pages + 1)
            ):
                raise RuntimeError(f"Invalid page splits for document {document_id}")
            document.page_count = expected_pages
            db_session.commit()

            with tempfile.TemporaryDirectory(prefix="ocr-inputs-") as temp_dir:
                for split in splits:
                    page = split.page_number
                    stage, current_page = FilePipelineStage.OCR_PROCESSING, page
                    if resume and _usable_ocr(split.ocr_storage_key):
                        continue
                    if not object_exists(split.storage_key):
                        if direct_image:
                            raise FileNotFoundError(
                                f"Original image {document_id} is missing from storage"
                            )
                        render_missing_pages(page)
                    progress(
                        FilePipelineStage.OCR_PROCESSING,
                        f"Processing page {page} of {expected_pages}...",
                        FileStatus.OCR_STARTED,
                        page,
                    )
                    suffix = Path(split.filename).suffix or ".png"
                    image_path = Path(temp_dir) / f"page-{page:04d}{suffix}"
                    download_file(split.storage_key, image_path)

                    def publish_retry() -> None:
                        progress(
                            FilePipelineStage.OCR_PROCESSING,
                            f"Retrying OCR for page {page} of {expected_pages}...",
                            FileStatus.OCR_STARTED,
                            page,
                        )

                    text = extract_image_text(
                        image_path,
                        document_id=document_id,
                        page_number=page,
                        on_retry=publish_retry,
                    )
                    save_ocr_page(
                        str(source.id),
                        str(document.workspace_id),
                        page,
                        text,
                        db_session,
                        invalidate_formatted_output=resume,
                    )

            if not resume or document.status == FileStatus.OCR_STARTED.value:
                progress(
                    FilePipelineStage.OCR_PROCESSING,
                    "OCR finished.",
                    FileStatus.OCR_FINISHED,
                )

            def formatting_page(page: int) -> None:
                nonlocal stage, current_page
                stage, current_page = FilePipelineStage.TRANSLATION, page

            def formatting_started(page: int) -> None:
                progress(
                    FilePipelineStage.TRANSLATION,
                    f"Formatting or translating page {page}...",
                    FileStatus.TRANSLATION_AND_FORMATTING_STARTED,
                    page,
                )

            format_all_markdown(
                str(document.workspace_id),
                document_id,
                db_session,
                resume=resume,
                on_page=formatting_page,
                on_work=formatting_started,
            )
            if document.status == FileStatus.TRANSLATION_AND_FORMATTING_STARTED.value:
                progress(
                    FilePipelineStage.TRANSLATION,
                    "Translation and formatting finished.",
                    FileStatus.TRANSLATION_AND_FORMATTING_FINISHED,
                )
            progress(
                FilePipelineStage.FILE_PROCESS_FINISHED,
                "File processing finished. Indexing next...",
                FileStatus.RETRY_RUNNING
                if resume
                else FileStatus.FILE_PROCESS_FINISHED,
            )
            return True
    except Exception as exc:
        if claimed:
            record_pipeline_failure(
                document_id, stage, exc, workspace_name, current_page
            )
        raise


@celery_app.task(name="workers.tasks.process_file_upload", bind=True)
def process_file_upload(self: Task, document_id: str) -> None:
    from workers.tasks.save_data import run_indexing

    with document_worker_lock(document_id):
        if not _run_file_pipeline(self, document_id):
            return
        run_indexing(self, document_id)


@celery_app.task(name="workers.tasks.retry_document", bind=True)
def retry_document(self: Task, document_id: str, resume_from: str) -> None:
    from workers.tasks.save_data import run_indexing

    with document_worker_lock(document_id):
        if _run_file_pipeline(
            self,
            document_id,
            retry_task_id=UUID(self.request.id),
            resume_from=FilePipelineStage(resume_from),
        ):
            run_indexing(self, document_id, count_attempt=False)
