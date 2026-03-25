"""
step2/excerpt.py — Log Excerpt Generator (Hybrid Strategy)

HOW IT WORKS:
─────────────
Extracts the RELEVANT error section from massive CI logs.

GitHub Actions logs can be 10,000+ lines. We need to find the needle
(the actual error) in the haystack (build output, download logs, etc).

TWO-PHASE STRATEGY (from architecture spec Section 8):

Phase 1 — Heuristic (always runs):
    1. Find lines containing error keywords (ERROR, FAILED, Exception, etc.)
    2. Extract N context lines before/after each error line
    3. Extract the last 200 lines (errors often appear at the end)
    4. Clean ANSI escape codes
    5. Deduplicate and combine

Phase 2 — LLM Refinement (optional, if excerpt is unclear):
    If the heuristic excerpt is too long, too short, or too noisy,
    the worker will ask the LLM to produce a summary.
    This is handled in step5/triage.py, NOT here.

OUTPUT:
    A clean, focused excerpt of 50-300 lines containing the actual error.

COMMUNICATION:
─────────────
Worker calls:
    excerpt = ExcerptGenerator().generate(sanitized_logs)
The excerpt is stored in S3: events/<slug>/<event-id>/logs/excerpt.txt
Then passed to Step 5 (triage) for AI classification.
"""

import re
from typing import List, Set

from shared.logger import get_logger

logger = get_logger("step2.excerpt")

# ──────────────────────────────────────────────
# Error keywords to search for in logs
# ──────────────────────────────────────────────
ERROR_KEYWORDS = [
    "error",
    "Error",
    "ERROR",
    "failed",
    "Failed",
    "FAILED",
    "failure",
    "Failure",
    "exception",
    "Exception",
    "EXCEPTION",
    "traceback",
    "Traceback",
    "fatal",
    "Fatal",
    "FATAL",
    "panic",
    "cannot find",
    "not found",
    "undefined",
    "ModuleNotFoundError",
    "ImportError",
    "SyntaxError",
    "TypeError",
    "ValueError",
    "KeyError",
    "AttributeError",
    "FileNotFoundError",
    "PermissionError",
    "ConnectionError",
    "TimeoutError",
    "AssertionError",
    "npm ERR!",
    "ENOENT",
    "EACCES",
    "exit code 1",
    "exit code 2",
    "Process completed with exit code",
    "build failed",
    "test failed",
    "compilation error",
    "compile error",
]

# ANSI escape code pattern (for cleaning colored output)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# GitHub Actions timestamp prefix pattern
GH_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s*")


class ExcerptGenerator:
    """
    Generates a focused error excerpt from CI logs.

    Config:
        context_lines: Number of lines before/after each error line (default 5)
        tail_lines:    Number of lines from the end of logs (default 200)
        max_excerpt_lines: Maximum total excerpt length (default 300)
    """

    def __init__(
        self,
        context_lines: int = 5,
        tail_lines: int = 200,
        max_excerpt_lines: int = 300,
    ):
        self.context_lines = context_lines
        self.tail_lines = tail_lines
        self.max_excerpt_lines = max_excerpt_lines

    def generate(self, raw_logs: str) -> str:
        """
        Generate an excerpt from raw CI logs.

        Args:
            raw_logs: Full CI log text (potentially 10,000+ lines)

        Returns:
            Focused excerpt containing the error context (50-300 lines)
        """
        # Clean ANSI codes and GitHub timestamps
        lines = self._clean_lines(raw_logs)
        total_lines = len(lines)

        logger.info("excerpt_generating", total_lines=total_lines)

        # Phase 1: Find error lines + context
        error_lines = self._find_error_lines(lines)
        
        # Phase 2: Get tail lines (errors often at the end)
        tail_start = max(0, total_lines - self.tail_lines)
        tail_indices = set(range(tail_start, total_lines))

        # Combine all relevant line indices
        relevant_indices = error_lines | tail_indices

        # Extract and deduplicate
        if not relevant_indices:
            # Fallback: just take the last N lines
            excerpt_lines = lines[-self.tail_lines:]
        else:
            sorted_indices = sorted(relevant_indices)
            excerpt_lines = self._build_excerpt(lines, sorted_indices)

        # Trim to max length
        if len(excerpt_lines) > self.max_excerpt_lines:
            excerpt_lines = excerpt_lines[-self.max_excerpt_lines:]

        excerpt = "\n".join(excerpt_lines)
        logger.info(
            "excerpt_generated",
            original_lines=total_lines,
            excerpt_lines=len(excerpt_lines),
        )
        return excerpt

    def _clean_lines(self, text: str) -> List[str]:
        """Remove ANSI codes and normalize whitespace."""
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            line = ANSI_ESCAPE.sub("", line)
            line = GH_TIMESTAMP.sub("", line)
            line = line.rstrip()
            cleaned.append(line)
        return cleaned

    def _find_error_lines(self, lines: List[str]) -> Set[int]:
        """
        Find all lines containing error keywords,
        plus context_lines before and after each match.
        """
        error_indices: Set[int] = set()
        total = len(lines)

        for i, line in enumerate(lines):
            lower = line.lower()
            if any(kw.lower() in lower for kw in ERROR_KEYWORDS):
                # Add the error line plus context
                start = max(0, i - self.context_lines)
                end = min(total, i + self.context_lines + 1)
                error_indices.update(range(start, end))

        return error_indices

    def _build_excerpt(self, lines: List[str], indices: List[int]) -> List[str]:
        """
        Build excerpt from selected line indices.
        Insert '...' markers where lines are skipped.
        """
        result = []
        prev_idx = -2

        for idx in indices:
            if idx > prev_idx + 1:
                result.append("... (lines skipped) ...")
            if 0 <= idx < len(lines):
                result.append(lines[idx])
            prev_idx = idx

        return result
