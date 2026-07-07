import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.file_conversions import FileConversionModel


@pytest.mark.unit
class TestFormatAllMarkdown:
    def test_raises_when_no_txt_records(self):
        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.all.return_value = []

        from app.services.format.format import format_all_markdown

        with pytest.raises(ValueError, match="No files txt for this operation"):
            format_all_markdown("ws-1", "doc-1", db_session)

    @patch("app.services.format.format.translate_content")
    @patch("app.services.format.format.format_markdown")
    def test_generates_translated_md_files(
        self, mock_format_markdown, mock_translate_content
    ):
        mock_txt_1 = MagicMock(spec=FileConversionModel)
        mock_txt_1.converted_file_path = "/tmp/dummy_page_001.txt"
        mock_txt_2 = MagicMock(spec=FileConversionModel)
        mock_txt_2.converted_file_path = "/tmp/dummy_page_002.txt"

        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.all.return_value = [
            mock_txt_1,
            mock_txt_2,
        ]
        db_session.execute.return_value.scalars.return_value.first.return_value = None

        mock_translate_content.side_effect = lambda text, lang: (
            f"translated_{lang.value}_{text}"
        )
        mock_format_markdown.side_effect = lambda text: f"md({text})"

        with (
            patch("builtins.open"),
            patch("pathlib.Path.mkdir"),
        ):
            from app.services.format.format import format_all_markdown

            with tempfile.TemporaryDirectory() as tmpdir:
                # Write two dummy txt files
                f1 = Path(tmpdir) / "dummy_page_001.txt"
                f1.write_text("page one", encoding="utf-8")
                f2 = Path(tmpdir) / "dummy_page_002.txt"
                f2.write_text("page two", encoding="utf-8")
                mock_txt_1.converted_file_path = str(f1)
                mock_txt_2.converted_file_path = str(f2)

                format_all_markdown("ws-1", "doc-1", db_session)

        assert mock_translate_content.call_count == 4
        assert mock_format_markdown.call_count == 4

        assert db_session.add.call_count == 4
        assert db_session.commit.call_count == 4

    @patch("app.services.format.format.translate_content")
    @patch("app.services.format.format.format_markdown")
    def test_skips_existing_md_files(
        self, mock_format_markdown, mock_translate_content
    ):
        mock_txt = MagicMock(spec=FileConversionModel)
        mock_txt.converted_file_path = "/tmp/dummy_page_001.txt"

        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.all.return_value = [
            mock_txt
        ]
        # Simulate that the md record already exists
        existing_md = MagicMock(spec=FileConversionModel)
        existing_md.id = "existing-uuid"
        db_session.execute.return_value.scalars.return_value.first.return_value = (
            existing_md
        )

        mock_translate_content.return_value = "translated text"
        mock_format_markdown.return_value = "formatted md"

        with (
            patch("builtins.open"),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            from app.services.format.format import format_all_markdown

            with tempfile.TemporaryDirectory() as tmpdir:
                f = Path(tmpdir) / "dummy_page_001.txt"
                f.write_text("page one", encoding="utf-8")
                mock_txt.converted_file_path = str(f)

                format_all_markdown("ws-1", "doc-1", db_session)

        # Should NOT add or commit new records since the md already exists
        db_session.add.assert_not_called()
        db_session.commit.assert_not_called()

    def test_extracts_page_number_from_filename(self):
        from app.services.format.format import _extract_page_number

        assert (
            _extract_page_number("/app/brain/ws/doc-1_OCR_page_001.txt", "doc-1") == 1
        )
        assert (
            _extract_page_number("/app/brain/ws/doc-1_OCR_page_042.txt", "doc-1") == 42
        )
        assert (
            _extract_page_number("/app/brain/ws/doc-1_OCR_page_142.txt", "doc-1") == 142
        )
        # No match
        assert _extract_page_number("/app/brain/ws/doc-2_random.txt", "doc-2") == 0

    @patch("app.services.format.format.translate_content")
    @patch("app.services.format.format.format_markdown")
    def test_continues_on_per_page_failure(
        self, mock_format_markdown, mock_translate_content
    ):
        mock_txt_1 = MagicMock(spec=FileConversionModel)
        mock_txt_1.converted_file_path = "/tmp/ok_page_001.txt"
        mock_txt_2 = MagicMock(spec=FileConversionModel)
        mock_txt_2.converted_file_path = "/tmp/bad_page_002.txt"

        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.all.return_value = [
            mock_txt_1,
            mock_txt_2,
        ]
        db_session.execute.return_value.scalars.return_value.first.return_value = None

        mock_translate_content.side_effect = [
            "en_text_page1",
            "jp_text_page1",
            RuntimeError("LLM failure"),
            RuntimeError("LLM failure"),
        ]
        mock_format_markdown.side_effect = [
            "md_en_1",
            "md_jp_1",
        ]

        with (
            patch("pathlib.Path.mkdir"),
            patch("builtins.open"),
        ):
            from app.services.format.format import format_all_markdown

            with tempfile.TemporaryDirectory() as tmpdir:
                ok1 = Path(tmpdir) / "ok_page_001.txt"
                ok1.write_text("page one", encoding="utf-8")
                bad = Path(tmpdir) / "bad_page_002.txt"
                bad.write_text("bad content", encoding="utf-8")
                mock_txt_1.converted_file_path = str(ok1)
                mock_txt_2.converted_file_path = str(bad)

                format_all_markdown("ws-1", "doc-1", db_session)

        # Page 1 succeeded: 2 adds (EN + JP)
        # Page 2 failed: 0 adds
        assert db_session.add.call_count == 2
        assert mock_format_markdown.call_count == 2
