"""
shared/github_auth.py — GitHub App Authentication

HOW IT WORKS:
─────────────
GitHub Apps authenticate using JWT (JSON Web Tokens):
  1. Read the .pem private key from disk
  2. Build a JWT signed with the private key (RS256)
  3. Exchange the JWT for an Installation Access Token via GitHub API
  4. Use the token for all GitHub API calls (expires in 1 hour)

This module handles the full flow and caches the token until it expires.

WHY GITHUB APP (not PAT):
    - Fine-grained permissions per repo
    - No personal account dependency
    - Tokens auto-expire (better security)
    - Can be installed on specific repos only

USAGE:
    from shared.github_auth import get_github_client
    g = get_github_client()
    repo = g.get_repo("username/mlproject")
    # Now use PyGithub as normal

COMMUNICATION:
─────────────
Step 2 (worker) calls get_github_client() to:
  - Download workflow run logs
  - Read repo files
Step 8 (PR creator) calls it to:
  - Create branches, commits, and pull requests
"""

import time
import jwt
from pathlib import Path
from typing import Optional

from github import Github, GithubIntegration

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("shared.github_auth")

# ──────────────────────────────────────────────
# Module-level token cache
# ──────────────────────────────────────────────
_cached_token: Optional[str] = None
_token_expires_at: float = 0


def _read_private_key() -> str:
    """
    Read the GitHub App private key from the .pem file.
    Path comes from settings.GITHUB_PRIVATE_KEY_PATH.
    """
    key_path = Path(settings.GITHUB_PRIVATE_KEY_PATH)
    if not key_path.is_absolute():
        # Resolve relative to project root
        key_path = Path(__file__).resolve().parent.parent / key_path
    
    if not key_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at: {key_path}\n"
            f"Download it from GitHub App settings → Private keys"
        )
    
    return key_path.read_text(encoding="utf-8")


def _generate_jwt() -> str:
    """
    Generate a JWT for GitHub App authentication.

    The JWT is signed with the App's private key (RS256).
    Valid for 10 minutes (GitHub's maximum).

    Payload:
        iss: GitHub App ID
        iat: issued at (now - 60s for clock drift)
        exp: expires at (now + 10 minutes)
    """
    private_key = _read_private_key()
    now = int(time.time())

    payload = {
        "iss": settings.GITHUB_APP_ID,
        "iat": now - 60,  # 60 seconds in the past for clock drift
        "exp": now + (10 * 60),  # 10 minutes
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    logger.info("jwt_generated", app_id=settings.GITHUB_APP_ID)
    return token


def get_installation_token() -> str:
    """
    Get an Installation Access Token for the GitHub App.

    Flow:
        1. Generate JWT
        2. Call GitHub API: POST /app/installations/{id}/access_tokens
        3. Cache the token until it expires

    The token lasts 1 hour. We refresh when < 5 min remaining.
    """
    global _cached_token, _token_expires_at

    # Return cached token if still valid (> 5 minutes left)
    if _cached_token and time.time() < (_token_expires_at - 300):
        return _cached_token

    integration = GithubIntegration(
        integration_id=int(settings.GITHUB_APP_ID),
        private_key=_read_private_key(),
    )

    installation_id = int(settings.GITHUB_INSTALLATION_ID)
    token_obj = integration.get_access_token(installation_id)

    _cached_token = token_obj.token
    # GitHub tokens expire in 1 hour
    _token_expires_at = time.time() + 3600

    logger.info(
        "installation_token_acquired",
        installation_id=installation_id,
        expires_in="~1 hour",
    )
    return _cached_token


def get_github_client() -> Github:
    """
    Get an authenticated PyGithub client.

    Returns a Github instance ready to make API calls
    with the Installation Access Token.
    """
    token = get_installation_token()
    return Github(token)
