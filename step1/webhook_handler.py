"""
step1/webhook_handler.py — FastAPI Webhook Endpoint

HOW IT WORKS:
─────────────
This is the ENTRY POINT of the entire RepoMind pipeline.

1. GitHub sends a POST to /webhook when a workflow_run completes
2. We validate the HMAC-SHA256 signature (reject forgeries)
3. We parse the payload and check if it's a failure event
4. If yes → generate event_id → build SQS message → publish to queue
5. Return 202 Accepted (async processing)

ENDPOINTS:
    POST /webhook  — receives GitHub webhook events
    GET  /health   — health check (for monitoring)

WHAT THIS MODULE DOES NOT DO:
    ❌ Download logs
    ❌ Call LLM
    ❌ Write to S3
    ❌ Any heavy processing

Step 1 is LIGHTWEIGHT by design. All heavy work is in Step 2.

COMMUNICATION:
─────────────
GitHub → POST /webhook → validate → parse → SQS message → Step 2 Worker
                                                    ↑
                                            (this is the handoff)
"""

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse

from step1.models import GitHubWebhookPayload, SQSMessage
from step1.signature import validate_signature
from step1.sqs_client import get_queue_client
from shared.config import settings
from shared.event_id import generate_event_id
from shared.logger import get_logger

logger = get_logger("step1.webhook_handler")

# ──────────────────────────────────────────────
# FastAPI Application
# ──────────────────────────────────────────────
app = FastAPI(
    title="RepoMind Webhook Handler",
    description="Receives GitHub webhook events and queues CI failures for auto-fix",
    version="1.0.0",
)

# Queue client (SQS in prod, local in dev)
queue = get_queue_client()


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    Used by API Gateway, load balancers, and monitoring tools.
    """
    return {
        "status": "healthy",
        "service": "repomind-webhook",
        "environment": settings.ENVIRONMENT,
    }


# ──────────────────────────────────────────────
# Webhook Endpoint
# ──────────────────────────────────────────────
@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Receive and process GitHub webhook events.

    Flow:
        1. Read raw body (needed for signature validation)
        2. Validate HMAC-SHA256 signature
        3. Parse payload into GitHubWebhookPayload
        4. Check if it's a failed workflow_run
        5. Generate event_id
        6. Build SQSMessage
        7. Publish to queue
        8. Return 202 Accepted

    Returns:
        202: Event accepted and queued for processing
        200: Event received but not actionable (not a failure)
        403: Invalid signature
        400: Malformed payload
    """
    # ── Step 1: Read raw body ──
    body = await request.body()

    # ── Step 2: Validate signature ──
    signature = request.headers.get("X-Hub-Signature-256", "")
    github_event = request.headers.get("X-GitHub-Event", "")

    logger.info("webhook_received", event_type=github_event)

    if settings.GITHUB_WEBHOOK_SECRET:
        if not validate_signature(body, signature, settings.GITHUB_WEBHOOK_SECRET):
            logger.warning("webhook_signature_invalid")
            raise HTTPException(status_code=403, detail="Invalid signature")

    # ── Step 3: Parse payload ──
    try:
        payload_dict = await request.json()
        payload = GitHubWebhookPayload(**payload_dict)
    except Exception as e:
        logger.error("webhook_parse_error", error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    # ── Step 4: Check if actionable ──
    if github_event != "workflow_run":
        logger.info("webhook_ignored", reason="not workflow_run", event_type=github_event)
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "reason": "Not a workflow_run event"},
        )

    # ── Step 4a: Check for fix/* branch verification (Step 10) ──
    wf = payload.workflow_run
    if (
        wf
        and wf.head_branch.startswith("fix/")
        and payload.is_completed_workflow()
    ):
        repo_name = payload.repository.full_name
        event_id = generate_event_id(repo_name, wf.id)

        sqs_message = SQSMessage(
            event_id=event_id,
            repo=repo_name,
            workflow_run_id=wf.id,
            run_url=wf.html_url,
            head_branch=wf.head_branch,
            head_sha=wf.head_sha,
            message_type="verification",
            conclusion=wf.conclusion or "",
        )

        logger.info(
            "webhook_verification_routed",
            event_id=event_id,
            repo=repo_name,
            branch=wf.head_branch,
            conclusion=wf.conclusion,
        )

        success = queue.publish(sqs_message.model_dump())
        if not success:
            logger.error("webhook_queue_failed", event_id=event_id)
            raise HTTPException(status_code=500, detail="Failed to queue verification event")

        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "event_id": event_id,
                "message_type": "verification",
                "message": "Verification event queued for Step 10",
            },
        )

    if not payload.is_failed_workflow():
        logger.info(
            "webhook_ignored",
            reason="not a failure",
            action=payload.action,
            conclusion=payload.workflow_run.conclusion if payload.workflow_run else None,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "reason": "Not a failed workflow"},
        )

    # ── Step 5: Generate event ID ──
    wf = payload.workflow_run
    repo_name = payload.repository.full_name
    event_id = generate_event_id(repo_name, wf.id)

    # ── Step 6: Build SQS message ──
    sqs_message = SQSMessage(
        event_id=event_id,
        repo=repo_name,
        workflow_run_id=wf.id,
        run_url=wf.html_url,
        head_branch=wf.head_branch,
        head_sha=wf.head_sha,
    )

    logger.info(
        "webhook_processing",
        event_id=event_id,
        repo=repo_name,
        run_id=wf.id,
        branch=wf.head_branch,
    )

    # ── Step 7: Publish to queue ──
    success = queue.publish(sqs_message.model_dump())

    if not success:
        logger.error("webhook_queue_failed", event_id=event_id)
        raise HTTPException(status_code=500, detail="Failed to queue event")

    # ── Step 8: Return 202 ──
    logger.info("webhook_accepted", event_id=event_id)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "event_id": event_id,
            "message": "Event queued for processing",
        },
    )


# ──────────────────────────────────────────────
# Ping endpoint (GitHub sends a ping on App install)
# ──────────────────────────────────────────────
@app.post("/webhook/ping")
async def handle_ping():
    """Handle GitHub's ping event sent when webhook is first configured."""
    logger.info("ping_received")
    return {"status": "pong"}
