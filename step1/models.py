"""
step1/models.py — Pydantic Models for Webhook Events

HOW IT WORKS:
─────────────
Defines the data structures that flow through Step 1:

1. GitHubWebhookPayload — the raw incoming GitHub event (we extract only what we need)
2. SQSMessage          — the normalized message we push to SQS for Step 2

WHY PYDANTIC:
    - Automatic validation (reject malformed payloads instantly)
    - Type safety (IDE autocomplete, catch bugs early)
    - Serialization (.model_dump() → dict → JSON)

DATA FLOW:
    GitHub sends → raw JSON → we parse → GitHubWebhookPayload
    We build → SQSMessage → serialize → send to SQS → Step 2 consumes
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


class WorkflowRun(BaseModel):
    """
    Subset of GitHub's workflow_run object.
    We only extract the fields we need.
    Full spec: https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run
    """
    id: int
    name: str = ""
    status: str = ""            # "completed"
    conclusion: Optional[str] = None   # "failure", "success", "cancelled"
    html_url: str = ""
    head_branch: str = ""
    head_sha: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Repository(BaseModel):
    """Subset of the repository object from the webhook payload."""
    id: int
    full_name: str = ""         # "username/mlproject"
    html_url: str = ""
    default_branch: str = "main"


class GitHubWebhookPayload(BaseModel):
    """
    The incoming webhook payload from GitHub.

    We only care about 'workflow_run' events where:
      - action == "completed"
      - workflow_run.conclusion == "failure"
    """
    action: str = ""
    workflow_run: Optional[WorkflowRun] = None
    repository: Optional[Repository] = None

    def is_failed_workflow(self) -> bool:
        """
        Check if this event represents a failed CI workflow.

        Only these events trigger the auto-fix pipeline:
          action == "completed" AND conclusion == "failure"
        """
        if self.action != "completed":
            return False
        if self.workflow_run is None:
            return False
        return self.workflow_run.conclusion == "failure"

    def is_completed_workflow(self) -> bool:
        """
        Check if this event represents a completed workflow (any conclusion).

        Used by Step 10 to detect fix branch CI results.
        """
        if self.action != "completed":
            return False
        return self.workflow_run is not None


class SQSMessage(BaseModel):
    """
    The normalized message sent to SQS for Step 2 (Worker).

    This is the contract between Step 1 and Step 2.
    Step 2 expects exactly this shape.

    Fields:
        event_id:        Unique event identifier (evt-slug-runid-timestamp)
        repo:            Full repo name (owner/repo)
        workflow_run_id: GitHub's workflow run ID
        run_url:         Direct URL to the GitHub Actions run page
        head_branch:     Branch that triggered the workflow
        head_sha:        Commit SHA that triggered the workflow
        message_type:    "ci_failure" (default) or "verification" (Step 10)
        conclusion:      Workflow conclusion (for verification messages)
        timestamp:       ISO timestamp when we received the event
    """
    event_id: str
    repo: str
    workflow_run_id: int
    run_url: str
    head_branch: str = ""
    head_sha: str = ""
    message_type: str = "ci_failure"  # "ci_failure" | "verification"
    conclusion: str = ""  # For verification: "success" | "failure"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
