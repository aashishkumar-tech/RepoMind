"""
step3/retriever.py — Similarity Search (Qdrant Query)

HOW IT WORKS:
─────────────
Searches the Qdrant vector database for past events that are
semantically similar to a given query text.

USE CASES:
    1. RAG for Triage (Step 5):
       "This excerpt looks like a dependency_error. Have we seen similar?"
       → Returns top-K past events with same failure pattern
       → Helps LLM make better triage decisions

    2. Analytics Dashboard:
       "Show me all failures similar to 'ModuleNotFoundError: pandas'"
       → Returns ranked list of similar incidents

    3. De-duplication:
       "Is this the same failure we saw yesterday?"
       → High similarity score = likely duplicate

SEARCH FLOW:
    1. Embed the query text → 384-dim vector
    2. Send to Qdrant with optional filters (repo, failure_type, etc.)
    3. Get top-K results ranked by cosine similarity
    4. Return results with metadata (event_id, repo, score, preview)

FILTERING:
    Qdrant supports payload filtering during search:
    - Filter by repo (only search your own failures)
    - Filter by failure_type (only show dependency_error matches)
    - Filter by embedding_type (only search excerpts, not plans)
    - Filter by date range

COMMUNICATION:
─────────────
Step 5 (triage.py) can call:
    retriever = Retriever()
    similar = retriever.search("ModuleNotFoundError: No module named 'flask'", top_k=5)
    → Returns list of similar past incidents for context
"""

from typing import List, Dict, Any, Optional

from shared.config import settings
from shared.logger import get_logger
from step3.embedder import Embedder, EMBEDDING_DIM

logger = get_logger("step3.retriever")

COLLECTION_NAME = "repomind_events"


class SearchResult:
    """A single search result from Qdrant."""

    def __init__(self, score: float, payload: Dict[str, Any]):
        self.score = score
        self.event_id = payload.get("event_id", "")
        self.repo = payload.get("repo", "")
        self.embedding_type = payload.get("embedding_type", "")
        self.failure_type = payload.get("failure_type", "unknown")
        self.confidence = payload.get("confidence", 0.0)
        self.text_preview = payload.get("text_preview", "")
        self.timestamp = payload.get("timestamp", "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "event_id": self.event_id,
            "repo": self.repo,
            "embedding_type": self.embedding_type,
            "failure_type": self.failure_type,
            "confidence": self.confidence,
            "text_preview": self.text_preview,
            "timestamp": self.timestamp,
        }

    def __repr__(self):
        return f"SearchResult(score={self.score:.3f}, type={self.failure_type}, repo={self.repo})"


class Retriever:
    """
    Searches Qdrant for semantically similar past CI failures.
    """

    def __init__(self):
        self.embedder = Embedder()
        self._qdrant = None

    def _get_qdrant(self):
        """Lazy-load Qdrant client."""
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
        return self._qdrant

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        repo_filter: Optional[str] = None,
        failure_type_filter: Optional[str] = None,
        embedding_type_filter: Optional[str] = None,
        score_threshold: float = 0.3,
    ) -> List[SearchResult]:
        """
        Search for similar past events by text query.

        Args:
            query_text: The text to search for (e.g. an error message)
            top_k: Number of results to return (default 5)
            repo_filter: Only return results from this repo
            failure_type_filter: Only return this failure type
            embedding_type_filter: Only search "excerpt", "triage", etc.
            score_threshold: Minimum cosine similarity (0.0 to 1.0)

        Returns:
            List of SearchResult objects, sorted by descending score
        """
        # Step 1: Embed the query
        query_vector = self.embedder.embed_text(query_text)

        # Step 2: Build filters
        query_filter = self._build_filter(
            repo_filter=repo_filter,
            failure_type_filter=failure_type_filter,
            embedding_type_filter=embedding_type_filter,
        )

        # Step 3: Search Qdrant
        try:
            client = self._get_qdrant()
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=score_threshold,
            )

            search_results = [
                SearchResult(score=hit.score, payload=hit.payload)
                for hit in results
            ]

            logger.info(
                "search_completed",
                query_preview=query_text[:100],
                results_count=len(search_results),
                top_score=search_results[0].score if search_results else 0.0,
            )

            return search_results

        except Exception as e:
            logger.error("search_failed", error=str(e), query_preview=query_text[:50])
            return []

    def search_similar_failures(
        self,
        excerpt: str,
        repo: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Convenience method for RAG retrieval in Step 5 (triage).

        Searches for past excerpts similar to the current failure.
        Returns dicts ready to inject into LLM prompt context.

        Args:
            excerpt: Current failure excerpt
            repo: Optionally scope to same repo
            top_k: Number of past incidents to retrieve

        Returns:
            List of dicts with {failure_type, summary, score}
        """
        results = self.search(
            query_text=excerpt,
            top_k=top_k,
            repo_filter=repo,
            embedding_type_filter="excerpt",
            score_threshold=0.4,
        )

        return [r.to_dict() for r in results]

    def _build_filter(
        self,
        repo_filter: Optional[str] = None,
        failure_type_filter: Optional[str] = None,
        embedding_type_filter: Optional[str] = None,
    ):
        """Build Qdrant filter from optional criteria."""
        conditions = []

        if repo_filter:
            from qdrant_client.models import FieldCondition, MatchValue
            conditions.append(
                FieldCondition(key="repo", match=MatchValue(value=repo_filter))
            )

        if failure_type_filter:
            from qdrant_client.models import FieldCondition, MatchValue
            conditions.append(
                FieldCondition(key="failure_type", match=MatchValue(value=failure_type_filter))
            )

        if embedding_type_filter:
            from qdrant_client.models import FieldCondition, MatchValue
            conditions.append(
                FieldCondition(key="embedding_type", match=MatchValue(value=embedding_type_filter))
            )

        if conditions:
            from qdrant_client.models import Filter
            return Filter(must=conditions)

        return None
