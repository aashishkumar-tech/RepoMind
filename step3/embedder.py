"""
step3/embedder.py — Text Embedding Generator (OpenAI)

HOW IT WORKS:
─────────────
Converts text (excerpts, triage summaries, plans) into 1536-dimensional
vectors using OpenAI's text-embedding-3-small model.

WHY THIS MODEL:
    - text-embedding-3-small: best cost-performance ratio ($0.02/1M tokens)
    - 1536 dimensions (high-quality semantic vectors)
    - No local GPU needed — lightweight API call
    - Fits in Lambda easily (just the openai package ~1MB)

USAGE:
    from step3.embedder import Embedder
    embedder = Embedder()
    vector = embedder.embed_text("ModuleNotFoundError: No module named 'lodash'")
    vectors = embedder.embed_batch(["text1", "text2", "text3"])

COMMUNICATION:
─────────────
Called by:
    step3/indexer.py   → embed excerpt + triage + plan before upserting to Qdrant
    step3/retriever.py → embed the query text before searching Qdrant
"""

from typing import List
from openai import OpenAI

from shared.logger import get_logger
from shared.config import settings

logger = get_logger("step3.embedder")

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
MODEL_NAME = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# ──────────────────────────────────────────────
# Module-level client cache (lazy-loaded)
# ──────────────────────────────────────────────
_client = None


def _get_client() -> OpenAI:
    """Get or create the OpenAI client (cached)."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("openai_client_initialized", model=MODEL_NAME, dim=EMBEDDING_DIM)
    return _client


class Embedder:
    """
    Generates dense vector embeddings from text using OpenAI text-embedding-3-small.

    Thread-safe for sequential calls.
    Client is created lazily on first embed call.
    """

    def __init__(self, model_name: str = MODEL_NAME):
        self._model_name = model_name

    def embed_text(self, text: str) -> List[float]:
        """
        Embed a single text string into a 1536-dimensional vector.

        Args:
            text: Any text string (excerpt, summary, query, etc.)

        Returns:
            List of 1536 floats
        """
        client = _get_client()
        response = client.embeddings.create(
            model=self._model_name,
            input=text,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """
        Embed multiple texts in a batch (sent in one API call).

        Args:
            texts: List of text strings
            batch_size: How many to encode at once (default 100, OpenAI max ~2048)

        Returns:
            List of vectors, one per input text
        """
        if not texts:
            return []

        client = _get_client()
        all_vectors = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = client.embeddings.create(
                model=self._model_name,
                input=batch,
            )
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_vectors.extend([d.embedding for d in sorted_data])

        return all_vectors

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (1536 for text-embedding-3-small)."""
        return EMBEDDING_DIM
