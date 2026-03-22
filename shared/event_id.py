"""
shared/event_id.py — Event ID Generator

HOW IT WORKS:
─────────────
Generates a globally unique, sortable, human-readable event ID.

FORMAT:
    evt-<repo-slug>-<workflow-run-id>-<timestamp>

EXAMPLE:
    evt-username-mlproject-123456789-20260213T154400Z

WHY THIS FORMAT:
    - Globally unique  (repo + run ID + timestamp = no collisions)
    - Lexicographically sortable  (ISO timestamp at the end)
    - Human-readable  (you can read the repo + run at a glance)
    - Debug-friendly  (paste it in logs, S3 browser, grep)

COMMUNICATION:
─────────────
Step 1 (webhook) calls: generate_event_id(repo, run_id)
Passes the event_id into the SQS message.
Step 2 (worker) receives it and uses it as the S3 folder key.
Every artifact is stored under: events/<repo-slug>/<event-id>/
"""

import re
from datetime import datetime, timezone


def _slugify(repo_full_name: str) -> str:
    """
    Convert 'owner/repo-name' → 'owner-repo-name'

    Replaces non-alphanumeric chars with hyphens.
    Lowercased for consistency.
    """
    return re.sub(r"[^a-z0-9]+", "-", repo_full_name.lower()).strip("-")


def generate_event_id(repo_full_name: str, workflow_run_id: int) -> str:
    """
    Build the canonical event ID.

    Args:
        repo_full_name: e.g. "myuser/mlproject"
        workflow_run_id: e.g. 123456789

    Returns:
        e.g. "evt-myuser-mlproject-123456789-20260213T154400Z"
    """
    slug = _slugify(repo_full_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"evt-{slug}-{workflow_run_id}-{ts}"


def extract_repo_slug(event_id: str) -> str:
    """
    Reverse-extract the repo slug from an event ID.

    'evt-myuser-mlproject-123456789-20260213T154400Z'
      → 'myuser-mlproject'

    Used to build S3 paths: events/<slug>/<event_id>/
    """
    # Remove 'evt-' prefix, then remove the last two segments (run_id + timestamp)
    without_prefix = event_id[4:]  # drop 'evt-'
    parts = without_prefix.rsplit("-", 2)
    # parts = ['myuser-mlproject', '123456789', '20260213T154400Z']
    return parts[0] if len(parts) >= 3 else without_prefix
