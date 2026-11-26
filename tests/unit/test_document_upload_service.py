import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constant import DocumentsType
from app.models.document_history import DocumentHistoryModel
from app.models.file_conversions import FileConversionModel


def _make_upload_file(filename: str, content_type: str, data: bytes = b"fake-bytes"):
    mock_file = MagicMock()
    mock_file.file = BytesIO(data)
    mock_file.filename = filename
    mock_file.content_type = content_type
    return mock_file


@pytest.mark.unit
class TestProcessDocumentUpload:
    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_pdf_upload_writes_initial_history_row(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("test.pdf", "application/pdf")
            mock_db = AsyncMock()
            mock_to_thread.return_value = None

            mock_task_instance = MagicMock()
            mock_task_instance.id = "celery-task-abc"
            mock_dispatch.delay.return_value = mock_task_instance

            document, task_id = await process_document_upload(
                workspace_id="22222222-2222-2222-2222-222222222222",
                file=mock_file,
                db=mock_db,
            )

            history_adds = [
                c
                for c in mock_db.add.call_args_list
                if isinstance(c[0][0], DocumentHistoryModel)
            ]
            assert len(history_adds) == 1
            history_row = history_adds[0][0][0]
            assert history_row.status == "file_uploaded"
            assert history_row.stage == "pending"
            assert history_row.step == "0/12"
            assert history_row.message == "File uploaded, queued for processing"

    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_non_pdf_upload_writes_initial_history_row(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("report.docx", "application/msword")
            mock_db = AsyncMock()
            mock_to_thread.return_value = None

            mock_task_instance = MagicMock()
            mock_task_instance.id = "celery-task-def"
            mock_dispatch.delay.return_value = mock_task_instance

            document, task_id = await process_document_upload(
                workspace_id="44444444-4444-4444-4444-444444444444",
                file=mock_file,
                db=mock_db,
            )

            history_adds = [
                c
                for c in mock_db.add.call_args_list
                if isinstance(c[0][0], DocumentHistoryModel)
            ]
            assert len(history_adds) == 1
            h = history_adds[0][0][0]
            assert h.status == "file_uploaded"
            assert h.stage == "pending"
            assert h.step == "0/12"

    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_pdf_upload_also_writes_file_conversion_record(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("slides.pdf", "application/pdf")
            mock_db = AsyncMock()
            mock_to_thread.return_value = None

            mock_task_instance = MagicMock()
            mock_task_instance.id = "celery-task-ghi"
            mock_dispatch.delay.return_value = mock_task_instance

            await process_document_upload(
                workspace_id="66666666-6666-6666-6666-666666666666",
                file=mock_file,
                db=mock_db,
            )

            conversion_adds = [
                c
                for c in mock_db.add.call_args_list
                if isinstance(c[0][0], FileConversionModel)
            ]
            assert len(conversion_adds) == 1
            rec = conversion_adds[0][0][0]
            assert rec.document_type == DocumentsType.ORIGINAL_FILE.value
            assert rec.converted_to_extension == "pdf"
            assert rec.converted_mime_type == "application/pdf"

    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_dispatch_pipeline_called_and_redis_setex(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("77777777-7777-7777-7777-777777777777")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("notes.txt", "text/plain")
            mock_db = AsyncMock()
            mock_to_thread.return_value = None

            mock_task_instance = MagicMock()
            mock_task_instance.id = "celery-task-jkl"
            mock_dispatch.delay.return_value = mock_task_instance

            document, task_id = await process_document_upload(
                workspace_id="88888888-8888-8888-8888-888888888888",
                file=mock_file,
                db=mock_db,
            )

            mock_dispatch.delay.assert_called_once_with(str(fixed_id))
            mock_redis.setex.assert_called_once_with(
                f"document_task:{fixed_id}", 1800, "celery-task-jkl"
            )
            assert task_id == "celery-task-jkl"

    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_corrupt_pdf_raises_before_history_row(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("bad.pdf", "application/pdf")
            mock_db = AsyncMock()

            call_count = 0

            async def fake_to_thread(fn, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return None
                raise RuntimeError("cannot open")

            mock_to_thread.side_effect = fake_to_thread

            with pytest.raises(ValueError, match="Could not read PDF"):
                await process_document_upload(
                    workspace_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    file=mock_file,
                    db=mock_db,
                )

            history_adds = [
                c
                for c in mock_db.add.call_args_list
                if isinstance(c[0][0], DocumentHistoryModel)
            ]
            assert len(history_adds) == 0
            mock_dispatch.delay.assert_not_called()
            mock_redis.setex.assert_not_called()

    @patch("app.services.storage.document.redis_client")
    @patch("app.services.storage.document.dispatch_pipeline_task")
    @patch("app.services.storage.document.Path")
    @patch("app.services.storage.document.asyncio.to_thread")
    async def test_disk_write_failure_raises_before_history_row(
        self,
        mock_to_thread,
        mock_path_cls,
        mock_dispatch,
        mock_redis,
    ):
        from app.services.storage.document import process_document_upload

        fixed_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
        with patch("app.services.storage.document.uuid.uuid4", return_value=fixed_id):
            mock_file = _make_upload_file("big.pdf", "application/pdf")
            mock_db = AsyncMock()

            mock_to_thread.side_effect = OSError("disk full")

            with pytest.raises(OSError, match="disk full"):
                await process_document_upload(
                    workspace_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                    file=mock_file,
                    db=mock_db,
                )

            history_adds = [
                c
                for c in mock_db.add.call_args_list
                if isinstance(c[0][0], DocumentHistoryModel)
            ]
            assert len(history_adds) == 0
            mock_dispatch.delay.assert_not_called()
            mock_redis.setex.assert_not_called()
