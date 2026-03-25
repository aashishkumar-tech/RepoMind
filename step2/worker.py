"""
step2/worker.py — Core Pipeline Orchestrator

HOW IT WORKS:
─────────────
This is the BRAIN of the pipeline. It receives an SQS message from Step 1
and orchestrates the ENTIRE fix pipeline:

    1. Fetch CI logs from GitHub        (log_fetcher.py)
    2. Sanitize logs                    (sanitizer.py)
    3. Generate excerpt                 (excerpt.py)
    4. Store logs + excerpt in S3       (shared/storage.py)
    5. Run triage (classify failure)    (step5/triage.py)
    6. Generate fix plan                (step6/planner.py)
    7. Evaluate policy                  (step7/policy.py)
    8. Create PR with fix               (step8/pr_creator.py)
    9. Code quality gate                (step9/code_checker.py)
    10. Verify fix + rollback           (step10/verifier.py)
    11. Metrics + kill switch           (step11/metrics.py, step11/killswitch.py)

ROUTING:
    message_type == "ci_failure"    → full pipeline (Steps 2-9)
    message_type == "verification"  → Step 10 only (verify + rollback)

ARCHITECTURE:
    The worker is the ONLY module that knows about the full pipeline.
    Each sub-step is a separate module that does ONE thing.
    The worker calls them in sequence and handles errors.

ERROR HANDLING:
    - Each step is wrapped in try/except
    - Errors are recorded in the timeline
    - On critical failure → pipeline stops, error notification sent
    - Partial artifacts are still saved (for debugging)

COMMUNICATION MAP:
    SQS Message → Worker → [kill switch check]
                         → [log_fetcher → sanitizer → excerpt]
                         → [triage → planner → policy → quality → pr_creator]
                         → [storage.put_json(artifacts)]
                         → [storage.put_json(timeline)]
                         → [notifier.send_email()]
                         → [push_metrics()]
"""

import json
import traceback
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from step2.log_fetcher import LogFetcher
from step2.sanitizer import Sanitizer
from step2.excerpt import ExcerptGenerator
from shared.config import settings
from shared.event_id import extract_repo_slug
from shared.storage import get_storage
from shared.timeline import Timeline
from shared.notifier import Notifier
from shared.logger import get_logger

logger = get_logger("step2.worker")


@dataclass
class PipelineContext:
    """
    Carries all data through the pipeline.

    Each step reads from and writes to this context.
    At the end, the worker serializes it to artifacts.json.
    """
    event_id: str
    repo: str
    workflow_run_id: int
    run_url: str
    head_branch: str = ""
    head_sha: str = ""

    # Populated by pipeline steps
    raw_logs: Optional[str] = None
    sanitized_logs: Optional[str] = None
    excerpt: Optional[str] = None

    triage: Optional[Dict[str, Any]] = None
    plan_summary: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None
    code_quality: Optional[Dict[str, Any]] = None
    pr: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None

    errors: list = field(default_factory=list)


class Worker:
    """
    Core pipeline orchestrator.

    Runs the entire CI auto-fix pipeline for a single event.
    """

    def __init__(self):
        self.storage = get_storage()
        self.log_fetcher = LogFetcher()
        self.sanitizer = Sanitizer()
        self.excerpt_generator = ExcerptGenerator()
        self.notifier = Notifier()

    def process_event(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single CI failure event end-to-end.

        Routes messages based on message_type:
            "ci_failure"    → full pipeline (default)
            "verification"  → Step 10 verification only

        Args:
            message: The SQS message dict from Step 1.
                    Contains: event_id, repo, workflow_run_id, run_url, timestamp

        Returns:
            Final artifacts dict containing all pipeline results.
        """
        # ── Route verification messages to Step 10 ──
        if message.get("message_type") == "verification":
            return self._handle_verification(message)

        # ── Kill Switch Check (Step 11) ──
        try:
            from step11.killswitch import is_kill_switch_enabled
            if is_kill_switch_enabled():
                logger.warning(
                    "kill_switch_active",
                    event_id=message.get("event_id"),
                    repo=message.get("repo"),
                )
                return {
                    "status": "halted",
                    "reason": "Kill switch is ON — pipeline halted",
                    "event_id": message.get("event_id"),
                }
        except Exception as e:
            # Kill switch check failure is non-fatal in development
            logger.warning("kill_switch_check_failed", error=str(e))

        # ── Record pipeline start metric ──
        try:
            from step11.metrics import metrics
            metrics.events_total.labels(
                repo=message.get("repo", "unknown"),
                status="started",
            ).inc()
        except Exception:
            pass

        # ── Initialize context and timeline ──
        ctx = PipelineContext(
            event_id=message["event_id"],
            repo=message["repo"],
            workflow_run_id=message["workflow_run_id"],
            run_url=message["run_url"],
            head_branch=message.get("head_branch", ""),
            head_sha=message.get("head_sha", ""),
        )
        timeline = Timeline(event_id=ctx.event_id)
        repo_slug = extract_repo_slug(ctx.event_id)
        base_path = f"events/{repo_slug}/{ctx.event_id}"

        logger.info(
            "pipeline_started",
            event_id=ctx.event_id,
            repo=ctx.repo,
            run_id=ctx.workflow_run_id,
        )

        timeline.record(
            step=1,
            event_type="event_received",
            summary=f"Processing workflow run {ctx.workflow_run_id} for {ctx.repo}",
        )

        # ── Step 2a: Fetch Logs ──
        try:
            timeline.start_step(2)
            ctx.raw_logs = self.log_fetcher.fetch_logs(ctx.repo, ctx.workflow_run_id)

            if ctx.raw_logs:
                timeline.record(
                    step=2,
                    event_type="logs_downloaded",
                    summary=f"Downloaded {len(ctx.raw_logs)} bytes of logs",
                )
            else:
                timeline.record_error(step=2, error="Failed to download logs")
                self._finalize(ctx, timeline, base_path)
                return self._build_artifacts(ctx)

        except Exception as e:
            self._handle_error(ctx, timeline, 2, "log_fetch_failed", e)
            self._finalize(ctx, timeline, base_path)
            return self._build_artifacts(ctx)

        # ── Step 2b: Sanitize ──
        try:
            ctx.sanitized_logs = self.sanitizer.sanitize(ctx.raw_logs)
            # Store full logs
            self.storage.put_text(f"{base_path}/logs/full_logs.txt", ctx.sanitized_logs)
        except Exception as e:
            self._handle_error(ctx, timeline, 2, "sanitization_failed", e)

        # ── Step 2c: Generate Excerpt ──
        try:
            logs_to_excerpt = ctx.sanitized_logs or ctx.raw_logs
            ctx.excerpt = self.excerpt_generator.generate(logs_to_excerpt)

            # Store excerpt
            self.storage.put_text(f"{base_path}/logs/excerpt.txt", ctx.excerpt)

            timeline.record(
                step=2,
                event_type="excerpt_generated",
                summary=f"Excerpt: {len(ctx.excerpt.splitlines())} lines",
            )
        except Exception as e:
            self._handle_error(ctx, timeline, 2, "excerpt_failed", e)
            self._finalize(ctx, timeline, base_path)
            return self._build_artifacts(ctx)

        # ── Step 5: Triage ──
        try:
            timeline.start_step(5)
            from step5.triage import TriageEngine
            triage_engine = TriageEngine()
            ctx.triage = triage_engine.classify(ctx.excerpt, ctx.repo)

            timeline.record(
                step=5,
                event_type="triage_completed",
                summary=f"{ctx.triage['failure_type']} ({ctx.triage['confidence']:.2f} confidence)",
            )
        except Exception as e:
            self._handle_error(ctx, timeline, 5, "triage_failed", e)
            self._finalize(ctx, timeline, base_path)
            return self._build_artifacts(ctx)

        # ── Step 6: Plan Generation ──
        try:
            timeline.start_step(6)
            from step6.planner import Planner
            planner = Planner()
            ctx.plan_summary = planner.generate_plan(ctx.triage, ctx.excerpt, ctx.repo)

            timeline.record(
                step=6,
                event_type="plan_generated",
                summary=f"Playbook: {ctx.plan_summary.get('playbook_id', 'custom')}",
            )
        except Exception as e:
            self._handle_error(ctx, timeline, 6, "plan_failed", e)
            self._finalize(ctx, timeline, base_path)
            return self._build_artifacts(ctx)

        # ── Step 7: Policy Evaluation ──
        try:
            timeline.start_step(7)
            from step7.policy import PolicyEngine
            policy_engine = PolicyEngine()
            ctx.policy = policy_engine.evaluate(ctx.triage, ctx.plan_summary, ctx.repo)

            timeline.record(
                step=7,
                event_type="policy_evaluated",
                summary=f"Decision: {ctx.policy['decision']}",
            )

            if ctx.policy["decision"] == "deny":
                logger.info("policy_denied", event_id=ctx.event_id, reason=ctx.policy.get("reason"))
                self.notifier.notify_policy_denied(
                    event_id=ctx.event_id,
                    repo=ctx.repo,
                    reason=ctx.policy.get("reason", "Policy denied"),
                )
                self._finalize(ctx, timeline, base_path)
                return self._build_artifacts(ctx)

        except Exception as e:
            self._handle_error(ctx, timeline, 7, "policy_failed", e)
            self._finalize(ctx, timeline, base_path)
            return self._build_artifacts(ctx)

        # ── Step 9: Code Quality Gate ──
        try:
            timeline.start_step(9)
            from step9.code_checker import CodeChecker
            checker = CodeChecker()
            code_changes = ctx.plan_summary.get("code_changes", []) if ctx.plan_summary else []
            ctx.code_quality = checker.check(code_changes)

            timeline.record(
                step=9,
                event_type="code_quality_checked",
                summary=f"Quality: {'PASSED' if ctx.code_quality['passed'] else 'BLOCKED'} — {ctx.code_quality['summary']}",
            )

            if not ctx.code_quality["passed"]:
                logger.warning(
                    "code_quality_blocked",
                    event_id=ctx.event_id,
                    blocking_failures=ctx.code_quality["blocking_failures"],
                    summary=ctx.code_quality["summary"],
                )
                self._finalize(ctx, timeline, base_path)
                return self._build_artifacts(ctx)

        except Exception as e:
            # Code checker failure is non-fatal — proceed to PR
            self._handle_error(ctx, timeline, 9, "code_quality_check_failed", e)

        # ── Step 8: PR Creation ──
        try:
            timeline.start_step(8)
            from step8.pr_creator import PRCreator
            pr_creator = PRCreator()
            ctx.pr = pr_creator.create_pr(
                repo=ctx.repo,
                triage=ctx.triage,
                plan=ctx.plan_summary,
                event_id=ctx.event_id,
                head_branch=ctx.head_branch,
            )

            timeline.record(
                step=8,
                event_type="pr_created",
                summary=f"PR: {ctx.pr.get('url', 'unknown')}",
            )

            # Notify success
            self.notifier.notify_pipeline_success(
                event_id=ctx.event_id,
                repo=ctx.repo,
                pr_url=ctx.pr.get("url", ""),
            )

        except Exception as e:
            self._handle_error(ctx, timeline, 8, "pr_creation_failed", e)

        # ── Step 3: Index to Vector DB (non-blocking) ──
        try:
            timeline.start_step(3)
            from step3.indexer import Indexer
            indexer = Indexer()
            count = indexer.index_event(
                event_id=ctx.event_id,
                repo=ctx.repo,
                excerpt=ctx.excerpt,
                triage=ctx.triage,
                plan=ctx.plan_summary,
                verification=ctx.verification,
            )
            timeline.record(
                step=3,
                event_type="vectors_indexed",
                summary=f"Indexed {count} vectors to Qdrant",
            )
        except Exception as e:
            # Non-fatal: vector indexing failure shouldn't break the pipeline
            self._handle_error(ctx, timeline, 3, "indexing_failed", e)

        # ── Finalize ──
        self._finalize(ctx, timeline, base_path)
        return self._build_artifacts(ctx)

    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────
    def _handle_error(
        self,
        ctx: PipelineContext,
        timeline: Timeline,
        step: int,
        error_type: str,
        exception: Exception,
    ) -> None:
        """Record an error in context, timeline, and logs."""
        error_msg = f"{error_type}: {str(exception)}"
        ctx.errors.append({"step": step, "error": error_msg})
        timeline.record_error(step=step, error=error_msg)
        logger.error(
            error_type,
            event_id=ctx.event_id,
            step=step,
            error=str(exception),
            traceback=traceback.format_exc(),
        )

    def _build_artifacts(self, ctx: PipelineContext) -> Dict[str, Any]:
        """Build the final artifacts.json from the pipeline context."""
        artifacts = {}
        if ctx.triage:
            artifacts["triage"] = ctx.triage
        if ctx.plan_summary:
            artifacts["plan_summary"] = ctx.plan_summary
        if ctx.policy:
            artifacts["policy"] = ctx.policy
        if ctx.code_quality:
            artifacts["code_quality"] = ctx.code_quality
        if ctx.pr:
            artifacts["pr"] = ctx.pr
        if ctx.verification:
            artifacts["verification"] = ctx.verification
        if ctx.errors:
            artifacts["errors"] = ctx.errors
        return artifacts

    def _finalize(
        self,
        ctx: PipelineContext,
        timeline: Timeline,
        base_path: str,
    ) -> None:
        """Save artifacts and timeline to storage. Push metrics."""
        try:
            artifacts = self._build_artifacts(ctx)
            self.storage.put_json(f"{base_path}/artifacts.json", artifacts)
            self.storage.put_json(f"{base_path}/timeline.json", timeline.to_dict())

            logger.info(
                "pipeline_finalized",
                event_id=ctx.event_id,
                has_errors=bool(ctx.errors),
                steps_completed=len(timeline),
            )
        except Exception as e:
            logger.error(
                "finalize_failed",
                event_id=ctx.event_id,
                error=str(e),
            )

        # Record final status metric
        try:
            from step11.metrics import metrics
            status = "error" if ctx.errors else "completed"
            if ctx.policy and ctx.policy.get("decision") == "deny":
                status = "denied"
            if ctx.code_quality and not ctx.code_quality.get("passed", True):
                status = "quality_blocked"
            metrics.events_total.labels(repo=ctx.repo, status=status).inc()
        except Exception:
            pass

        # Push all metrics to Pushgateway (non-blocking)
        try:
            from step11.metrics import push_metrics
            push_metrics(job="repomind-worker")
        except Exception as e:
            logger.debug("metrics_push_error", error=str(e))

        # Send failure notification if there were errors
        if ctx.errors:
            self.notifier.notify_pipeline_failure(
                event_id=ctx.event_id,
                repo=ctx.repo,
                error=ctx.errors[-1].get("error", "Unknown error"),
            )


    def _handle_verification(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a verification message (Step 10).

        Called when a CI run completes on a fix/* branch.
        Verifies if the fix worked and triggers rollback if not.
        """
        logger.info(
            "verification_started",
            event_id=message.get("event_id"),
            repo=message.get("repo"),
            branch=message.get("head_branch"),
            conclusion=message.get("conclusion"),
        )

        try:
            from step10.verifier import Verifier
            verifier = Verifier()
            result = verifier.verify(
                repo=message["repo"],
                workflow_run_id=message["workflow_run_id"],
                branch=message.get("head_branch", ""),
                conclusion=message.get("conclusion", ""),
                head_sha=message.get("head_sha", ""),
                run_url=message.get("run_url", ""),
            )

            # Store verification result
            from shared.event_id import extract_repo_slug
            repo_slug = extract_repo_slug(message["event_id"])
            base_path = f"events/{repo_slug}/{message['event_id']}"
            self.storage.put_json(
                f"{base_path}/verification.json",
                result.to_dict(),
            )

            logger.info(
                "verification_completed",
                event_id=message.get("event_id"),
                status=result.status,
                rollback_triggered=result.rollback_triggered,
            )

            # Push metrics
            try:
                from step11.metrics import push_metrics
                push_metrics(job="repomind-verifier")
            except Exception:
                pass

            return result.to_dict()

        except Exception as e:
            logger.error(
                "verification_failed",
                event_id=message.get("event_id"),
                error=str(e),
            )
            return {
                "status": "error",
                "error": str(e),
                "event_id": message.get("event_id"),
            }


# ──────────────────────────────────────────────
# Lambda handler for SQS trigger
# ──────────────────────────────────────────────
def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    Triggered by SQS. Processes each record (message).
    """
    worker = Worker()

    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            logger.info("sqs_message_received", event_id=message.get("event_id"))
            worker.process_event(message)
        except Exception as e:
            logger.error("sqs_processing_failed", error=str(e))
            raise  # Let Lambda retry via SQS visibility timeout
