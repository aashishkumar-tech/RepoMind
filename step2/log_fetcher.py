"""
step2/log_fetcher.py — GitHub Actions Log Downloader

HOW IT WORKS:
─────────────
Downloads the CI/CD logs from a failed GitHub Actions workflow run.

Flow:
    1. Authenticate with GitHub App token
    2. Call GitHub API: GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs
    3. GitHub returns a ZIP file containing all job logs
    4. Extract and concatenate all log files into one string
    5. Return the raw log text

RETRY STRATEGY:
    Uses tenacity for exponential backoff:
    - Wait: 1s → 2s → 4s → 8s
    - Max retries: 3
    - Retry on: HTTP 5xx, connection errors, rate limits (403)

WHY DOWNLOAD ALL LOGS:
    We need the full log to find the error. GitHub Actions logs are
    split across multiple jobs/steps. We merge them all, then the
    excerpt generator (step2/excerpt.py) extracts the relevant parts.

COMMUNICATION:
─────────────
Worker (step2/worker.py) calls:
    logs = LogFetcher().fetch_logs(repo, run_id)
Then passes `logs` to:
    ExcerptGenerator to extract the relevant error section
"""

import io
import zipfile
from typing import Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from shared.github_auth import get_installation_token
from shared.logger import get_logger

logger = get_logger("step2.log_fetcher")


class LogFetcher:
    """Downloads GitHub Actions workflow run logs."""

    GITHUB_API_BASE = "https://api.github.com"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
        reraise=True,
    )
    def fetch_logs(self, repo_full_name: str, run_id: int) -> Optional[str]:
        """
        Download and extract logs from a GitHub Actions workflow run.

        Args:
            repo_full_name: e.g. "username/mlproject"
            run_id: GitHub workflow run ID

        Returns:
            Concatenated log text from all jobs, or None on failure.

        Raises:
            httpx.HTTPStatusError: On non-retryable HTTP errors (4xx)
        """
        token = get_installation_token()
        url = f"{self.GITHUB_API_BASE}/repos/{repo_full_name}/actions/runs/{run_id}/logs"

        logger.info("fetching_logs", repo=repo_full_name, run_id=run_id)

        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                follow_redirects=True,
            )
            response.raise_for_status()

        # GitHub returns a ZIP file
        log_text = self._extract_zip_logs(response.content)
        logger.info(
            "logs_fetched",
            repo=repo_full_name,
            run_id=run_id,
            log_size=len(log_text),
        )
        return log_text

    def _extract_zip_logs(self, zip_bytes: bytes) -> str:
        """
        Extract all text files from the ZIP and concatenate them.

        GitHub Actions log ZIPs contain one .txt file per job step.
        We merge them with headers so we can identify which step failed.
        """
        all_logs = []

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith("/"):
                    continue  # Skip directories
                try:
                    content = zf.read(name).decode("utf-8", errors="replace")
                    all_logs.append(f"=== {name} ===\n{content}\n")
                except Exception as e:
                    all_logs.append(f"=== {name} === [ERROR READING: {e}]\n")

        return "\n".join(all_logs)
