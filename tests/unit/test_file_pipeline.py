from unittest.mock import MagicMock, patch

import pytest

from app.core.constant import FileStatus


def _mock_task():
    from workers.tasks.file_pipeline import process_file_upload

    task = process_file_upload._get_current_object()
    task.update_state = MagicMock()
    return task


@pytest.mark.unit
class TestFilePipeline:
    @patch("workers.tasks.file_pipeline._publish_status")
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
        mock_publish_status,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
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

        assert mock_doc.status == "ocr_failed"
        mock_ensure_pdf_in_workspace.assert_called_once_with(document_id, mock_session)
        mock_session.commit.assert_called()
        mock_extract_image_text.assert_not_called()
        mock_save_ocr_page.assert_not_called()
        mock_format_all_markdown.assert_not_called()

    @patch("workers.tasks.file_pipeline._publish_status")
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
        mock_publish_status,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
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

        assert mock_doc.status == FileStatus.TRANSLATION_COMPLETED.value
        mock_ensure_pdf_in_workspace.assert_called_once_with(document_id, mock_session)
        assert result is None
        assert mock_save_ocr_page.call_count == 3
        mock_format_all_markdown.assert_called_once_with(
            "22222222-2222-2222-2222-222222222222",
            document_id,
            mock_session,
        )

    @patch("workers.tasks.file_pipeline._publish_status")
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
        mock_publish_status,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "photo.png"
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

        assert mock_doc.status == FileStatus.TRANSLATION_COMPLETED.value
        mock_ensure_pdf_in_workspace.assert_not_called()
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

    @patch("workers.tasks.file_pipeline._publish_status")
    @patch("workers.tasks.file_pipeline.format_all_markdown")
    @patch("workers.tasks.file_pipeline.save_ocr_page")
    @patch("workers.tasks.file_pipeline.extract_image_text")
    @patch("workers.tasks.file_pipeline.return_list_images_path")
    @patch("workers.tasks.file_pipeline.ensure_pdf_in_workspace")
    @patch("workers.tasks.file_pipeline.convert_to_images")
    @patch("workers.tasks.file_pipeline.get_sync_db")
    def test_format_failure_sets_translation_failed(
        self,
        mock_get_sync_db,
        mock_convert_to_images,
        mock_ensure_pdf_in_workspace,
        mock_return_list_images_path,
        mock_extract_image_text,
        mock_save_ocr_page,
        mock_format_all_markdown,
        mock_publish_status,
    ):
        document_id = "11111111-1111-1111-1111-111111111111"

        mock_doc = MagicMock()
        mock_doc.id = document_id
        mock_doc.workspace_id = "22222222-2222-2222-2222-222222222222"
        mock_doc.original_filename = "test.pdf"
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

        assert mock_doc.status == FileStatus.TRANSLATION_FAILED.value
        mock_format_all_markdown.assert_called_once_with(
            "22222222-2222-2222-2222-222222222222",
            document_id,
            mock_session,
        )
