"""
step3/indexer.py — Vector DB Indexer (Qdrant Upsert)

HOW IT WORKS:
─────────────
Takes pipeline artifacts (excerpt, triage, plan, verification) and:
    1. Generates embeddings using step3/embedder.py
    2. Upserts vectors + metadata into Qdrant collection
    3. Saves embedding JSON files to S3 for backup

QDRANT COLLECTION DESIGN:
    Collection: "repomind_events"
    Vector size: 1536 (OpenAI text-embedding-3-small)
    Distance: Cosine similarity

    Each event produces 2-4 points (one per embedding type):
        - excerpt_embedding    (always)
        - triage_embedding     (if triage succeeded)
        - plan_embedding       (if plan generated)
        - verification_embedding (if verification ran)

POINT METADATA (payload in Qdrant):
    {
        "event_id": "evt-...",
        "repo": "user/mlproject",
        "embedding_type": "excerpt",
        "failure_type": "dependency_error",
        "confidence": 0.87,
        "timestamp": "2026-02-13T15:44:00Z",
        "text_preview": "First 200 chars of the embedded text..."
    }

WHY STORE IN QDRANT:
    - Fast similarity search → "find similar past failures"
    - Filtering by repo, failure_type, confidence, etc.
    - Powers the RAG retrieval in Step 5 (triage uses past incidents)

COMMUNICATION:
─────────────
Worker (step2/worker.py) can call after pipeline completion:
    indexer = Indexer()
    indexer.index_event(event_id, repo, excerpt, triage, plan)
Retriever (step3/retriever.py) searches the same collection.

S3 STORAGE:
    embeddings/<repo-slug>/<event-id>/excerpt_embedding.json
    embeddings/<repo-slug>/<event-id>/triage_embedding.json
    embeddings/<repo-slug>/<event-id>/plan_embedding.json
"""

import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from shared.config import settings
from shared.event_id import extract_repo_slug
from shared.storage import get_storage
from shared.logger import get_logger
from step3.embedder import Embedder, EMBEDDING_DIM

logger = get_logger("step3.indexer")

# ──────────────────────────────────────────────
# Qdrant collection config
# ──────────────────────────────────────────────
COLLECTION_NAME = "repomind_events"


class Indexer:
    """
    Indexes pipeline artifacts into Qdrant and backs up embeddings to S3.
    """

    def __init__(self):
        self.embedder = Embedder()
        self.storage = get_storage()
        self._qdrant = None

    def _get_qdrant(self):
        """Lazy-load Qdrant client and ensure collection exists."""
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._qdrant = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )

            # Create collection if it doesn't exist
            collections = [c.name for c in self._qdrant.get_collections().collections]
            if COLLECTION_NAME not in collections:
                self._qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("qdrant_collection_created", name=COLLECTION_NAME)

        return self._qdrant

    def index_event(
        self,
        event_id: str,
        repo: str,
        excerpt: Optional[str] = None,
        triage: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Index all artifacts from a single pipeline event into Qdrant.

        Generates embeddings for each available artifact and upserts them.
        Also saves embedding JSON files to S3 for backup.

        Args:
            event_id: The unique event ID
            repo: Full repo name (e.g. "user/mlproject")
            excerpt: The log excerpt text
            triage: Triage result dict (failure_type, confidence, summary)
            plan: Plan summary dict (playbook_id, actions)
            verification: Verification result dict

        Returns:
            Number of vectors indexed
        """
        repo_slug = extract_repo_slug(event_id)
        s3_base = f"embeddings/{repo_slug}/{event_id}"
        points = []
        timestamp = datetime.now(timezone.utc).isoformat()

        # ── Excerpt embedding ──
        if excerpt:
            vector = self.embedder.embed_text(excerpt)
            point = self._build_point(
                event_id=event_id,
                repo=repo,
                embedding_type="excerpt",
                vector=vector,
                text=excerpt,
                timestamp=timestamp,
                extra_payload={"failure_type": triage.get("failure_type", "unknown") if triage else "unknown"},
            )
            points.append(point)
            self._save_embedding_s3(s3_base, "excerpt_embedding", vector, excerpt)

        # ── Triage embedding ──
        if triage and triage.get("summary"):
            triage_text = f"{triage['failure_type']}: {triage['summary']}"
            vector = self.embedder.embed_text(triage_text)
            point = self._build_point(
                event_id=event_id,
                repo=repo,
                embedding_type="triage",
                vector=vector,
                text=triage_text,
                timestamp=timestamp,
                extra_payload={
                    "failure_type": triage.get("failure_type", "unknown"),
                    "confidence": triage.get("confidence", 0.0),
                },
            )
            points.append(point)
            self._save_embedding_s3(s3_base, "triage_embedding", vector, triage_text)

        # ── Plan embedding ──
        if plan and plan.get("actions"):
            plan_text = f"Playbook: {plan.get('playbook_id', 'custom')}. Actions: {', '.join(plan.get('actions', []))}"
            vector = self.embedder.embed_text(plan_text)
            point = self._build_point(
                event_id=event_id,
                repo=repo,
                embedding_type="plan",
                vector=vector,
                text=plan_text,
                timestamp=timestamp,
                extra_payload={"playbook_id": plan.get("playbook_id", "custom")},
            )
            points.append(point)
            self._save_embedding_s3(s3_base, "plan_embedding", vector, plan_text)

        # ── Verification embedding ──
        if verification and verification.get("details"):
            verify_text = f"Verification: {verification['status']} - {verification['details']}"
            vector = self.embedder.embed_text(verify_text)
            point = self._build_point(
                event_id=event_id,
                repo=repo,
                embedding_type="verification",
                vector=vector,
                text=verify_text,
                timestamp=timestamp,
                extra_payload={"verification_status": verification.get("status", "unknown")},
            )
            points.append(point)
            self._save_embedding_s3(s3_base, "verification_embedding", vector, verify_text)

        # ── Upsert to Qdrant ──
        if points:
            try:
                client = self._get_qdrant()
                from qdrant_client.models import PointStruct
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=points,
                )
                logger.info(
                    "vectors_indexed",
                    event_id=event_id,
                    count=len(points),
                    types=[p.payload["embedding_type"] for p in points],
                )
            except Exception as e:
                logger.error("qdrant_upsert_failed", event_id=event_id, error=str(e))
                # Non-fatal: embeddings are backed up in S3

        return len(points)

    # ──────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────
    def _build_point(
        self,
        event_id: str,
        repo: str,
        embedding_type: str,
        vector: List[float],
        text: str,
        timestamp: str,
        extra_payload: Optional[Dict[str, Any]] = None,
    ):
        """Build a Qdrant PointStruct with metadata payload."""
        from qdrant_client.models import PointStruct

        payload = {
            "event_id": event_id,
            "repo": repo,
            "embedding_type": embedding_type,
            "text_preview": text[:200],
            "timestamp": timestamp,
        }
        if extra_payload:
            payload.update(extra_payload)

        return PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=payload,
        )

    def _save_embedding_s3(
        self,
        s3_base: str,
        name: str,
        vector: List[float],
        source_text: str,
    ) -> None:
        """Backup embedding to S3 as JSON."""
        try:
            data = {
                "model": self.embedder._model_name,
                "dimension": self.embedder.dimension,
                "vector": vector,
                "source_text_preview": source_text[:500],
            }
            self.storage.put_json(f"{s3_base}/{name}.json", data)
        except Exception as e:
            logger.warning("embedding_s3_backup_failed", name=name, error=str(e))
