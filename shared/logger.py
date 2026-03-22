"""
shared/logger.py — Structured Logging Setup

HOW IT WORKS:
─────────────
Uses `structlog` to produce JSON-formatted log lines.
Every log entry includes: timestamp, log_level, event, and any bound context.

WHY STRUCTLOG:
    - Machine-parseable (JSON) for CloudWatch / Datadog / Splunk
    - Human-readable in dev mode (colored console output)
    - Bind context once (event_id, repo) and it appears in all subsequent logs

USAGE:
    from shared.logger import get_logger
    logger = get_logger("step1.webhook")
    logger = logger.bind(event_id="evt-...", repo="user/repo")
    logger.info("webhook_received", run_id=12345)

OUTPUT:
    {"timestamp": "2026-...", "level": "info", "logger": "step1.webhook",
     "event": "webhook_received", "event_id": "evt-...", "run_id": 12345}

COMMUNICATION:
─────────────
Every module imports get_logger() and binds context.
The bound context (event_id, repo) flows through the entire pipeline.
"""

import sys
import logging
import structlog
from shared.config import settings


def _get_log_level(level_name: str) -> int:
    """Convert a log level name to its numeric value using stdlib logging."""
    return getattr(logging, level_name.upper(), logging.INFO)


def _configure_structlog():
    """
    Configure structlog once at import time.
    - Development: colored, pretty-printed console output
    - Production: JSON lines for CloudWatch
    """
    is_dev = settings.ENVIRONMENT == "development"

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_dev:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            _get_log_level(settings.LOG_LEVEL)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


# Configure once on import
_configure_structlog()


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a named logger.

    Args:
        name: Module name, e.g. "step1.webhook", "step2.worker"

    Returns:
        A structlog BoundLogger you can .bind() and .info()/.error() on.
    """
    return structlog.get_logger(logger_name=name)
