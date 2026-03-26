"""
tests/test_step3.py — Unit tests for Step 3 (Embedder, Indexer, Retriever)

Tests the embedding generator, vector indexer, and retriever with mocked
OpenAI API and Qdrant to avoid real API calls in CI.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestEmbedder:
    """Test the Embedder class."""

    @patch("step3.embedder._get_client")
    def test_embed_text_returns_list_of_floats(self, mock_get_client):
        """embed_text should return a list of floats."""
        mock_client = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from step3.embedder import Embedder
        embedder = Embedder()
        result = embedder.embed_text("test failure log")

        assert isinstance(result, list)
        assert len(result) == 1536
        assert all(isinstance(v, float) for v in result)
        mock_client.embeddings.create.assert_called_once()

    @patch("step3.embedder._get_client")
    def test_embed_batch_returns_multiple_vectors(self, mock_get_client):
        """embed_batch should return one vector per input text."""
        mock_client = MagicMock()

        mock_data = []
        for i in range(3):
            m = MagicMock()
            m.index = i
            m.embedding = [0.1] * 1536
            mock_data.append(m)

        mock_response = MagicMock()
        mock_response.data = mock_data
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from step3.embedder import Embedder
        embedder = Embedder()
        results = embedder.embed_batch(["text1", "text2", "text3"])

        assert len(results) == 3
        assert all(len(v) == 1536 for v in results)

    @patch("step3.embedder._get_client")
    def test_embed_batch_empty_input(self, mock_get_client):
        """embed_batch with empty list should return empty list."""
        from step3.embedder import Embedder
        embedder = Embedder()
        results = embedder.embed_batch([])

        assert results == []
        mock_get_client.assert_not_called()

    def test_dimension_property(self):
        """dimension should return 1536."""
        from step3.embedder import Embedder
        embedder = Embedder()
        assert embedder.dimension == 1536


class TestIndexer:
    """Test the Indexer class with mocked dependencies."""

    @patch("step3.indexer.Embedder")
    @patch("step3.indexer.get_storage")
    def test_index_event_with_excerpt_only(self, mock_storage_fn, mock_embedder_cls):
        """Indexing with just an excerpt should produce 1 point."""
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = [0.1] * 1536
        mock_embedder._model_name = "test"
        mock_embedder.dimension = 1536
        mock_embedder_cls.return_value = mock_embedder

        mock_storage = MagicMock()
        mock_storage_fn.return_value = mock_storage

        from step3.indexer import Indexer
        indexer = Indexer()
        indexer.embedder = mock_embedder
        indexer.storage = mock_storage

        # Mock Qdrant to avoid real connection
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="repomind_events")]
        )
        indexer._qdrant = mock_qdrant

        count = indexer.index_event(
            event_id="evt-test-repo-123-20260213T154400Z",
            repo="test/repo",
            excerpt="ModuleNotFoundError: No module named 'flask'",
        )

        assert count == 1
        mock_embedder.embed_text.assert_called_once()
        mock_qdrant.upsert.assert_called_once()

    @patch("step3.indexer.Embedder")
    @patch("step3.indexer.get_storage")
    def test_index_event_with_all_artifacts(self, mock_storage_fn, mock_embedder_cls):
        """Indexing with all artifacts should produce 3 points."""
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = [0.1] * 1536
        mock_embedder._model_name = "test"
        mock_embedder.dimension = 1536
        mock_embedder_cls.return_value = mock_embedder

        mock_storage = MagicMock()
        mock_storage_fn.return_value = mock_storage

        from step3.indexer import Indexer
        indexer = Indexer()
        indexer.embedder = mock_embedder
        indexer.storage = mock_storage

        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="repomind_events")]
        )
        indexer._qdrant = mock_qdrant

        count = indexer.index_event(
            event_id="evt-test-repo-123-20260213T154400Z",
            repo="test/repo",
            excerpt="Error log",
            triage={"failure_type": "dependency_error", "confidence": 0.9, "summary": "Missing flask"},
            plan={"playbook_id": "fix_pip_install", "actions": ["pip install flask"]},
        )

        assert count == 3
        assert mock_embedder.embed_text.call_count == 3


class TestRetriever:
    """Test the Retriever class with mocked Qdrant."""

    @patch("step3.retriever.Embedder")
    def test_search_returns_results(self, mock_embedder_cls):
        """search should return SearchResult objects."""
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = [0.1] * 1536
        mock_embedder_cls.return_value = mock_embedder

        from step3.retriever import Retriever, SearchResult

        retriever = Retriever()
        retriever.embedder = mock_embedder

        # Mock Qdrant search results
        mock_hit = MagicMock()
        mock_hit.score = 0.85
        mock_hit.payload = {
            "event_id": "evt-old-123",
            "repo": "test/repo",
            "embedding_type": "excerpt",
            "failure_type": "dependency_error",
            "text_preview": "Missing flask module",
            "timestamp": "2026-01-01T00:00:00Z",
        }

        mock_qdrant = MagicMock()
        mock_qdrant.search.return_value = [mock_hit]
        retriever._qdrant = mock_qdrant

        results = retriever.search("ModuleNotFoundError: flask")

        assert len(results) == 1
        assert results[0].score == 0.85
        assert results[0].failure_type == "dependency_error"

    @patch("step3.retriever.Embedder")
    def test_search_handles_qdrant_failure(self, mock_embedder_cls):
        """search should return empty list on Qdrant failure."""
        mock_embedder = MagicMock()
        mock_embedder.embed_text.return_value = [0.1] * 1536
        mock_embedder_cls.return_value = mock_embedder

        from step3.retriever import Retriever

        retriever = Retriever()
        retriever.embedder = mock_embedder

        mock_qdrant = MagicMock()
        mock_qdrant.search.side_effect = Exception("Connection refused")
        retriever._qdrant = mock_qdrant

        results = retriever.search("some error")
        assert results == []
