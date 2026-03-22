"""
shared/storage.py — S3 Storage Abstraction Layer

HOW IT WORKS:
─────────────
Provides a clean interface over S3 operations.
All pipeline artifacts are stored/retrieved through this module.

S3 STRUCTURE (from architecture spec):
    events/<repo-slug>/<event-id>/logs/full_logs.txt
    events/<repo-slug>/<event-id>/logs/excerpt.txt
    events/<repo-slug>/<event-id>/artifacts.json
    events/<repo-slug>/<event-id>/timeline.json
    embeddings/<repo-slug>/<event-id>/excerpt_embedding.json

WHY AN ABSTRACTION:
    - Testability: mock Storage in tests without touching AWS
    - Portability: swap S3 for local filesystem in dev mode
    - Single place to handle S3 errors, retries, encoding

USAGE:
    from shared.storage import S3Storage
    storage = S3Storage()
    storage.put_text("events/slug/evt-123/logs/full_logs.txt", log_content)
    content = storage.get_text("events/slug/evt-123/logs/excerpt.txt")

COMMUNICATION:
─────────────
Step 2 (worker) writes: logs, excerpt, artifacts.json, timeline.json
Step 3 (embeddings) writes: embedding JSON files
Step 10 (verifier) reads: artifacts.json to update verification status
"""

import json
from typing import Any, Dict, Optional, Protocol

import boto3
from botocore.exceptions import ClientError

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("shared.storage")


# ──────────────────────────────────────────────
# Storage Protocol (interface for mocking)
# ──────────────────────────────────────────────
class StorageProtocol(Protocol):
    """Interface that any storage backend must implement."""

    def put_text(self, key: str, content: str) -> None: ...
    def put_json(self, key: str, data: Any) -> None: ...
    def get_text(self, key: str) -> Optional[str]: ...
    def get_json(self, key: str) -> Optional[Any]: ...
    def exists(self, key: str) -> bool: ...


# ──────────────────────────────────────────────
# S3 Implementation
# ──────────────────────────────────────────────
class S3Storage:
    """
    Production storage backend using AWS S3.

    All keys are relative to the configured S3_DATA_BUCKET.
    Example key: "events/myuser-mlproject/evt-...-123/logs/full_logs.txt"
    """

    def __init__(self, bucket: Optional[str] = None):
        self._bucket = bucket or settings.S3_DATA_BUCKET
        self._client = boto3.client("s3", region_name=settings.AWS_REGION)

    def put_text(self, key: str, content: str) -> None:
        """Upload a plain text file to S3."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/plain",
            )
            logger.info("s3_put_text", key=key, size=len(content))
        except ClientError as e:
            logger.error("s3_put_text_failed", key=key, error=str(e))
            raise

    def put_json(self, key: str, data: Any) -> None:
        """Upload a JSON-serializable object to S3."""
        try:
            body = json.dumps(data, indent=2, default=str)
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info("s3_put_json", key=key, size=len(body))
        except ClientError as e:
            logger.error("s3_put_json_failed", key=key, error=str(e))
            raise

    def get_text(self, key: str) -> Optional[str]:
        """Download a text file from S3. Returns None if not found."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.warning("s3_key_not_found", key=key)
                return None
            logger.error("s3_get_text_failed", key=key, error=str(e))
            raise

    def get_json(self, key: str) -> Optional[Any]:
        """Download and parse a JSON file from S3. Returns None if not found."""
        text = self.get_text(key)
        if text is None:
            return None
        return json.loads(text)

    def exists(self, key: str) -> bool:
        """Check if a key exists in S3."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False


# ──────────────────────────────────────────────
# Local Filesystem Implementation (for dev/testing)
# ──────────────────────────────────────────────
class LocalStorage:
    """
    Development storage backend using local filesystem.
    Mirrors the S3 key structure under a local `data/` directory.
    """

    def __init__(self, base_dir: str = "data"):
        from pathlib import Path
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str):
        from pathlib import Path
        path = self._base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put_text(self, key: str, content: str) -> None:
        path = self._resolve(key)
        path.write_text(content, encoding="utf-8")
        logger.info("local_put_text", key=key, path=str(path))

    def put_json(self, key: str, data: Any) -> None:
        path = self._resolve(key)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("local_put_json", key=key, path=str(path))

    def get_text(self, key: str) -> Optional[str]:
        path = self._resolve(key)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def get_json(self, key: str) -> Optional[Any]:
        text = self.get_text(key)
        if text is None:
            return None
        return json.loads(text)

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()


# ──────────────────────────────────────────────
# Factory — picks storage backend based on ENVIRONMENT
# ──────────────────────────────────────────────
def get_storage() -> StorageProtocol:
    """
    Returns the appropriate storage backend.
    - development → LocalStorage (writes to ./data/)
    - production  → S3Storage
    """
    if settings.ENVIRONMENT == "development":
        logger.info("using_local_storage")
        return LocalStorage()
    else:
        logger.info("using_s3_storage", bucket=settings.S3_DATA_BUCKET)
        return S3Storage()
