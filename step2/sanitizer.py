"""
step2/sanitizer.py — Log Sanitizer

HOW IT WORKS:
─────────────
Removes sensitive data from CI logs before storing or processing.

CI logs can accidentally contain:
    - API keys and tokens
    - AWS credentials
    - Database passwords
    - Email addresses
    - Private IPs / hostnames

This module scans the log text with regex patterns and replaces
matches with [REDACTED].

WHY:
    - Security: never store secrets in S3 or send to LLM
    - Compliance: avoid leaking PII
    - Safety: even if someone browses the S3 bucket, no secrets exposed

PATTERNS:
    Configurable. Default patterns cover common secrets.
    Add custom patterns via the `extra_patterns` parameter.

COMMUNICATION:
─────────────
Called by worker.py after fetching logs, before excerpt generation:
    raw_logs → Sanitizer.sanitize(raw_logs) → clean_logs → ExcerptGenerator
"""

import re
from typing import List, Tuple

from shared.logger import get_logger

logger = get_logger("step2.sanitizer")

# ──────────────────────────────────────────────
# Default sanitization patterns
# ──────────────────────────────────────────────
# Each tuple: (pattern_name, regex_pattern)
DEFAULT_PATTERNS: List[Tuple[str, str]] = [
    # AWS keys
    ("aws_access_key", r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}"),
    ("aws_secret_key", r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*\S+"),
    
    # GitHub tokens
    ("github_token", r"gh[pousr]_[A-Za-z0-9_]{36,255}"),
    ("github_classic_token", r"ghp_[A-Za-z0-9]{36}"),
    
    # Generic API keys / tokens / secrets
    ("generic_api_key", r"(?i)(?:api[_\-]?key|apikey|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[A-Za-z0-9/+=_\-]{8,}['\"]?"),
    
    # Bearer tokens
    ("bearer_token", r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    
    # Email addresses
    ("email", r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    
    # Private IPs
    ("private_ip", r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"),
    
    # Connection strings
    ("connection_string", r"(?i)(?:mongodb|mysql|postgres|redis|amqp):\/\/[^\s]+"),
    
    # JWT tokens
    ("jwt", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
]


class Sanitizer:
    """
    Scans text for sensitive patterns and replaces with [REDACTED].

    Tracks how many redactions were made per pattern (for monitoring).
    """

    def __init__(self, extra_patterns: List[Tuple[str, str]] = None):
        self._patterns = DEFAULT_PATTERNS.copy()
        if extra_patterns:
            self._patterns.extend(extra_patterns)
        # Pre-compile for performance
        self._compiled = [
            (name, re.compile(pattern)) for name, pattern in self._patterns
        ]

    def sanitize(self, text: str) -> str:
        """
        Remove all sensitive data from the text.

        Args:
            text: Raw log text

        Returns:
            Sanitized text with secrets replaced by [REDACTED]
        """
        total_redactions = 0
        result = text

        for name, pattern in self._compiled:
            matches = pattern.findall(result)
            if matches:
                result = pattern.sub(f"[REDACTED:{name}]", result)
                total_redactions += len(matches)

        if total_redactions > 0:
            logger.info("logs_sanitized", redactions=total_redactions)

        return result
