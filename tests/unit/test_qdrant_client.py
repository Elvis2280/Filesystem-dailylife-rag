from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.models import Distance

from app.core.config import settings


@pytest.mark.unit
class TestQdrantClient:
    def test_get_qdrant_client_uses_settings_host_and_port(self):
        from app.services.rag.qdrant_client import get_qdrant_client

        with patch("app.services.rag.qdrant_client.QdrantClient") as mock_cls:
            get_qdrant_client()

        mock_cls.assert_called_once_with(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )

    def test_ensure_collection_creates_when_missing(self):
        from qdrant_client.models import VectorParams

        from app.services.rag.qdrant_client import ensure_collection

        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False

        ensure_collection(mock_client, vector_size=3)

        mock_client.create_collection.assert_called_once_with(
            collection_name="documents",
            vectors_config=VectorParams(size=3, distance=Distance.COSINE),
        )

    def test_ensure_collection_skips_when_exists(self):
        from app.services.rag.qdrant_client import ensure_collection

        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        ensure_collection(mock_client, vector_size=3)

        mock_client.create_collection.assert_not_called()

    def test_upsert_rejects_empty_vectors(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        with pytest.raises(ValueError, match="No texts or vectors"):
            upsert_embeddings(
                document_id="d",
                workspace_id="w",
                page_number=1,
                language="en",
                texts=[],
                vectors=[],
                raw_ocr="",
                japanese_text="",
            )

    def test_upsert_rejects_length_mismatch(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        with pytest.raises(ValueError, match="must match"):
            upsert_embeddings(
                document_id="d",
                workspace_id="w",
                page_number=1,
                language="en",
                texts=["a", "b"],
                vectors=[[0.1]],
                raw_ocr="raw",
                japanese_text="ja",
            )

    def test_upsert_creates_points_with_payload_and_deterministic_ids(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            upsert_embeddings(
                document_id="doc-1",
                workspace_id="ws-1",
                page_number=3,
                language="en",
                texts=["chunk one", "chunk two"],
                vectors=[[0.1, 0.2], [0.3, 0.4]],
                raw_ocr="raw ocr text",
                japanese_text="日本語テキスト",
            )

        mock_client.upsert.assert_called_once()
        points = mock_client.upsert.call_args.kwargs["points"]
        assert len(points) == 2

        p0 = points[0]
        assert p0.payload["document_id"] == "doc-1"
        assert p0.payload["workspace_id"] == "ws-1"
        assert p0.payload["page_number"] == 3
        assert p0.payload["chunk_index"] == 0
        assert p0.payload["language"] == "en"
        assert p0.payload["text"] == "chunk one"
        assert p0.payload["raw_ocr"] == "raw ocr text"
        assert p0.payload["japanese_text"] == "日本語テキスト"
        assert p0.vector == [0.1, 0.2]

        p1 = points[1]
        assert p1.payload["chunk_index"] == 1
        assert p1.payload["text"] == "chunk two"
        assert p1.vector == [0.3, 0.4]

        assert p0.id != p1.id

    def test_upsert_ids_are_deterministic(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        def run():
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            with patch(
                "app.services.rag.qdrant_client.get_qdrant_client",
                return_value=mock_client,
            ):
                upsert_embeddings(
                    document_id="doc-1",
                    workspace_id="ws-1",
                    page_number=3,
                    language="en",
                    texts=["chunk"],
                    vectors=[[0.1, 0.2]],
                    raw_ocr="raw",
                    japanese_text="ja",
                )
            return mock_client.upsert.call_args.kwargs["points"][0].id

        assert run() == run()

    def test_upsert_creates_collection_with_vector_size(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            upsert_embeddings(
                document_id="d",
                workspace_id="w",
                page_number=1,
                language="en",
                texts=["chunk"],
                vectors=[[0.1, 0.2, 0.3]],
                raw_ocr="raw",
                japanese_text="ja",
            )

        create_call = mock_client.create_collection.call_args.kwargs
        assert create_call["collection_name"] == "documents"
        assert create_call["vectors_config"].size == 3
        assert create_call["vectors_config"].distance == Distance.COSINE

    def test_upsert_raises_runtime_error_on_upsert_failure(self):
        from app.services.rag.qdrant_client import upsert_embeddings

        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True
        mock_client.upsert.side_effect = RuntimeError("Qdrant is down")

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="Qdrant is down"):
                upsert_embeddings(
                    document_id="d",
                    workspace_id="w",
                    page_number=1,
                    language="en",
                    texts=["chunk"],
                    vectors=[[0.1]],
                    raw_ocr="raw",
                    japanese_text="ja",
                )

    def test_search_embeddings_filters_by_workspace_with_limit(self):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from app.services.rag.qdrant_client import search_embeddings

        mock_client = MagicMock()
        mock_client.query_points.return_value.points = []

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            search_embeddings([0.1, 0.2], "ws-1")

        call_kwargs = mock_client.query_points.call_args.kwargs
        assert call_kwargs["query"] == [0.1, 0.2]
        assert call_kwargs["limit"] == 3
        query_filter = call_kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert query_filter.must == [
            FieldCondition(key="workspace_id", match=MatchValue(value="ws-1"))
        ]

    def test_search_embeddings_returns_raw_points(self):
        from app.services.rag.qdrant_client import search_embeddings

        mock_point = MagicMock()
        mock_point.id = "p1"
        mock_point.score = 0.91
        mock_point.payload = {"text": "chunk one"}

        mock_client = MagicMock()
        mock_client.query_points.return_value.points = [mock_point]

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            results = search_embeddings([0.1, 0.2], "ws-1")

        assert results == [
            {"id": "p1", "score": 0.91, "payload": {"text": "chunk one"}}
        ]

    def test_search_embeddings_rejects_empty_vector(self):
        from app.services.rag.qdrant_client import search_embeddings

        with pytest.raises(ValueError, match="No vector"):
            search_embeddings([], "ws-1")

    def test_search_embeddings_raises_runtime_error_on_failure(self):
        from app.services.rag.qdrant_client import search_embeddings

        mock_client = MagicMock()
        mock_client.query_points.side_effect = RuntimeError("Qdrant is down")

        with patch(
            "app.services.rag.qdrant_client.get_qdrant_client",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="Qdrant is down"):
                search_embeddings([0.1], "ws-1")
