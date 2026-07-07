import json
import logging
from datetime import datetime

import fitz

from app.core.constant import (
    ALLOWED_IMAGE_EXTENSIONS,
    FilePipelineStage,
    FileStatus,
)
from app.core.database import get_sync_db
from app.core.redis_client import redis_client
from app.models.document import Document
from app.services.format.format import format_all_markdown
from app.services.ocr.file_ocr_llm import extract_image_text
from app.services.storage.document_sync import (
    convert_to_images,
    convert_to_pdf,
    ensure_pdf_in_workspace,
    return_list_images_path,
    save_ocr_page,
)
from workers.celery_app import celery_app


def _is_pdf(mime_type: str) -> bool:
    return mime_type == "application/pdf"


def _count_pdf_pages(path: str) -> int:
    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _publish_status(
    document_id: str,
    stage: FilePipelineStage,
    message: str | None = None,
    page_number: int | None = None,
    total_pages: int | None = None,
    status: str = "PROGRESS",
):
    redis_client.publish(
        f"document_updates:{document_id}",
        json.dumps(
            {
                "status": status,
                "step": stage.step,
                "stage": stage.value,
                "message": message or stage.message,
                "document_id": document_id,
                "page_number": page_number,
                "total_pages": total_pages,
                "timestamp": datetime.now().isoformat(),
            }
        ),
    )


@celery_app.task(
    name="workers.tasks.process_file_upload",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_file_upload(self, document_id: str) -> None:
    try:
        with get_sync_db() as db_session:
            document = db_session.query(Document).filter_by(id=document_id).first()
            if not document:
                raise ValueError(
                    f"Document with ID {document_id} not found in database."
                )

            ext = (
                "."
                + (
                    document.original_filename.rsplit(".", 1)[-1]
                    if "." in document.original_filename
                    else ""
                )
            ).lower()
            is_pdf = _is_pdf(document.mime_type)

            if not is_pdf and ext not in ALLOWED_IMAGE_EXTENSIONS:
                _publish_status(document_id, FilePipelineStage.PDF_CONVERSION)
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "pdf_conversion"},
                )
                document.status = "processing_document_to_pdf"
                db_session.commit()

                converted_pdf_result = convert_to_pdf(document_id, db_session)
                ext = f".{converted_pdf_result.converted_to_extension.lower()}"

                # Capture page_count for non-PDFs after LibreOffice conversion
                try:
                    pdf_path = converted_pdf_result.converted_file_path
                    page_count = _count_pdf_pages(pdf_path)
                    document.page_count = page_count
                    db_session.commit()
                except Exception as exc:
                    logging.getLogger("memory_rag.pipeline").warning(
                        "Could not read page_count from generated PDF: %s", exc
                    )

            if ext == ".pdf" or is_pdf:
                _publish_status(document_id, FilePipelineStage.IMAGE_CONVERSION)
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "image_conversion"},
                )
                document.status = "processing_pdf_to_image"
                db_session.commit()

                ensure_pdf_in_workspace(document_id, db_session)

                list_images_metadata = convert_to_images(document_id, db_session)
                if len(list_images_metadata) > 0:
                    ext = f".{list_images_metadata[0].converted_to_extension.lower()}"

            if ext in ALLOWED_IMAGE_EXTENSIONS:
                images_path = return_list_images_path(document_id, db_session)
                document.status = "processing_ocr"
                db_session.commit()

                if len(images_path) <= 0:
                    raise ValueError("No image paths available for OCR processing")

                if (
                    document.page_count is not None
                    and len(images_path) != document.page_count
                ):
                    document.status = "ocr_failed"
                    db_session.commit()
                    raise RuntimeError(
                        f"Image count mismatch for document {document_id}: "
                        f"got {len(images_path)} images, expected {document.page_count}"
                    )

                total_pages = len(images_path)
                _publish_status(
                    document_id,
                    FilePipelineStage.OCR_PROCESSING,
                    message=f"Starting OCR on {total_pages} pages...",
                    total_pages=total_pages,
                )
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "ocr_processing"},
                )

                for idx, image_path in enumerate(images_path):
                    _publish_status(
                        document_id,
                        FilePipelineStage.OCR_PROCESSING,
                        message=f"Processing page {idx + 1} of {total_pages}...",
                        page_number=idx + 1,
                        total_pages=total_pages,
                    )
                    try:
                        text = extract_image_text(image_path)
                    except Exception as e:
                        logging.getLogger("memory_rag.pipeline").warning(
                            "OCR failed for page %d of document %s: %s",
                            idx + 1,
                            document_id,
                            e,
                        )
                        continue

                    try:
                        save_ocr_page(
                            document_id,
                            str(document.workspace_id),
                            page_number=idx + 1,
                            text=text,
                            db_session=db_session,
                        )
                    except Exception as e:
                        logging.getLogger("memory_rag.pipeline").warning(
                            "Failed to save OCR page %d for document %s: %s",
                            idx + 1,
                            document_id,
                            e,
                        )
                        continue

                document.status = FileStatus.OCR_COMPLETED.value
                db_session.commit()

                # Translation and formatting
                document.status = FileStatus.TRANSLATION_AND_FORMATTING.value
                db_session.commit()

                _publish_status(
                    document_id,
                    FilePipelineStage.TRANSLATION,
                    message="Starting translation and formatting...",
                )
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "translation_and_formatting"},
                )

                try:
                    format_all_markdown(
                        str(document.workspace_id),
                        document_id,
                        db_session,
                    )

                    document.status = FileStatus.TRANSLATION_COMPLETED.value
                    db_session.commit()

                    _publish_status(
                        document_id,
                        FilePipelineStage.COMPLETED,
                        message=(
                            f"Processing completed! {total_pages} pages processed."
                        ),
                        total_pages=total_pages,
                        status="SUCCESS",
                    )

                    return None
                except Exception as format_error:
                    document.status = FileStatus.TRANSLATION_FAILED.value
                    db_session.commit()
                    logging.getLogger("memory_rag.pipeline").error(
                        "Translation/formatting failed for document %s: %s",
                        document_id,
                        format_error,
                    )
                    _publish_status(
                        document_id,
                        FilePipelineStage.FAILED,
                        message=(f"Translation/formatting failed: {format_error}"),
                        status="FAILURE",
                    )
                    raise

    except Exception as e:
        _publish_status(
            document_id,
            FilePipelineStage.FAILED,
            message=str(e),
            status="FAILURE",
        )
        self.update_state(
            state="FAILURE",
            meta={"stage": "failed", "error": str(e)},
        )
        raise
