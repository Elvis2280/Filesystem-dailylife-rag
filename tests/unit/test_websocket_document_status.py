from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constant import FileStatus


@pytest.mark.unit
class TestStreamDocumentStatus:
    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_returns_immediately_when_current_state_is_completed(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = {
            "type": "current_state",
            "status": FileStatus.COMPLETED.value,
            "document_id": "doc-1",
        }

        from app.services.websocket.document_status import stream_document_status

        await stream_document_status("doc-1")

        mock_send_state.assert_awaited_once_with("doc-1")
        mock_get_redis.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_returns_immediately_when_current_state_is_failed(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = {
            "type": "current_state",
            "status": FileStatus.FAILED.value,
            "document_id": "doc-1",
        }

        from app.services.websocket.document_status import stream_document_status

        await stream_document_status("doc-1")

        mock_send_state.assert_awaited_once_with("doc-1")
        mock_get_redis.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_sends_current_state_on_connect(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = {
            "type": "current_state",
            "status": FileStatus.OCR_STARTED.value,
            "document_id": "doc-1",
        }

        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)
        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_get_redis.return_value = mock_redis

        from app.services.websocket.document_status import stream_document_status

        with patch("app.services.websocket.document_status.manager") as mock_manager:
            mock_manager.send_message = AsyncMock()

            call_count = 0

            async def fake_get_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise StopAsyncIteration
                return None

            mock_pubsub.get_message.side_effect = fake_get_message

            try:
                await stream_document_status("doc-1")
            except StopAsyncIteration:
                pass

        mock_send_state.assert_awaited_once_with("doc-1")
        mock_get_redis.assert_awaited()

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_breaks_on_terminal_pubsub_message(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = {
            "type": "current_state",
            "status": FileStatus.OCR_STARTED.value,
            "document_id": "doc-1",
        }

        mock_pubsub = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_get_redis.return_value = mock_redis

        terminal_message = {
            "type": "message",
            "data": '{"status": "completed", "document_id": "doc-1"}',
        }
        mock_pubsub.get_message = AsyncMock(return_value=terminal_message)

        from app.services.websocket.document_status import stream_document_status

        with patch("app.services.websocket.document_status.manager") as mock_manager:
            mock_manager.send_message = AsyncMock()

            await stream_document_status("doc-1")

        mock_manager.send_message.assert_any_await(
            "doc-1",
            {"status": "completed", "document_id": "doc-1"},
        )

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_sends_ping_on_get_message_timeout(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = {
            "type": "current_state",
            "status": FileStatus.OCR_STARTED.value,
            "document_id": "doc-1",
        }

        mock_pubsub = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_get_redis.return_value = mock_redis

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # timeout -> should send ping
            return {
                "type": "message",
                "data": '{"status": "completed", "document_id": "doc-1"}',
            }

        mock_pubsub.get_message.side_effect = fake_get_message

        from app.services.websocket.document_status import stream_document_status

        with patch("app.services.websocket.document_status.manager") as mock_manager:
            mock_manager.send_message = AsyncMock()

            await stream_document_status("doc-1")

        mock_manager.send_message.assert_any_await("doc-1", {"type": "ping"})

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._send_current_state")
    async def test_skips_when_no_state_and_no_redis(
        self, mock_send_state, mock_get_redis
    ):
        mock_send_state.return_value = None

        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(side_effect=StopAsyncIteration("exit loop"))
        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_get_redis.return_value = mock_redis

        from app.services.websocket.document_status import stream_document_status

        with patch("app.services.websocket.document_status.manager") as mock_manager:
            mock_manager.send_message = AsyncMock()

            try:
                await stream_document_status("nonexistent-doc")
            except StopAsyncIteration:
                pass

        mock_send_state.assert_awaited_once_with("nonexistent-doc")

    @pytest.mark.asyncio
    @patch("app.services.websocket.document_status.get_async_redis_client")
    @patch("app.services.websocket.document_status._get_current_state")
    async def test_ws_connection_after_multiple_steps_sends_latest_step(
        self, mock_get_state, mock_get_redis
    ):
        """After 3 steps are recorded (0/8, 1/8, 2/8), WS connects and receives
        the latest step (2/8), not the first (0/8)."""
        latest_state = {
            "type": "current_state",
            "status": "file_conversion_finished",
            "step": "2/8",
            "stage": "image_conversion",
            "message": "Image conversion finished",
            "document_id": "doc-1",
            "page_number": None,
            "total_pages": 3,
            "timestamp": "2026-07-22T12:05:00",
        }
        mock_get_state.return_value = latest_state

        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(side_effect=StopAsyncIteration("exit loop"))
        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_get_redis.return_value = mock_redis

        from app.services.websocket.document_status import stream_document_status

        with patch("app.services.websocket.document_status.manager") as mock_manager:
            mock_manager.send_message = AsyncMock()

            try:
                await stream_document_status("doc-1")
            except StopAsyncIteration:
                pass

        mock_get_state.assert_awaited_once_with("doc-1")
        mock_manager.send_message.assert_awaited_once_with("doc-1", latest_state)
        mock_get_redis.assert_awaited()


@pytest.mark.unit
class TestGetCurrentState:
    DOC_ID = "11111111-1111-1111-1111-111111111111"

    @pytest.mark.asyncio
    async def test_returns_history_when_exists(self):
        from app.services.websocket.document_status import _get_current_state

        mock_history = MagicMock()
        mock_history.status = "ocr_started"
        mock_history.stage = "ocr_processing"
        mock_history.step = "3/8"
        mock_history.message = "Running OCR..."
        mock_history.page_number = 2
        mock_history.total_pages = 5
        mock_history.created_at = MagicMock()
        mock_history.created_at.isoformat.return_value = "2026-07-22T12:00:00"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_history

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.websocket.document_status.async_session"
        ) as mock_session_cls:
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _get_current_state(self.DOC_ID)

        assert result is not None
        assert result["type"] == "current_state"
        assert result["status"] == "ocr_started"
        assert result["stage"] == "ocr_processing"
        assert result["step"] == "3/8"
        assert result["message"] == "Running OCR..."
        assert result["page_number"] == 2
        assert result["total_pages"] == 5
        assert result["timestamp"] == "2026-07-22T12:00:00"
        assert result["document_id"] == self.DOC_ID

    @pytest.mark.asyncio
    async def test_falls_back_to_document_when_no_history(self):
        from app.services.websocket.document_status import _get_current_state

        mock_doc = MagicMock()
        mock_doc.status = "file_uploaded"
        mock_doc.page_count = 10
        mock_doc.created_at = MagicMock()
        mock_doc.created_at.isoformat.return_value = "2026-07-22T11:00:00"

        history_result = MagicMock()
        history_result.scalar_one_or_none.return_value = None

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = mock_doc

        call_count = 0

        async def fake_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return history_result
            return doc_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute

        with patch(
            "app.services.websocket.document_status.async_session"
        ) as mock_session_cls:
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _get_current_state(self.DOC_ID)

        assert result is not None
        assert result["type"] == "current_state"
        assert result["status"] == "file_uploaded"
        assert result["stage"] is None
        assert result["step"] is None
        assert result["message"] == "Pending"
        assert result["total_pages"] == 10
        assert result["timestamp"] == "2026-07-22T11:00:00"

    @pytest.mark.asyncio
    async def test_returns_none_when_document_not_found(self):
        from app.services.websocket.document_status import _get_current_state

        history_result = MagicMock()
        history_result.scalar_one_or_none.return_value = None

        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = None

        call_count = 0

        async def fake_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return history_result
            return doc_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute

        with patch(
            "app.services.websocket.document_status.async_session"
        ) as mock_session_cls:
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _get_current_state("22222222-2222-2222-2222-222222222222")

        assert result is None
