"""
shared/config.py — Centralized Configuration Loader

HOW IT WORKS:
─────────────
1. Loads .env file using python-dotenv
2. Reads each variable with os.getenv() + sensible defaults
3. Validates required secrets exist at startup (fail-fast)
4. Exposes a single `settings` object the entire app imports

COMMUNICATION:
─────────────
Every module does: `from shared.config import settings`
Then uses: `settings.GITHUB_APP_ID`, `settings.GROQ_API_KEY`, etc.

This is the SINGLE SOURCE OF TRUTH for all configuration.
No module reads os.environ directly — always go through settings.
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv


# ──────────────────────────────────────────────
# Load .env from project root
# ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_env_path = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_env_path)


@dataclass
class Settings:
    """
    Immutable application settings loaded from environment variables.

    Each field maps to an env var. Required fields raise on missing.
    Optional fields have defaults.
    """

    # ── AWS ──
    AWS_REGION: str = ""
    AWS_ACCOUNT_ID: str = ""
    S3_SAM_BUCKET: str = ""
    S3_DATA_BUCKET: str = ""

    # ── GitHub App ──
    GITHUB_APP_ID: str = ""
    GITHUB_INSTALLATION_ID: str = ""
    GITHUB_PRIVATE_KEY_PATH: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # ── Groq LLM ──
    GROQ_API_KEY: str = ""

    # ── OpenAI Embeddings ──
    OPENAI_API_KEY: str = ""

    # ── Email ──
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""
    NOTIFICATION_EMAILS: List[str] = field(default_factory=list)

    # ── Qdrant ──
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ── Target Repo ──
    TARGET_REPO: str = ""

    # ── Observability (Step 11) ──
    PUSHGATEWAY_URL: str = ""
    METRICS_ENABLED: str = "false"
    KILL_SWITCH_PARAM: str = "/repomind/kill_switch"

    # ── Verifier (Step 10) ──
    VERIFICATION_ENABLED: str = "true"
    MAX_ROLLBACKS_PER_HOUR: str = "3"

    # ── App ──
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"

    @classmethod
    def from_env(cls) -> "Settings":
        """
        Factory method: reads every field from os.environ.
        Splits comma-separated NOTIFICATION_EMAILS into a list.
        """
        notification_emails_raw = os.getenv("NOTIFICATION_EMAILS", "")
        notification_emails = [
            e.strip() for e in notification_emails_raw.split(",") if e.strip()
        ]

        return cls(
            AWS_REGION=os.getenv("AWS_REGION", "ap-south-1"),
            AWS_ACCOUNT_ID=os.getenv("AWS_ACCOUNT_ID", ""),
            S3_SAM_BUCKET=os.getenv("S3_SAM_BUCKET", "repomind-sam-deployments"),
            S3_DATA_BUCKET=os.getenv("S3_DATA_BUCKET", "repomind-data"),
            GITHUB_APP_ID=os.getenv("GITHUB_APP_ID", ""),
            GITHUB_INSTALLATION_ID=os.getenv("GITHUB_INSTALLATION_ID", ""),
            GITHUB_PRIVATE_KEY_PATH=os.getenv("GITHUB_PRIVATE_KEY_PATH", "private-key.pem"),
            GITHUB_WEBHOOK_SECRET=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
            GROQ_API_KEY=os.getenv("GROQ_API_KEY", ""),
            OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
            GMAIL_ADDRESS=os.getenv("GMAIL_ADDRESS", ""),
            GMAIL_APP_PASSWORD=os.getenv("GMAIL_APP_PASSWORD", ""),
            NOTIFICATION_EMAILS=notification_emails,
            QDRANT_HOST=os.getenv("QDRANT_HOST", "localhost"),
            QDRANT_PORT=int(os.getenv("QDRANT_PORT", "6333")),
            TARGET_REPO=os.getenv("TARGET_REPO", ""),
            PUSHGATEWAY_URL=os.getenv("PUSHGATEWAY_URL", ""),
            METRICS_ENABLED=os.getenv("METRICS_ENABLED", "false"),
            KILL_SWITCH_PARAM=os.getenv("KILL_SWITCH_PARAM", "/repomind/kill_switch"),
            VERIFICATION_ENABLED=os.getenv("VERIFICATION_ENABLED", "true"),
            MAX_ROLLBACKS_PER_HOUR=os.getenv("MAX_ROLLBACKS_PER_HOUR", "3"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
            ENVIRONMENT=os.getenv("ENVIRONMENT", "development"),
        )

    def validate_required(self, keys: List[str]) -> None:
        """
        Fail fast if any required key is empty.
        Called at service startup to catch misconfig early.

        Usage:
            settings.validate_required(["GITHUB_APP_ID", "GITHUB_WEBHOOK_SECRET"])
        """
        missing = [k for k in keys if not getattr(self, k, "")]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )


# ──────────────────────────────────────────────
# Singleton — import this everywhere
# ──────────────────────────────────────────────
settings = Settings.from_env()
