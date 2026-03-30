"""
step10 — Verifier + Rollback

Provides:
  - Verifier: checks if a fix branch CI passed or failed (step10.verifier)
  - RollbackClient: creates a revert PR when fix CI fails (step10.rollback)
  - Models: VerificationResult dataclass (step10.models)

TRIGGER:
    GitHub sends workflow_run.completed on fix/* branches.
    Step 1 routes it to the worker with message_type="verification".
    Worker delegates to Step 10 Verifier.

COMMUNICATION:
─────────────
Step 1 (webhook) → routes fix/* branch events → SQS → Worker
Worker → step10.verifier.verify() → step10.rollback.rollback() (if CI failed)
"""
