from unittest.mock import MagicMock, patch

import pytest

from app.core.constant import FilePipelineStage, FileStatus
from app.models.document_history import DocumentHistoryModel


def _mock_task():
    from workers.tasks.file_pipeline import process_file_upload

    task = process_file_upload._get_current_object()
    task.update_state = MagicMock()
    return task


@pytest.mark.unit
class TestFilePipeline:
    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_image_count_mismatch_raises_runtime_error(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 5

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = [
            "p1.png",
            "p2.png",
            "p3.png",
        ]

        task = _mock_task()

        with pytest.raises(RuntimeError, match="Image count mismatch"):
            task.run(document_id)

        assert mock_doc.status == FileStatus.FAILED.value
        mock_ensure_pdf_in_workspace.assert_called_once_with(document_id, mock_session)
        mock_extract_image_text.assert_not_called()
        mock_save_ocr_page.assert_not_called()
        mock_format_all_markdown.assert_not_called()

        mock_redis.publish.assert_called()
        publish_args = mock_redis.publish.call_args
        assert publish_args[0][0] == f"document_updates:{document_id}"

        history_adds = [
            c
            for c in mock_session.add.call_args_list
            if isinstance(c[0][0], DocumentHistoryModel)
        ]
        assert len(history_adds) > 0

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_image_count_match_proceeds_to_ocr(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 3

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = [
            "p1.png",
            "p2.png",
            "p3.png",
        ]
        mock_extract_image_text.side_effect = ["text1", "text2", "text3"]

        task = _mock_task()

        result = task.run(document_id)

        assert mock_doc.status == FileStatus.COMPLETED.value
        mock_ensure_pdf_in_workspace.assert_called_once_with(document_id, mock_session)
        assert result is None
        assert mock_save_ocr_page.call_count == 3
        mock_format_all_markdown.assert_called_once_with(
            "22222222-2222-2222-2222-222222222222",
            document_id,
            mock_session,
        )

        mock_redis.publish.assert_called()
        publish_args = mock_redis.publish.call_args
        assert publish_args[0][0] == f"document_updates:{document_id}"

        history_adds = [
            c
            for c in mock_session.add.call_args_list
            if isinstance(c[0][0], DocumentHistoryModel)
        ]
        assert len(history_adds) > 0

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_image_only_upload_skips_guard(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "photo.png"
        mock_doc.stored_filename = "photo.png"
        mock_doc.mime_type = "image/png"
        mock_doc.page_count = None

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_return_list_images_path.return_value = ["photo.png"]
        mock_extract_image_text.return_value = "image text"

        task = _mock_task()

        result = task.run(document_id)

        assert mock_doc.status == FileStatus.COMPLETED.value
        mock_ensure_pdf_in_workspace.assert_not_called()
        mock_convert_to_images.assert_not_called()
        assert result is None
        mock_extract_image_text.assert_called_once_with("photo.png")
        mock_save_ocr_page.assert_called_once_with(
            document_id,
            "22222222-2222-2222-2222-222222222222",
            page_number=1,
            text="image text",
            db_session=mock_session,
        )
        mock_format_all_markdown.assert_called_once_with(
            "22222222-2222-2222-2222-222222222222",
            document_id,
            mock_session,
        )

        mock_redis.publish.assert_called()
        publish_args = mock_redis.publish.call_args
        assert publish_args[0][0] == f"document_updates:{document_id}"

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_format_failure_sets_failed_status(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 1

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png"]
        mock_extract_image_text.return_value = "text"
        mock_format_all_markdown.side_effect = RuntimeError("Format LLM failed")

        task = _mock_task()

        with pytest.raises(RuntimeError, match="Format LLM failed"):
            task.run(document_id)

        assert mock_doc.status == FileStatus.FAILED.value
        mock_format_all_markdown.assert_called_once_with(
            "22222222-2222-2222-2222-222222222222",
            document_id,
            mock_session,
        )

        mock_redis.publish.assert_called()
        publish_args = mock_redis.publish.call_args
        assert publish_args[0][0] == f"document_updates:{document_id}"

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_document_not_found_raises_value_error(
        self,
        mock_get_sync_db,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session

        task = _mock_task()

        with pytest.raises(ValueError, match="not found in database"):
            task.run(document_id)

        mock_redis.publish.assert_called_once()
        publish_args = mock_redis.publish.call_args
        assert publish_args[0][0] == f"document_updates:{document_id}"
        import json

        payload = json.loads(publish_args[0][1])
        assert payload["status"] == FileStatus.FAILED.value


def _extract_history_rows(mock_session):
    return [
        c[0][0]
        for c in mock_session.add.call_args_list
        if isinstance(c[0][0], DocumentHistoryModel)
    ]


@pytest.mark.unit
class TestFilePipelineHistory:
    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_full_pipeline_writes_history_for_each_step(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 3

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png", "p2.png", "p3.png"]
        mock_extract_image_text.side_effect = ["text1", "text2", "text3"]

        task = _mock_task()
        task.run(document_id)

        rows = _extract_history_rows(mock_session)
        assert len(rows) >= 10

        assert rows[0].status == FileStatus.FILE_UPLOADED.value
        assert rows[0].stage == FilePipelineStage.PENDING.value
        assert rows[0].step == "0/8"

        assert rows[1].stage == FilePipelineStage.IMAGE_CONVERSION.value
        assert rows[1].step == "2/8"

        assert rows[2].status == FileStatus.OCR_STARTED.value
        assert rows[2].stage == FilePipelineStage.OCR_PROCESSING.value
        assert rows[2].step == "3/8"
        assert rows[2].page_number is None

        for i in range(3):
            assert rows[3 + i].stage == FilePipelineStage.OCR_PROCESSING.value
            assert rows[3 + i].page_number == i + 1
            assert rows[3 + i].total_pages == 3

        assert rows[6].status == FileStatus.OCR_FINISHED.value
        assert rows[6].stage == FilePipelineStage.OCR_PROCESSING.value

        assert rows[7].status == FileStatus.TRANSLATION_AND_FORMATTING_STARTED.value
        assert rows[7].stage == FilePipelineStage.TRANSLATION.value
        assert rows[7].step == "5/8"

        assert rows[8].status == FileStatus.TRANSLATION_AND_FORMATTING_FINISHED.value
        assert rows[8].stage == FilePipelineStage.TRANSLATION.value

        assert rows[9].status == FileStatus.COMPLETED.value
        assert rows[9].stage == FilePipelineStage.COMPLETED.value
        assert rows[9].step == "8/8"

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.convert_to_pdf")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_non_pdf_history_includes_conversion_transitions(
        self,
        mock_get_sync_db,
        mock_convert_to_pdf,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        mock_doc.original_filename = "report"
        mock_doc.stored_filename = "report.docx"
        mock_doc.mime_type = "application/msword"
        mock_doc.page_count = None

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_pdf.return_value = MagicMock(
            converted_to_extension="pdf",
            converted_file_path="/tmp/converted.pdf",
        )
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png"]
        mock_extract_image_text.return_value = "text"

        task = _mock_task()
        task.run(document_id)

        rows = _extract_history_rows(mock_session)
        statuses = [r.status for r in rows]
        stages = [r.stage for r in rows]

        assert statuses[0] == FileStatus.FILE_UPLOADED.value
        assert stages[0] == FilePipelineStage.PENDING.value

        assert FileStatus.FILE_CONVERSION_STARTED.value in statuses
        assert FilePipelineStage.PDF_CONVERSION.value in stages
        assert FileStatus.FILE_CONVERSION_FINISHED.value in statuses

        assert stages.count(FilePipelineStage.PDF_CONVERSION.value) == 2

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_document_not_found_writes_failed_history_row(
        self,
        mock_get_sync_db,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session

        task = _mock_task()

        with pytest.raises(ValueError, match="not found in database"):
            task.run(document_id)

        rows = _extract_history_rows(mock_session)
        failed_rows = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed_rows) >= 1
        assert failed_rows[0].stage == FilePipelineStage.FAILED.value
        assert failed_rows[0].step == "0/8"

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_image_count_mismatch_writes_failed_history_row(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 5

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png", "p2.png", "p3.png"]

        task = _mock_task()

        with pytest.raises(RuntimeError, match="Image count mismatch"):
            task.run(document_id)

        rows = _extract_history_rows(mock_session)
        failed_rows = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed_rows) >= 1
        assert failed_rows[-1].stage == FilePipelineStage.FAILED.value
        assert "Image count mismatch" in (failed_rows[-1].message or "")

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_format_failure_writes_failed_history_row(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 1

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png"]
        mock_extract_image_text.return_value = "text"
        mock_format_all_markdown.side_effect = RuntimeError("Format LLM failed")

        task = _mock_task()

        with pytest.raises(RuntimeError, match="Format LLM failed"):
            task.run(document_id)

        rows = _extract_history_rows(mock_session)
        failed_rows = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed_rows) >= 2
        assert all(r.stage == FilePipelineStage.FAILED.value for r in failed_rows)
        assert any(
            "Translation/formatting failed" in (r.message or "") for r in failed_rows
        )

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.convert_to_pdf")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_non_pdf_convert_failure_writes_failed_history_row(
        self,
        mock_get_sync_db,
        mock_convert_to_pdf,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        mock_doc.original_filename = "report"
        mock_doc.stored_filename = "report.docx"
        mock_doc.mime_type = "application/msword"
        mock_doc.page_count = None

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_pdf.side_effect = RuntimeError("LibreOffice crashed")

        task = _mock_task()

        with pytest.raises(RuntimeError, match="LibreOffice crashed"):
            task.run(document_id)

        rows = _extract_history_rows(mock_session)
        failed_rows = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed_rows) >= 1
        assert failed_rows[-1].stage == FilePipelineStage.FAILED.value

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_convert_to_images_failure_writes_failed_history_row(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 2

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.side_effect = RuntimeError("Image conversion died")

        task = _mock_task()

        with pytest.raises(RuntimeError, match="Image conversion died"):
            task.run(document_id)

        rows = _extract_history_rows(mock_session)
        failed_rows = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed_rows) >= 1
        assert failed_rows[-1].stage == FilePipelineStage.FAILED.value
        assert failed_rows[-1].step == "0/8"

        mock_extract_image_text.assert_not_called()
        mock_format_all_markdown.assert_not_called()

    @patch("workers.tasks.file_pipeline.redis_client")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_redis_publish_failure_still_writes_history_row(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_redis,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
        mock_doc.stored_filename = "test.pdf"
        mock_doc.mime_type = "application/pdf"
        mock_doc.page_count = 1

        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = mock_doc

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session

        mock_get_sync_db.return_value = mock_session
        mock_convert_to_images.return_value = [MagicMock(converted_to_extension="png")]
        mock_return_list_images_path.return_value = ["p1.png"]
        mock_extract_image_text.return_value = "text"

        from redis.exceptions import ConnectionError as RedisConnectionError

        mock_redis.publish.side_effect = RedisConnectionError("Redis is down")

        task = _mock_task()
        task.run(document_id)

        rows = _extract_history_rows(mock_session)
        assert len(rows) >= 1
        assert rows[-1].status == FileStatus.COMPLETED.value
        assert rows[-1].stage == FilePipelineStage.COMPLETED.value
