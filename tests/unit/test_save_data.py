import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.constant import FilePipelineStage, FileStatus
from app.models.document_history import DocumentHistoryModel

DOCUMENT_ID = "11111111-1111-1111-1111-111111111111"
WORKSPACE_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _no_real_qdrant_upsert():
    with patch("workers.tasks.save_data.upsert_embeddings") as mock_upsert:
        yield mock_upsert


def _mock_task():
    from workers.tasks.save_data import process_save_data

    task = process_save_data._get_current_object()
    task.update_state = MagicMock()
    return task


def _make_document(page_count):
    mock_doc = MagicMock()
    mock_doc.id = DOCUMENT_ID
    mock_doc.workspace_id = WORKSPACE_ID
    mock_doc.page_count = page_count
    return mock_doc


def _mock_session(document):
    mock_query = MagicMock()
    mock_query.filter_by.return_value.first.return_value = document
    mock_session = MagicMock()
    mock_session.query.return_value = mock_query
    mock_session.__enter__.return_value = mock_session
    return mock_session


def _extract_history_rows(mock_session):
    return [
        c[0][0]
        for c in mock_session.add.call_args_list
        if isinstance(c[0][0], DocumentHistoryModel)
    ]


def _write_page(
    root,
    page,
    raw: str | None = None,
    en: str | None = None,
    ja: str | None = None,
):
    files_dir = root / WORKSPACE_ID / "files"
    en_dir = root / WORKSPACE_ID / "translation" / "english"
    ja_dir = root / WORKSPACE_ID / "translation" / "japanese"
    if raw is not None:
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / f"{DOCUMENT_ID}_OCR_page_{page:03d}.txt").write_text(
            raw, encoding="utf-8"
        )
    if en is not None:
        en_dir.mkdir(parents=True, exist_ok=True)
        (en_dir / f"{DOCUMENT_ID}_page_{page:03d}.md").write_text(en, encoding="utf-8")
    if ja is not None:
        ja_dir.mkdir(parents=True, exist_ok=True)
        (ja_dir / f"{DOCUMENT_ID}_page_{page:03d}.md").write_text(ja, encoding="utf-8")


@pytest.mark.unit
class TestSaveData:
    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_document_not_found_raises_value_error(self, mock_get_sync_db, mock_redis):
        mock_query = MagicMock()
        mock_query.filter_by.return_value.first.return_value = None
        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        mock_session.__enter__.return_value = mock_session
        mock_get_sync_db.return_value = mock_session

        task = _mock_task()
        with pytest.raises(ValueError, match="No document with ID"):
            task.run(DOCUMENT_ID)

        rows = _extract_history_rows(mock_session)
        failed = [r for r in rows if r.status == FileStatus.FAILED.value]
        assert len(failed) >= 1
        assert failed[-1].stage == FilePipelineStage.FAILED.value

        mock_redis.publish.assert_called()
        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert payload["status"] == FileStatus.FAILED.value

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_page_count_none_raises_value_error(self, mock_get_sync_db, mock_redis):
        mock_get_sync_db.return_value = _mock_session(_make_document(None))

        task = _mock_task()
        with pytest.raises(ValueError, match="no page_count"):
            task.run(DOCUMENT_ID)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_page_count_zero_raises_value_error(self, mock_get_sync_db, mock_redis):
        mock_get_sync_db.return_value = _mock_session(_make_document(0))

        task = _mock_task()
        with pytest.raises(ValueError, match="no page_count"):
            task.run(DOCUMENT_ID)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_happy_path_reads_all_three_files_per_page(
        self,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(2)
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x

        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert "page 1 cleaned for document" in caplog.text
        assert "page 2 cleaned for document" in caplog.text
        assert "raw=5 chars, en=4 chars, ja=4 chars" in caplog.text

        rows = _extract_history_rows(mock_session)
        stages = [r.stage for r in rows]

        assert FilePipelineStage.VERIFY_FILES.value in stages
        assert stages.count(FilePipelineStage.COLLECTING_DATA.value) == 2
        assert stages.count(FilePipelineStage.PREPARING_DATA.value) == 2
        assert stages.count(FilePipelineStage.SAVING_DATA.value) == 1
        assert stages[-1] == FilePipelineStage.COMPLETED.value

        collecting = [
            r for r in rows if r.stage == FilePipelineStage.COLLECTING_DATA.value
        ]
        preparing = [
            r for r in rows if r.stage == FilePipelineStage.PREPARING_DATA.value
        ]
        assert sorted(r.page_number for r in collecting) == [1, 2]
        assert sorted(r.page_number for r in preparing) == [1, 2]
        assert all(r.total_pages == 2 for r in collecting + preparing)

        completed = [r for r in rows if r.status == FileStatus.COMPLETED.value]
        assert len(completed) >= 1
        assert completed[-1].stage == FilePipelineStage.COMPLETED.value
        assert document.status == FileStatus.COMPLETED.value

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_missing_ocr_file_raises_file_not_found_with_path(
        self, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, en="en 1", ja="ja 1")

        task = _mock_task()
        with pytest.raises(FileNotFoundError, match="Missing OCR page 1"):
            task.run(DOCUMENT_ID)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_missing_english_md_raises_file_not_found_with_path(
        self, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", ja="ja 1")

        task = _mock_task()
        with pytest.raises(FileNotFoundError, match="Missing English page 1"):
            task.run(DOCUMENT_ID)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    def test_missing_japanese_md_raises_file_not_found_with_path(
        self, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1")

        task = _mock_task()
        with pytest.raises(FileNotFoundError, match="Missing Japanese page 1"):
            task.run(DOCUMENT_ID)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_missing_ocr_file_aborts_before_preparing(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(2)
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, en="en 2", ja="ja 2")

        task = _mock_task()
        with pytest.raises(FileNotFoundError, match="Missing OCR page 2"):
            task.run(DOCUMENT_ID)

        rows = _extract_history_rows(mock_session)
        collecting = [
            r for r in rows if r.stage == FilePipelineStage.COLLECTING_DATA.value
        ]
        preparing = [
            r for r in rows if r.stage == FilePipelineStage.PREPARING_DATA.value
        ]
        assert any(r.page_number == 2 for r in collecting)
        assert not any(r.page_number == 2 for r in preparing)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_sub_stages_emitted_in_expected_order(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(1)
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        rows = _extract_history_rows(mock_session)
        ordered_stages = [r.stage for r in rows]
        index_of = {stage: ordered_stages.index(stage) for stage in ordered_stages}

        expected = [
            FilePipelineStage.VERIFY_FILES.value,
            FilePipelineStage.COLLECTING_DATA.value,
            FilePipelineStage.PREPARING_DATA.value,
            FilePipelineStage.SAVING_DATA.value,
            FilePipelineStage.COMPLETED.value,
        ]
        positions = [index_of[stage] for stage in expected]
        assert positions == sorted(positions)

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_saving_data_emitted_once_after_loop(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(2)
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        rows = _extract_history_rows(mock_session)
        saving = [r for r in rows if r.stage == FilePipelineStage.SAVING_DATA.value]
        assert len(saving) == 1
        assert saving[0].step == FilePipelineStage.SAVING_DATA.step

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_save_data_sets_document_status_completed_at_end(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(1)
        document.status = FileStatus.FILE_PROCESS_FINISHED.value
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        assert document.status == FileStatus.COMPLETED.value

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_file_process_finished_emitted_in_history_not_completed(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        document = _make_document(1)
        mock_session = _mock_session(document)
        mock_get_sync_db.return_value = mock_session
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        rows = _extract_history_rows(mock_session)
        statuses = [r.status for r in rows]
        assert FileStatus.COMPLETED.value in statuses
        assert statuses[-1] == FileStatus.COMPLETED.value

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_clean_text_called_once_per_variable_per_page(
        self, mock_clean_text, mock_get_sync_db, mock_redis, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(2))
        mock_clean_text.side_effect = lambda x: x
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        assert mock_clean_text.call_count == 6
        inputs = [c.args[0] for c in mock_clean_text.call_args_list]
        assert inputs == ["raw 1", "en 1", "ja 1", "raw 2", "en 2", "ja 2"]

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_variables_replaced_with_cleaned_values(
        self,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.side_effect = ["CLEANED RAW", "CLEANED EN", "CLEANED JA"]

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert "raw=11 chars, en=10 chars, ja=10 chars" in caplog.text

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_log_emits_raw_text_cleaned_line_per_page(
        self,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.side_effect = lambda x: x

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert "raw_text cleaned: raw 1" in caplog.text
        assert "english_markdown cleaned: en 1" in caplog.text
        assert "japanese_markdown cleaned: ja 1" in caplog.text

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_page_skipped_when_all_three_cleaned_texts_empty(
        self,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_session = _mock_session(_make_document(2))
        mock_get_sync_db.return_value = mock_session
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")
        mock_clean_text.return_value = ""

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert mock_clean_text.call_count == 6
        assert "no content after cleaning" in caplog.text
        assert "page 1 cleaned for document" not in caplog.text
        assert "page 2 cleaned for document" not in caplog.text

        rows = _extract_history_rows(mock_session)
        saving = [r for r in rows if r.stage == FilePipelineStage.SAVING_DATA.value]
        assert len(saving) == 1
        completed = [r for r in rows if r.status == FileStatus.COMPLETED.value]
        assert len(completed) >= 1

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    def test_page_kept_when_at_least_one_cleaned_text_non_empty(
        self,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.side_effect = ["", "en cleaned", ""]

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert "page 1 cleaned for document" in caplog.text
        assert "raw=0 chars, en=10 chars, ja=0 chars" in caplog.text

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    @patch("workers.tasks.save_data.embedding")
    @patch("workers.tasks.save_data._chunk_english")
    def test_english_markdown_is_chunked_with_cleaned_value(
        self,
        mock_chunk_english,
        mock_embedding,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.side_effect = ["raw", "CLEANED EN", "ja"]
        mock_chunk_english.return_value = ["c1", "c2"]
        mock_embedding.side_effect = lambda chunks: chunks

        task = _mock_task()
        task.run(DOCUMENT_ID)

        mock_chunk_english.assert_called_once_with("CLEANED EN")
        mock_embedding.assert_called_once_with(["c1", "c2"])

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    @patch("workers.tasks.save_data.embedding")
    @patch("workers.tasks.save_data._chunk_english")
    def test_embedding_result_assigned_to_embedding_data_and_logged(
        self,
        mock_chunk_english,
        mock_embedding,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.side_effect = lambda x: x
        mock_chunk_english.return_value = ["c1", "c2"]
        mock_embedding.return_value = ["e1", "e2"]

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        mock_embedding.assert_called_once_with(["c1", "c2"])
        assert "produced 2 English chunks" in caplog.text
        assert "embedded 2 vectors" in caplog.text

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    @patch("workers.tasks.save_data.embedding")
    @patch("workers.tasks.save_data._chunk_english")
    def test_log_emits_chunked_and_embedded_lines_per_page(
        self,
        mock_chunk_english,
        mock_embedding,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(2))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")
        mock_clean_text.side_effect = lambda x: x
        mock_chunk_english.return_value = ["c1"]
        mock_embedding.side_effect = lambda chunks: chunks

        task = _mock_task()
        with caplog.at_level(logging.INFO, logger="memory_rag.save_data"):
            task.run(DOCUMENT_ID)

        assert "page 1 produced 1 English chunks" in caplog.text
        assert "page 2 produced 1 English chunks" in caplog.text
        assert "page 1 embedded 1 vectors" in caplog.text
        assert "page 2 embedded 1 vectors" in caplog.text

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    @patch("workers.tasks.save_data.embedding")
    @patch("workers.tasks.save_data._chunk_english")
    def test_page_skipped_when_all_empty_does_not_chunk_or_embed(
        self,
        mock_chunk_english,
        mock_embedding,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(1))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        mock_clean_text.return_value = ""
        mock_chunk_english.side_effect = AssertionError("should not chunk")
        mock_embedding.side_effect = AssertionError("should not embed")

        task = _mock_task()
        task.run(DOCUMENT_ID)

        mock_chunk_english.assert_not_called()
        mock_embedding.assert_not_called()

    @patch("workers.tasks.save_data.redis_client")
    @patch("workers.tasks.save_data.get_sync_db")
    @patch("workers.tasks.save_data.clean_text")
    @patch("workers.tasks.save_data.embedding")
    @patch("workers.tasks.save_data._chunk_english")
    def test_upsert_called_per_page_with_payload(
        self,
        mock_chunk_english,
        mock_embedding,
        mock_clean_text,
        mock_get_sync_db,
        mock_redis,
        tmp_path,
        monkeypatch,
        _no_real_qdrant_upsert,
    ):
        monkeypatch.setattr(settings, "BRAIN_WORKSPACES_PATH", str(tmp_path))
        mock_get_sync_db.return_value = _mock_session(_make_document(2))
        _write_page(tmp_path, 1, raw="raw 1", en="en 1", ja="ja 1")
        _write_page(tmp_path, 2, raw="raw 2", en="en 2", ja="ja 2")
        mock_clean_text.side_effect = lambda x: x
        mock_chunk_english.return_value = ["c1", "c2"]
        mock_embedding.return_value = [[0.1, 0.2], [0.3, 0.4]]

        task = _mock_task()
        task.run(DOCUMENT_ID)

        assert _no_real_qdrant_upsert.call_count == 2

        first = _no_real_qdrant_upsert.call_args_list[0].kwargs
        assert first["document_id"] == DOCUMENT_ID
        assert first["workspace_id"] == WORKSPACE_ID
        assert first["page_number"] == 1
        assert first["language"] == "en"
        assert first["texts"] == ["c1", "c2"]
        assert first["vectors"] == [[0.1, 0.2], [0.3, 0.4]]
        assert first["raw_ocr"] == "raw 1"
        assert first["japanese_text"] == "ja 1"

        second = _no_real_qdrant_upsert.call_args_list[1].kwargs
        assert second["page_number"] == 2
        assert second["raw_ocr"] == "raw 2"
        assert second["japanese_text"] == "ja 2"
