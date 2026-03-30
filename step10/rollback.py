"""
step10/rollback.py — Safe Rollback via Revert PR

HOW IT WORKS:
─────────────
When the Verifier detects that a fix branch CI failed, the RollbackClient
creates a REVERT PR that undoes the fix.

FLOW:
    1. Find the merged fix PR on the fix/* branch
    2. Anti-flapping check: has this event already been rolled back?
    3. Rate limit check: max N rollbacks per repo per hour
    4. Create a revert branch from the default branch
    5. Revert the merge commit
    6. Open a revert PR with full context
    7. Post a comment on the original fix PR
    8. Store rollback record in S3
    9. Push rollback metrics

SAFETY GUARDS:
    ┌──────────────────┬──────────────────────────────────────────┐
    │ Guard            │ How                                      │
    ├──────────────────┼──────────────────────────────────────────┤
    │ Anti-flapping    │ S3 key rollback.json — if exists, skip  │
    │ Rate limit       │ Max 3 rollbacks per repo per hour       │
    │ Kill switch      │ Checked by Verifier before calling us   │
    │ Branch filter    │ Only rollback fix/* branches             │
    │ Revert PR        │ Creates PR, not direct push (review)    │
    │ Audit trail      │ Everything logged + stored in S3        │
    └──────────────────┴──────────────────────────────────────────┘

COMMUNICATION:
─────────────
Verifier → RollbackClient.rollback(repo, fix_branch, event_id, reason)
RollbackClient → GitHub API (PyGithub) → create revert PR
RollbackClient → storage.put_json(rollback record)
RollbackClient → notifier.send_email(rollback notification)
RollbackClient → metrics.rollbacks_total.inc()
"""

import time
from typing import Optional, Dict, Any, List

from step10.models import RollbackResult
from shared.logger import get_logger
from shared.storage import get_storage
from shared.config import settings

logger = get_logger("step10.rollback")


class RollbackClient:
    """
    Creates revert PRs to undo failed auto-fixes.

    Safety: anti-flapping, rate limiting, audit trail.
    """

    def __init__(self):
        self.storage = get_storage()
        self.max_rollbacks_per_hour = int(
            getattr(settings, "MAX_ROLLBACKS_PER_HOUR", "3")
        )

    def rollback(
        self,
        repo: str,
        fix_branch: str,
        original_event_id: str,
        reason: str,
    ) -> Optional[RollbackResult]:
        """
        Create a revert PR for a failed fix.

        Args:
            repo: Repository full name (e.g. "user/mlproject")
            fix_branch: The fix/* branch to revert
            original_event_id: The event ID that created the original fix
            reason: Why rollback is being triggered

        Returns:
            RollbackResult or None if skipped
        """
        logger.info(
            "rollback_started",
            repo=repo,
            fix_branch=fix_branch,
            event_id=original_event_id,
            reason=reason,
        )

        # ── Guard 1: Anti-flapping check ──
        if self._already_rolled_back(repo, original_event_id):
            logger.warning(
                "rollback_skipped_antiflap",
                repo=repo,
                event_id=original_event_id,
            )
            return RollbackResult(
                status="skipped",
                reason="Already rolled back (anti-flapping)",
                message=f"Rollback skipped: {original_event_id} was already rolled back",
            )

        # ── Guard 2: Rate limit check ──
        if self._rate_limit_exceeded(repo):
            logger.warning(
                "rollback_skipped_ratelimit",
                repo=repo,
                max_per_hour=self.max_rollbacks_per_hour,
            )
            return RollbackResult(
                status="skipped",
                reason=f"Rate limit exceeded ({self.max_rollbacks_per_hour}/hour)",
                message=f"Rollback skipped: rate limit exceeded for {repo}",
            )

        # ── Create revert PR ──
        try:
            revert_result = self._create_revert_pr(
                repo=repo,
                fix_branch=fix_branch,
                original_event_id=original_event_id,
                reason=reason,
            )

            # Store rollback record
            self._store_rollback_record(
                repo=repo,
                original_event_id=original_event_id,
                revert_result=revert_result,
            )

            # Push metrics
            self._record_metrics(repo, reason)

            # Send notification
            self._notify_rollback(repo, fix_branch, revert_result)

            return revert_result

        except Exception as e:
            logger.error(
                "rollback_failed",
                repo=repo,
                fix_branch=fix_branch,
                error=str(e),
            )
            return RollbackResult(
                status="error",
                reason=reason,
                message=f"Rollback failed: {str(e)}",
            )

    def _create_revert_pr(
        self,
        repo: str,
        fix_branch: str,
        original_event_id: str,
        reason: str,
    ) -> RollbackResult:
        """
        Create a revert PR using GitHub API.

        Steps:
            1. Get the merged PR for the fix branch
            2. Find the merge commit
            3. Create revert branch
            4. Revert the merge commit
            5. Open the revert PR
        """
        from shared.github_auth import get_github_client

        g = get_github_client()
        repository = g.get_repo(repo)
        default_branch = repository.default_branch

        # Find the merged fix PR
        fix_pr = self._find_merged_pr(repository, fix_branch)
        if not fix_pr:
            return RollbackResult(
                status="skipped",
                reason="No merged PR found for fix branch",
                message=f"Cannot rollback: no merged PR found for {fix_branch}",
            )

        # Get the merge commit
        merge_commit_sha = fix_pr.merge_commit_sha
        if not merge_commit_sha:
            return RollbackResult(
                status="skipped",
                reason="No merge commit found",
                original_pr_number=fix_pr.number,
                message=f"Cannot rollback: PR #{fix_pr.number} has no merge commit",
            )

        # Create revert branch
        revert_branch = f"revert-{fix_branch}"
        base_ref = repository.get_git_ref(f"heads/{default_branch}")
        base_sha = base_ref.object.sha

        try:
            repository.create_git_ref(
                ref=f"refs/heads/{revert_branch}",
                sha=base_sha,
            )
        except Exception as e:
            if "Reference already exists" in str(e):
                logger.warning("revert_branch_exists", branch=revert_branch)
            else:
                raise

        # Revert the changes by restoring files to pre-merge state
        merge_commit = repository.get_commit(merge_commit_sha)
        parent_sha = merge_commit.parents[0].sha if merge_commit.parents else base_sha

        for file_info in merge_commit.files:
            try:
                if file_info.status == "added":
                    # File was added in fix — delete it in revert
                    current = repository.get_contents(file_info.filename, ref=revert_branch)
                    repository.delete_file(
                        path=file_info.filename,
                        message=f"revert: undo {fix_branch} [{original_event_id[:20]}]",
                        sha=current.sha,
                        branch=revert_branch,
                    )
                elif file_info.status == "removed":
                    # File was removed in fix — restore it from parent
                    parent_content = repository.get_contents(file_info.filename, ref=parent_sha)
                    repository.create_file(
                        path=file_info.filename,
                        message=f"revert: restore {file_info.filename} [{original_event_id[:20]}]",
                        content=parent_content.decoded_content.decode("utf-8"),
                        branch=revert_branch,
                    )
                else:
                    # File was modified — restore original version
                    parent_content = repository.get_contents(file_info.filename, ref=parent_sha)
                    current = repository.get_contents(file_info.filename, ref=revert_branch)
                    repository.update_file(
                        path=file_info.filename,
                        message=f"revert: restore {file_info.filename} [{original_event_id[:20]}]",
                        content=parent_content.decoded_content.decode("utf-8"),
                        sha=current.sha,
                        branch=revert_branch,
                    )
            except Exception as e:
                logger.error(
                    "revert_file_failed",
                    file=file_info.filename,
                    error=str(e),
                )

        # Create the revert PR
        pr_title = f"🔄 [RepoMind] Revert: {fix_branch}"
        pr_body = self._build_revert_pr_body(
            fix_branch=fix_branch,
            fix_pr_number=fix_pr.number,
            fix_pr_url=fix_pr.html_url,
            reason=reason,
            original_event_id=original_event_id,
        )

        revert_pr = repository.create_pull(
            title=pr_title,
            body=pr_body,
            head=revert_branch,
            base=default_branch,
        )

        try:
            revert_pr.add_to_labels("repomind-revert")
        except Exception:
            pass

        # Comment on the original fix PR
        try:
            fix_pr.create_issue_comment(
                f"⚠️ **RepoMind Rollback**\n\n"
                f"This fix **failed CI verification**. A revert PR has been created:\n"
                f"➡️ {revert_pr.html_url}\n\n"
                f"**Reason:** {reason}\n\n"
                f"*The auto-fix will not be retried automatically. Manual investigation required.*"
            )
        except Exception as e:
            logger.warning("revert_comment_failed", error=str(e))

        logger.info(
            "revert_pr_created",
            repo=repo,
            revert_pr=revert_pr.html_url,
            original_pr=fix_pr.number,
        )

        return RollbackResult(
            status="reverted",
            revert_pr_url=revert_pr.html_url,
            reason=reason,
            original_pr_number=fix_pr.number,
            message=f"Revert PR created: {revert_pr.html_url}",
        )

    def _find_merged_pr(self, repository, branch: str):
        """Find the merged PR for a given branch."""
        try:
            pulls = repository.get_pulls(state="closed", head=f"{repository.owner.login}:{branch}")
            for pr in pulls:
                if pr.merged:
                    return pr
            return None
        except Exception as e:
            logger.error("find_merged_pr_failed", branch=branch, error=str(e))
            return None

    def _already_rolled_back(self, repo: str, event_id: str) -> bool:
        """Check if this event was already rolled back (anti-flapping)."""
        from shared.event_id import extract_repo_slug
        slug = extract_repo_slug(f"evt-{repo.replace('/', '-')}-0-0")
        key = f"events/{slug}/{event_id}/rollback.json"
        return self.storage.exists(key)

    def _rate_limit_exceeded(self, repo: str) -> bool:
        """
        Check if rollback rate limit is exceeded.

        Uses a simple counter file in storage:
            rollbacks/<repo-slug>/hourly_count.json
            Contains: {"count": N, "window_start": timestamp}
        """
        from shared.event_id import _slugify
        slug = _slugify(repo)
        key = f"rollbacks/{slug}/hourly_count.json"

        try:
            data = self.storage.get_json(key)
            if data is None:
                # First rollback — create counter
                self.storage.put_json(key, {
                    "count": 1,
                    "window_start": time.time(),
                })
                return False

            window_start = data.get("window_start", 0)
            count = data.get("count", 0)

            # Reset window if more than 1 hour old
            if time.time() - window_start > 3600:
                self.storage.put_json(key, {
                    "count": 1,
                    "window_start": time.time(),
                })
                return False

            if count >= self.max_rollbacks_per_hour:
                return True

            # Increment counter
            self.storage.put_json(key, {
                "count": count + 1,
                "window_start": window_start,
            })
            return False

        except Exception as e:
            logger.warning("rate_limit_check_failed", error=str(e))
            return False  # Don't block rollback if rate limit check fails

    def _store_rollback_record(
        self,
        repo: str,
        original_event_id: str,
        revert_result: RollbackResult,
    ) -> None:
        """Store rollback record in S3 for anti-flapping and audit trail."""
        try:
            from shared.event_id import extract_repo_slug
            slug = extract_repo_slug(f"evt-{repo.replace('/', '-')}-0-0")
            key = f"events/{slug}/{original_event_id}/rollback.json"
            self.storage.put_json(key, revert_result.to_dict())
        except Exception as e:
            logger.error("store_rollback_record_failed", error=str(e))

    def _record_metrics(self, repo: str, reason: str) -> None:
        """Record rollback metrics to Prometheus."""
        try:
            from step11.metrics import metrics
            metrics.rollbacks_total.labels(repo=repo, reason=reason[:50]).inc()
        except Exception:
            pass

    def _notify_rollback(
        self,
        repo: str,
        fix_branch: str,
        result: RollbackResult,
    ) -> None:
        """Send rollback notification email."""
        try:
            from shared.notifier import Notifier
            notifier = Notifier()
            notifier.send_email(
                subject=f"🔄 RepoMind: Rollback triggered for {repo}",
                body=(
                    f"RepoMind CI Auto-Fix Agent — Rollback\n\n"
                    f"Repository: {repo}\n"
                    f"Fix Branch: {fix_branch}\n"
                    f"Status: {result.status}\n"
                    f"Reason: {result.reason}\n"
                    f"Revert PR: {result.revert_pr_url or 'N/A'}\n\n"
                    f"Manual investigation may be required."
                ),
            )
        except Exception as e:
            logger.warning("rollback_notification_failed", error=str(e))

    def _build_revert_pr_body(
        self,
        fix_branch: str,
        fix_pr_number: int,
        fix_pr_url: str,
        reason: str,
        original_event_id: str,
    ) -> str:
        """Build the revert PR body with full context."""
        return f"""## 🔄 RepoMind Revert

> This pull request **reverts** a failed auto-fix created by RepoMind.

### ❌ What Happened

The auto-fix PR (#{fix_pr_number}) was merged, but CI **failed** on the resulting code.
This revert undoes those changes to restore the repository to a working state.

### 📋 Details

| Field | Value |
|-------|-------|
| **Original Fix PR** | [#{fix_pr_number}]({fix_pr_url}) |
| **Fix Branch** | `{fix_branch}` |
| **Failure Reason** | {reason} |
| **Original Event ID** | `{original_event_id}` |

### ⚠️ Action Required

- [ ] Review this revert PR
- [ ] Merge to restore working state
- [ ] Investigate the original CI failure manually

### 🔒 Safety

This rollback was triggered automatically by RepoMind's verification system.
The original fix will **not** be retried automatically.

---
*Generated by [RepoMind](https://github.com/repomind) CI Auto-Fix Agent — Rollback System*
"""
