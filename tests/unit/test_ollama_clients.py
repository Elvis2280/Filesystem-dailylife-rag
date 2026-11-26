from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestOllamaSyncClient:
    def test_generate_disables_streaming_and_thinking(self):
        from app.services.ai.ollama_sync import OllamaSyncClient

        with patch("app.services.ai.ollama_sync.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.chat.return_value.message.content = "response text"

            client = OllamaSyncClient()
            result = client.generate("some-model", "prompt")

        assert result == "response text"
        call_kwargs = mock_client.chat.call_args.kwargs
        assert call_kwargs["stream"] is False
        assert call_kwargs["think"] is False
        assert call_kwargs["model"] == "some-model"

    def test_generate_sends_image_when_provided(self):
        from app.services.ai.ollama_sync import OllamaSyncClient

        with patch("app.services.ai.ollama_sync.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.chat.return_value.message.content = "text"

            client = OllamaSyncClient()
            client.generate("some-model", "prompt", image="/tmp/page.png")

        message = mock_client.chat.call_args.kwargs["messages"][0]
        assert message["images"] == ["/tmp/page.png"]


@pytest.mark.unit
class TestOllamaClient:
    @pytest.mark.asyncio
    async def test_generate_async_sends_think_and_stream_false(self):
        from unittest.mock import AsyncMock

        from app.services.ai.ollama_client import OllamaClient

        with patch("app.services.ai.ollama_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock()
            mock_resp = mock_client.post.return_value
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"message": {"content": "hi"}})

            client = OllamaClient()
            result = await client.generate_async("some-model", "prompt")

        assert result == "hi"
        body = mock_client.post.call_args.kwargs["json"]
        assert body["model"] == "some-model"
        assert body["stream"] is False
        assert body["think"] is False
        assert "thinking" not in body
