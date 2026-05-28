"""Celery task for OCR file processing."""

from datetime import datetime, timezone

from app.core.database import sync_session
from app.models.file import FileModel
from app.services.ocr.extractor import extract_text
from workers.celery_app import celery_app


@celery_app.task(name="workers.ocr.tasks.process_file", bind=True, max_retries=3)
def process_file(self, file_id: str, storage_path: str, mime_type: str):
    """Extract text from a file using OCR and update the database record.

    Args:
        file_id: UUID of the file record in the database.
        storage_path: Absolute path to the file on disk.
        mime_type: MIME type of the file.
    """
    try:
        text = extract_text(storage_path, mime_type)

        with sync_session() as session:
            file_record = session.query(FileModel).filter_by(id=file_id).first()
            if file_record:
                file_record.status = "completed"
                file_record.extracted_text = text
                file_record.processed_at = datetime.now(timezone.utc)
                session.commit()

        return {"file_id": file_id, "status": "completed", "text_length": len(text)}

    except Exception as e:
        with sync_session() as session:
            file_record = session.query(FileModel).filter_by(id=file_id).first()
            if file_record:
                file_record.status = "failed"
                session.commit()

        raise self.retry(exc=e, countdown=60)
