"""
shared/notifier.py — Email & GitHub Comment Notifications

HOW IT WORKS:
─────────────
Sends notifications through two channels:
  1. Email (Gmail SMTP) — for team alerts
  2. GitHub Issue/PR Comment — for developer-facing updates

Email uses Gmail App Password (not regular password).
GitHub comments use the GitHub App token.

USAGE:
    from shared.notifier import Notifier
    notifier = Notifier()
    notifier.send_email(subject="CI Fix Applied", body="...")
    notifier.post_github_comment(repo="user/repo", pr_number=42, body="...")

COMMUNICATION:
─────────────
Step 2 (worker) calls notifier on:
  - Pipeline completion (success email)
  - Pipeline failure (error email)
  - Policy denial (notification to maintainers)
Step 8 (PR creator) calls notifier to:
  - Comment on the PR with fix details
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("shared.notifier")


class Notifier:
    """Sends email and GitHub comment notifications."""

    # ── Email ──
    def send_email(
        self,
        subject: str,
        body: str,
        recipients: Optional[List[str]] = None,
        html: bool = False,
    ) -> bool:
        """
        Send an email via Gmail SMTP.

        Args:
            subject: Email subject line
            body: Email body (plain text or HTML)
            recipients: List of email addresses. Defaults to NOTIFICATION_EMAILS.
            html: If True, send as HTML email

        Returns:
            True if sent successfully, False otherwise
        """
        recipients = recipients or settings.NOTIFICATION_EMAILS
        if not recipients:
            logger.warning("no_recipients", msg="No notification emails configured")
            return False

        if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
            logger.warning("email_not_configured", msg="Gmail credentials missing")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = settings.GMAIL_ADDRESS
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject

            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type))

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
                server.sendmail(settings.GMAIL_ADDRESS, recipients, msg.as_string())

            logger.info("email_sent", subject=subject, recipients=recipients)
            return True

        except Exception as e:
            logger.error("email_failed", subject=subject, error=str(e))
            return False

    # ── GitHub Comment ──
    def post_github_comment(
        self,
        repo_full_name: str,
        issue_number: int,
        body: str,
    ) -> bool:
        """
        Post a comment on a GitHub Issue or Pull Request.

        Uses the GitHub App token for authentication.

        Args:
            repo_full_name: e.g. "username/mlproject"
            issue_number: Issue or PR number
            body: Comment body (Markdown supported)

        Returns:
            True if posted successfully, False otherwise
        """
        try:
            from shared.github_auth import get_github_client

            g = get_github_client()
            repo = g.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            issue.create_comment(body)

            logger.info(
                "github_comment_posted",
                repo=repo_full_name,
                issue=issue_number,
            )
            return True

        except Exception as e:
            logger.error(
                "github_comment_failed",
                repo=repo_full_name,
                issue=issue_number,
                error=str(e),
            )
            return False

    # ── Convenience Methods ──
    def notify_pipeline_success(
        self,
        event_id: str,
        repo: str,
        pr_url: str,
    ) -> None:
        """Send success notification via all channels."""
        subject = f"✅ RepoMind: Auto-fix applied to {repo}"
        body = (
            f"RepoMind CI Auto-Fix Agent\n\n"
            f"Repository: {repo}\n"
            f"Event ID: {event_id}\n"
            f"Pull Request: {pr_url}\n\n"
            f"A fix has been automatically applied. Please review the PR."
        )
        self.send_email(subject=subject, body=body)

    def notify_pipeline_failure(
        self,
        event_id: str,
        repo: str,
        error: str,
    ) -> None:
        """Send failure notification via email."""
        subject = f"❌ RepoMind: Pipeline failed for {repo}"
        body = (
            f"RepoMind CI Auto-Fix Agent\n\n"
            f"Repository: {repo}\n"
            f"Event ID: {event_id}\n"
            f"Error: {error}\n\n"
            f"Manual investigation may be required."
        )
        self.send_email(subject=subject, body=body)

    def notify_policy_denied(
        self,
        event_id: str,
        repo: str,
        reason: str,
    ) -> None:
        """Send notification when policy denies auto-fix."""
        subject = f"🚫 RepoMind: Auto-fix denied for {repo}"
        body = (
            f"RepoMind CI Auto-Fix Agent\n\n"
            f"Repository: {repo}\n"
            f"Event ID: {event_id}\n"
            f"Policy Decision: DENIED\n"
            f"Reason: {reason}\n\n"
            f"Manual fix required."
        )
        self.send_email(subject=subject, body=body)
