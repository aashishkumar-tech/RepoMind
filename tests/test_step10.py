"""
tests/test_step10.py — Unit tests for Verifier + Rollback

Tests:
    - VerificationResult / RollbackResult models
    - Verifier: CI passed, CI failed, not a fix branch, unexpected conclusion
    - Verifier: rollback triggering
    - RollbackClient: anti-flapping, rate limiting
    - RollbackClient: revert PR creation (mocked)
"""

import time
from unittest.mock import patch, MagicMock

from step10.models import VerificationResult, RollbackResult


# ──────────────────────────────────────────────
# Model Tests
# ──────────────────────────────────────────────
class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_default_values(self):
        result = VerificationResult(status="passed")
        assert result.status == "passed"
        assert result.ci_conclusion == ""
        assert result.fix_branch == ""
        assert result.rollback_triggered is False
        assert result.timestamp != ""

    def test_to_dict(self):
        result = VerificationResult(
            status="passed",
            ci_conclusion="success",
            fix_branch="fix/import-abc123",
            repo="user/repo",
            workflow_run_id=12345,
        )
        d = result.to_dict()
        assert d["status"] == "passed"
        assert d["ci_conclusion"] == "success"
        assert d["fix_branch"] == "fix/import-abc123"
        assert d["repo"] == "user/repo"
        assert d["workflow_run_id"] == 12345
        assert "timestamp" in d

    def test_failed_with_rollback(self):
        result = VerificationResult(
            status="failed",
            rollback_triggered=True,
            rollback_pr_url="https://github.com/user/repo/pull/42",
        )
        d = result.to_dict()
        assert d["rollback_triggered"] is True
        assert d["rollback_pr_url"] == "https://github.com/user/repo/pull/42"


class TestRollbackResult:
    """Tests for RollbackResult dataclass."""

    def test_default_values(self):
        result = RollbackResult(status="reverted")
        assert result.status == "reverted"
        assert result.revert_pr_url == ""
        assert result.original_pr_number == 0
        assert result.timestamp != ""

    def test_to_dict(self):
        result = RollbackResult(
            status="reverted",
            revert_pr_url="https://github.com/user/repo/pull/99",
            reason="CI failed",
            original_pr_number=42,
            message="Revert PR created",
        )
        d = result.to_dict()
        assert d["status"] == "reverted"
        assert d["revert_pr_url"] == "https://github.com/user/repo/pull/99"
        assert d["reason"] == "CI failed"
        assert d["original_pr_number"] == 42

    def test_skipped_result(self):
        result = RollbackResult(
            status="skipped",
            reason="Already rolled back",
        )
        assert result.status == "skipped"
        assert result.reason == "Already rolled back"


# ──────────────────────────────────────────────
# Verifier Tests
# ──────────────────────────────────────────────
class TestVerifier:
    """Tests for the Verifier engine."""

    def test_verify_ci_passed(self):
        """When CI passes on fix branch, should return status=passed."""
        from step10.verifier import Verifier
        verifier = Verifier()

        with patch.object(verifier, "_record_metrics"):
            result = verifier.verify(
                repo="user/repo",
                workflow_run_id=12345,
                branch="fix/import-abc12345",
                conclusion="success",
            )

        assert result.status == "passed"
        assert result.ci_conclusion == "success"
        assert result.rollback_triggered is False
        assert "Fix verified" in result.message

    def test_verify_ci_failed_triggers_rollback(self):
        """When CI fails on fix branch, should trigger rollback."""
        from step10.verifier import Verifier
        verifier = Verifier()

        mock_rollback_result = {
            "status": "reverted",
            "revert_pr_url": "https://github.com/user/repo/pull/99",
        }

        with patch.object(verifier, "_record_metrics"):
            with patch.object(verifier, "_trigger_rollback", return_value=mock_rollback_result):
                result = verifier.verify(
                    repo="user/repo",
                    workflow_run_id=12345,
                    branch="fix/import-abc12345",
                    conclusion="failure",
                )

        assert result.status == "failed"
        assert result.rollback_triggered is True
        assert result.rollback_pr_url == "https://github.com/user/repo/pull/99"

    def test_verify_not_fix_branch(self):
        """Non-fix branches should return status=error."""
        from step10.verifier import Verifier
        verifier = Verifier()

        result = verifier.verify(
            repo="user/repo",
            workflow_run_id=12345,
            branch="main",
            conclusion="success",
        )

        assert result.status == "error"
        assert "Not a fix branch" in result.message

    def test_verify_cancelled_conclusion(self):
        """Cancelled workflows should return status=error."""
        from step10.verifier import Verifier
        verifier = Verifier()

        with patch.object(verifier, "_record_metrics"):
            result = verifier.verify(
                repo="user/repo",
                workflow_run_id=12345,
                branch="fix/import-abc12345",
                conclusion="cancelled",
            )

        assert result.status == "error"
        assert "Unexpected conclusion" in result.message

    def test_verify_rollback_blocked_by_killswitch(self):
        """When kill switch is ON, rollback should not be triggered."""
        from step10.verifier import Verifier
        verifier = Verifier()

        with patch.object(verifier, "_record_metrics"):
            with patch("step10.verifier.Verifier._trigger_rollback", return_value=None):
                result = verifier.verify(
                    repo="user/repo",
                    workflow_run_id=12345,
                    branch="fix/import-abc12345",
                    conclusion="failure",
                )

        assert result.status == "failed"
        assert result.rollback_triggered is False

    def test_extract_event_id_from_branch(self):
        """Should extract short event ID from fix branch name."""
        from step10.verifier import Verifier
        verifier = Verifier()

        assert verifier._extract_event_id_from_branch("fix/missing_import-abc12345") == "abc12345"
        assert verifier._extract_event_id_from_branch("fix/test_failure-xyz99999") == "xyz99999"

    def test_extract_event_id_single_part(self):
        """Branch with no dash separator should return full suffix."""
        from step10.verifier import Verifier
        verifier = Verifier()

        result = verifier._extract_event_id_from_branch("fix/simplefix")
        assert result == "simplefix"


# ──────────────────────────────────────────────
# Rollback Client Tests
# ──────────────────────────────────────────────
class TestRollbackClient:
    """Tests for the RollbackClient."""

    def test_anti_flapping_skips_duplicate(self):
        """Should skip rollback if already rolled back."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        with patch.object(client, "_already_rolled_back", return_value=True):
            result = client.rollback(
                repo="user/repo",
                fix_branch="fix/import-abc12345",
                original_event_id="evt-abc123",
                reason="CI failed",
            )

        assert result.status == "skipped"
        assert "anti-flapping" in result.reason.lower()

    def test_rate_limit_skips(self):
        """Should skip rollback when rate limit exceeded."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        with patch.object(client, "_already_rolled_back", return_value=False):
            with patch.object(client, "_rate_limit_exceeded", return_value=True):
                result = client.rollback(
                    repo="user/repo",
                    fix_branch="fix/import-abc12345",
                    original_event_id="evt-abc123",
                    reason="CI failed",
                )

        assert result.status == "skipped"
        assert "rate limit" in result.reason.lower()

    def test_rollback_error_handling(self):
        """Should return error result on exception."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        with patch.object(client, "_already_rolled_back", return_value=False):
            with patch.object(client, "_rate_limit_exceeded", return_value=False):
                with patch.object(client, "_create_revert_pr", side_effect=Exception("GitHub API error")):
                    result = client.rollback(
                        repo="user/repo",
                        fix_branch="fix/import-abc12345",
                        original_event_id="evt-abc123",
                        reason="CI failed",
                    )

        assert result.status == "error"
        assert "GitHub API error" in result.message

    def test_rate_limit_counter_reset_after_hour(self):
        """Rate limit counter should reset after 1 hour."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        # Mock storage with an expired window
        mock_data = {
            "count": 10,
            "window_start": time.time() - 7200,  # 2 hours ago
        }

        with patch.object(client.storage, "get_json", return_value=mock_data):
            with patch.object(client.storage, "put_json"):
                result = client._rate_limit_exceeded("user/repo")
                assert result is False  # Window expired, should reset

    def test_rate_limit_within_window(self):
        """Rate limit should trigger when count exceeds max in window."""
        from step10.rollback import RollbackClient
        client = RollbackClient()
        client.max_rollbacks_per_hour = 3

        mock_data = {
            "count": 3,
            "window_start": time.time() - 100,  # 100 seconds ago (within window)
        }

        with patch.object(client.storage, "get_json", return_value=mock_data):
            result = client._rate_limit_exceeded("user/repo")
            assert result is True

    def test_rate_limit_first_rollback(self):
        """First rollback should not be rate limited."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        with patch.object(client.storage, "get_json", return_value=None):
            with patch.object(client.storage, "put_json"):
                result = client._rate_limit_exceeded("user/repo")
                assert result is False

    def test_revert_pr_body_content(self):
        """Revert PR body should contain all relevant context."""
        from step10.rollback import RollbackClient
        client = RollbackClient()

        body = client._build_revert_pr_body(
            fix_branch="fix/import-abc12345",
            fix_pr_number=42,
            fix_pr_url="https://github.com/user/repo/pull/42",
            reason="CI failed on fix branch",
            original_event_id="evt-abc123",
        )

        assert "RepoMind Revert" in body
        assert "#42" in body
        assert "fix/import-abc12345" in body
        assert "CI failed" in body
        assert "evt-abc123" in body
        assert "Action Required" in body
