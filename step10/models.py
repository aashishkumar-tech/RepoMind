"""
step10/models.py — Data Models for Verification + Rollback

HOW IT WORKS:
─────────────
Defines the data structures used by the Verifier and RollbackClient.

DATA FLOW:
    Verifier.verify() → VerificationResult
    RollbackClient.rollback() → RollbackResult
    Both stored in artifacts.json under "verification" key
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime, timezone


@dataclass
class VerificationResult:
    """
    Result of verifying whether a fix branch CI passed.

    Fields:
        status: "passed" | "failed" | "error"
        ci_conclusion: GitHub workflow_run conclusion (e.g. "success", "failure")
        fix_branch: The fix/* branch that was verified
        repo: Repository full name
        workflow_run_id: The verification workflow run ID
        original_event_id: The event ID that created the fix PR
        message: Human-readable summary
        rollback_triggered: Whether a rollback was initiated
        rollback_pr_url: URL of the revert PR (if rollback was triggered)
    """
    status: str  # "passed" | "failed" | "error"
    ci_conclusion: str = ""
    fix_branch: str = ""
    repo: str = ""
    workflow_run_id: int = 0
    original_event_id: str = ""
    message: str = ""
    rollback_triggered: bool = False
    rollback_pr_url: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ci_conclusion": self.ci_conclusion,
            "fix_branch": self.fix_branch,
            "repo": self.repo,
            "workflow_run_id": self.workflow_run_id,
            "original_event_id": self.original_event_id,
            "message": self.message,
            "rollback_triggered": self.rollback_triggered,
            "rollback_pr_url": self.rollback_pr_url,
            "timestamp": self.timestamp,
        }


@dataclass
class RollbackResult:
    """
    Result of a rollback operation.

    Fields:
        status: "reverted" | "skipped" | "error"
        revert_pr_url: URL of the revert PR
        reason: Why rollback was triggered
        original_pr_number: The PR that was reverted
        message: Human-readable summary
    """
    status: str  # "reverted" | "skipped" | "error"
    revert_pr_url: str = ""
    reason: str = ""
    original_pr_number: int = 0
    message: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "revert_pr_url": self.revert_pr_url,
            "reason": self.reason,
            "original_pr_number": self.original_pr_number,
            "message": self.message,
            "timestamp": self.timestamp,
        }
