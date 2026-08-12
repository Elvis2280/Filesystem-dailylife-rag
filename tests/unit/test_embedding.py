from unittest.mock import patch

import pytest

from app.core.config import settings


@pytest.mark.unit
class TestEmbedding:
    def test_embedding_rejects_empty_list(self):
        from app.services.rag.embedding import embedding

        with pytest.raises(ValueError, match="No text"):
            embedding([])

    def test_embedding_rejects_empty_text(self):
        from app.services.rag.embedding import embedding

        with pytest.raises(ValueError, match="empty"):
            embedding(["", "valid"])

    def test_embedding_rejects_whitespace_only_text(self):
        from app.services.rag.embedding import embedding

        with pytest.raises(ValueError, match="empty"):
            embedding(["   \n  "])

    def test_embedding_calls_ollama_with_model_and_all_texts(self):
        from app.services.rag.embedding import embedding

        with patch("app.services.rag.embedding.OllamaSyncClient") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]

            result = embedding(["chunk one", "chunk two"])

        mock_client.embed.assert_called_once_with(
            model=settings.OLLAMA_MODEL_EMBEDDING,
            input=["chunk one", "chunk two"],
        )
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_embedding_returns_list_of_lists_of_floats(self):
        from app.services.rag.embedding import embedding

        with patch("app.services.rag.embedding.OllamaSyncClient") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.embed.return_value = [[0.0, 1.0], [2.0, 3.0]]

            result = embedding(["a", "b"])

        assert isinstance(result, list)
        assert all(isinstance(v, list) for v in result)
        assert all(isinstance(x, float) for v in result for x in v)

    def test_embedding_propagates_runtime_error(self):
        from app.services.rag.embedding import embedding

        with patch("app.services.rag.embedding.OllamaSyncClient") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.embed.side_effect = RuntimeError("Ollama is down")

            with pytest.raises(RuntimeError, match="Ollama is down"):
                embedding(["chunk"])

    def test_embedding_error_logged_to_console(self, caplog):
        from app.services.rag.embedding import embedding

        with (
            patch("app.services.rag.embedding.OllamaSyncClient") as mock_cls,
            caplog.at_level("ERROR", logger="memory_rag.embedding"),
        ):
            mock_cls.return_value.embed.side_effect = RuntimeError("boom")

            with pytest.raises(RuntimeError):
                embedding(["chunk"])

        assert "boom" in caplog.text
