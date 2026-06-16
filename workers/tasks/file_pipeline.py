from datetime import datetime
import json
from typing import Any

from app.core.constant import ALLOWED_IMAGE_EXTENSIONS, FilePipelineStage
from app.core.database import get_sync_db
from app.core.redis_client import redis_client
from app.models.file import FileModel
from app.services.ocr.file_ocr import extract_image_text
from app.services.storage.file_sync import (
    convert_to_images,
    convert_to_pdf,
    return_list_images_path,
)
from workers.celery_app import celery_app


def _publish_status(
    file_id: str,
    stage: FilePipelineStage,
    message: str | None = None,
    page_number: int | None = None,
    total_pages: int | None = None,
    status: str = "PROGRESS",
):
    """Publish a progress update to Redis for WebSocket relay.

    Args:
        file_id: UUID of the file being processed.
        stage: Current pipeline stage (determines step and message defaults).
        message: Custom status message. Falls back to stage.message.
        page_number: 1-indexed current page (OCR stage only).
        total_pages: Total pages to process.
        status: Status label (PROGRESS, SUCCESS, or FAILURE).
    """
    redis_client.publish(
        f"file_updates:{file_id}",
        json.dumps(
            {
                "status": status,
                "step": stage.step,
                "stage": stage.value,
                "message": message or stage.message,
                "file_id": file_id,
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
def process_file_upload(self, file_id: str) -> list[dict[str, Any]]:
    """Process a file upload through the full pipeline.

    For non-image documents: converts to PDF, then to images.
    For images or generated images: runs OCR on each page.

    Publishes real-time status updates to Redis for WebSocket relay.
    """
    try:
        with get_sync_db() as db_session:
            file_record = db_session.query(FileModel).filter_by(id=file_id).first()
            if not file_record:
                raise ValueError(f"File with ID {file_id} not found in database.")

            ext = f".{file_record.file_extension.lstrip('.').lower()}"

            if ext not in ALLOWED_IMAGE_EXTENSIONS and ext != ".pdf":
                _publish_status(file_id, FilePipelineStage.PDF_CONVERSION)
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "pdf_conversion"},
                )
                file_record.status = "processing_document_to_pdf"
                db_session.commit()
                converted_pdf_result = convert_to_pdf(file_id, db_session)
                ext = f".{str(converted_pdf_result.converted_to_extension).lstrip('.').lower()}"

            if ext == ".pdf":
                _publish_status(file_id, FilePipelineStage.IMAGE_CONVERSION)
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "image_conversion"},
                )
                file_record.status = "processing_pdf_to_image"
                db_session.commit()

                list_images_metadata = convert_to_images(file_id, db_session)
                if len(list_images_metadata) > 0:
                    ext = f".{str(list_images_metadata[0].converted_to_extension).lstrip('.').lower()}"

            if ext in ALLOWED_IMAGE_EXTENSIONS:
                images_path = return_list_images_path(file_id, db_session)
                file_record.status = "processing_ocr"
                db_session.commit()

                if len(images_path) <= 0:
                    raise ValueError("No image paths available for OCR processing")

                total_pages = len(images_path)
                _publish_status(
                    file_id,
                    FilePipelineStage.OCR_PROCESSING,
                    message=f"Starting OCR on {total_pages} pages...",
                    total_pages=total_pages,
                )
                self.update_state(
                    state="PROGRESS",
                    meta={"stage": "ocr_processing"},
                )

                ocr_results: list[dict[str, Any]] = []
                for idx, image_path in enumerate(images_path):
                    try:
                        _publish_status(
                            file_id,
                            FilePipelineStage.OCR_PROCESSING,
                            message=f"Processing page {idx + 1} of {total_pages}...",
                            page_number=idx + 1,
                            total_pages=total_pages,
                        )
                        text = extract_image_text(image_path)
                        ocr_results.append(
                            {
                                "page_number": idx,
                                "image_path": image_path,
                                "text": text,
                            }
                        )
                    except Exception as e:
                        raise RuntimeError(
                            f"OCR failed on page {idx} ({image_path}): {str(e)}"
                        )

                file_record.status = "ocr_completed"
                db_session.commit()

                _publish_status(
                    file_id,
                    FilePipelineStage.COMPLETED,
                    message=f"Processing completed! {total_pages} pages processed.",
                    total_pages=total_pages,
                    status="SUCCESS",
                )

                return ocr_results

    except Exception as e:
        _publish_status(
            file_id,
            FilePipelineStage.FAILED,
            message=str(e),
            status="FAILURE",
        )
        self.update_state(
            state="FAILURE",
            meta={"stage": "failed", "error": str(e)},
        )
        raise RuntimeError(f"Error while processing the files: {str(e)}")
