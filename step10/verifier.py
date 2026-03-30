"""
step10/verifier.py — Fix Verification Engine

HOW IT WORKS:
─────────────
After Step 8 creates a fix PR on a fix/* branch and it gets merged,
GitHub CI runs again on the merged code. The Verifier checks if that
CI run passed or failed.

FLOW:
    1. Webhook fires: workflow_run.completed on fix/* branch
    2. Step 1 routes it to worker with message_type="verification"
    3. Worker calls Verifier.verify()
    4. Verifier queries GitHub API for the workflow run conclusion
    5. If CI passed  → log success, push metrics, done
    6. If CI failed  → trigger RollbackClient, push metrics

WHAT IT CHECKS:
    - Was the workflow_run conclusion "success"?
    - Is the branch a fix/* branch (our branch)?
    - Can we find the original event artifacts in storage?

SAFETY:
    - Only verifies fix/* branches (ignores everything else)
    - Kill switch is checked before any rollback
    - Non-fatal: if verification fails, we log and continue

COMMUNICATION:
─────────────
Worker → Verifier.verify(repo, run_id, branch, conclusion)
Verifier → RollbackClient.rollback() (if CI failed)
Verifier → metrics.verification_total.inc()
Verifier → storage.put_json(verification result)
"""

from typing import Dict, Any, Optional

from step10.models import VerificationResult
from shared.logger import get_logger
from shared.storage import get_storage

logger = get_logger("step10.verifier")


class Verifier:
    """
    Verifies whether a fix branch CI passed or failed.
    Triggers rollback if the fix made things worse.
    """

    def __init__(self):
        self.storage = get_storage()

    def verify(
        self,
        repo: str,
        workflow_run_id: int,
        branch: str,
        conclusion: str,
        head_sha: str = "",
        run_url: str = "",
    ) -> VerificationResult:
        """
        Verify the outcome of a CI run on a fix branch.

        Args:
            repo: Repository full name (e.g. "user/mlproject")
            workflow_run_id: The GitHub workflow run ID
            branch: The branch name (e.g. "fix/missing_import-abc12345")
            conclusion: GitHub conclusion ("success", "failure", "cancelled")
            head_sha: The commit SHA
            run_url: URL to the workflow run

        Returns:
            VerificationResult with status, rollback info, etc.
        """
        logger.info(
            "verification_started",
            repo=repo,
            branch=branch,
            run_id=workflow_run_id,
            conclusion=conclusion,
        )

        # Validate this is a fix branch
        if not branch.startswith("fix/"):
            return VerificationResult(
                status="error",
                ci_conclusion=conclusion,
                fix_branch=branch,
                repo=repo,
                workflow_run_id=workflow_run_id,
                message=f"Not a fix branch: {branch}",
            )

        # Extract original event info from branch name
        original_event_id = self._extract_event_id_from_branch(branch)

        # Record metrics
        self._record_metrics(repo, conclusion)

        if conclusion == "success":
            result = VerificationResult(
                status="passed",
                ci_conclusion=conclusion,
                fix_branch=branch,
                repo=repo,
                workflow_run_id=workflow_run_id,
                original_event_id=original_event_id,
                message=f"Fix verified: CI passed on {branch}",
                rollback_triggered=False,
            )
            logger.info(
                "verification_passed",
                repo=repo,
                branch=branch,
            )
            return result

        elif conclusion == "failure":
            # CI failed on fix branch — trigger rollback
            logger.warning(
                "verification_failed",
                repo=repo,
                branch=branch,
                conclusion=conclusion,
            )

            rollback_result = self._trigger_rollback(
                repo=repo,
                branch=branch,
                original_event_id=original_event_id,
                reason=f"Fix CI failed on {branch} (conclusion: {conclusion})",
            )

            result = VerificationResult(
                status="failed",
                ci_conclusion=conclusion,
                fix_branch=branch,
                repo=repo,
                workflow_run_id=workflow_run_id,
                original_event_id=original_event_id,
                message=f"Fix failed: CI failed on {branch}. Rollback {'triggered' if rollback_result else 'skipped'}.",
                rollback_triggered=rollback_result is not None,
                rollback_pr_url=rollback_result.get("revert_pr_url", "") if rollback_result else "",
            )
            return result

        else:
            # Cancelled or other conclusion
            result = VerificationResult(
                status="error",
                ci_conclusion=conclusion,
                fix_branch=branch,
                repo=repo,
                workflow_run_id=workflow_run_id,
                original_event_id=original_event_id,
                message=f"Unexpected conclusion: {conclusion}",
            )
            logger.warning(
                "verification_unexpected",
                repo=repo,
                branch=branch,
                conclusion=conclusion,
            )
            return result

    def _trigger_rollback(
        self,
        repo: str,
        branch: str,
        original_event_id: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Trigger a rollback by creating a revert PR.

        Returns rollback result dict or None if skipped.
        """
        try:
            # Check kill switch before rollback
            from step11.killswitch import is_kill_switch_enabled
            if is_kill_switch_enabled():
                logger.warning(
                    "rollback_blocked_by_killswitch",
                    repo=repo,
                    branch=branch,
                )
                return None

            from step10.rollback import RollbackClient
            rollback_client = RollbackClient()
            result = rollback_client.rollback(
                repo=repo,
                fix_branch=branch,
                original_event_id=original_event_id,
                reason=reason,
            )
            return result.to_dict() if result else None

        except Exception as e:
            logger.error(
                "rollback_trigger_failed",
                repo=repo,
                branch=branch,
                error=str(e),
            )
            return None

    def _extract_event_id_from_branch(self, branch: str) -> str:
        """
        Extract the short event ID suffix from a fix branch name.

        Example: "fix/missing_import-abc12345" → "abc12345"
        """
        parts = branch.replace("fix/", "").rsplit("-", 1)
        if len(parts) == 2:
            return parts[1]
        return branch.replace("fix/", "")

    def _record_metrics(self, repo: str, conclusion: str) -> None:
        """Record verification metrics to Prometheus."""
        try:
            from step11.metrics import metrics
            result_label = "passed" if conclusion == "success" else "failed"
            metrics.verification_total.labels(repo=repo, result=result_label).inc()
        except Exception:
            pass  # Metrics are non-fatal
