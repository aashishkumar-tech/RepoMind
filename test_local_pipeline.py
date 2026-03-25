"""
test_local_pipeline.py — Simulate Full Pipeline Locally

HOW TO USE:
───────────
    python test_local_pipeline.py

This simulates the entire pipeline WITHOUT needing:
    - A real GitHub webhook
    - AWS SQS
    - A real CI failure

It creates a fake SQS message and runs it through the Worker,
so you can verify the full pipeline works end-to-end on your machine.

WHAT IT TESTS:
    ✅ Log fetching (from GitHub, needs GITHUB_APP_ID set)
    ✅ Sanitization
    ✅ Excerpt generation
    ✅ Triage (needs GROQ_API_KEY for LLM, falls back to heuristic)
    ✅ Plan generation
    ✅ Policy evaluation
    ✅ PR creation (needs GitHub App with write permissions)
    ✅ Artifact storage (writes to ./data/ in dev mode)
    ✅ Timeline tracking

SKIP PR CREATION:
    Set CREATE_PR=false to skip the PR step (useful for testing triage/plan only)
"""

import os
import json
import sys

# Ensure we're in development mode
os.environ.setdefault("ENVIRONMENT", "development")

from shared.config import settings
from shared.event_id import generate_event_id
from shared.logger import get_logger
from step2.worker import Worker

logger = get_logger("test_pipeline")


def simulate_pipeline():
    """Run the full pipeline with a simulated event."""

    # You can set these in .env or here
    repo = settings.TARGET_REPO or "your-username/mlproject"

    # Use a real workflow run ID from your repo, or 0 for dry run
    workflow_run_id = int(os.getenv("TEST_RUN_ID", "0"))

    event_id = generate_event_id(repo, workflow_run_id)

    print("\n" + "=" * 60)
    print("  🧪 RepoMind Pipeline — Local Simulation")
    print("=" * 60)
    print(f"  Event ID:     {event_id}")
    print(f"  Repository:   {repo}")
    print(f"  Run ID:       {workflow_run_id}")
    print(f"  Environment:  {settings.ENVIRONMENT}")
    print(f"  Groq API:     {'✅ Configured' if settings.GROQ_API_KEY else '❌ Not set (heuristic mode)'}")
    print(f"  GitHub App:   {'✅ Configured' if settings.GITHUB_APP_ID else '❌ Not set'}")
    print("=" * 60 + "\n")

    # Simulate the SQS message that Step 1 would send
    sqs_message = {
        "event_id": event_id,
        "repo": repo,
        "workflow_run_id": workflow_run_id,
        "run_url": f"https://github.com/{repo}/actions/runs/{workflow_run_id}",
        "head_branch": "main",
        "head_sha": "abc123",
        "timestamp": "2025-01-01T00:00:00Z",
    }

    print(f"📨 Simulated SQS Message:")
    print(json.dumps(sqs_message, indent=2))
    print()

    # Run the worker
    worker = Worker()

    if workflow_run_id == 0:
        print("⚠️  Run ID is 0 — skipping real log fetch.")
        print("    Set TEST_RUN_ID=<real_run_id> in .env to test with real logs.")
        print("    Testing excerpt + triage with sample logs...\n")

        # Use sample failed log for testing
        sample_log = _get_sample_failed_log()
        _test_excerpt_and_triage(sample_log, repo)
    else:
        print(f"🔄 Running full pipeline for run {workflow_run_id}...\n")
        artifacts = worker.process_event(sqs_message)
        print("\n📦 Final Artifacts:")
        print(json.dumps(artifacts, indent=2))

    print("\n✅ Pipeline simulation complete!")
    print(f"   Check ./data/ for stored artifacts.\n")


def _test_excerpt_and_triage(sample_log: str, repo: str):
    """Test excerpt generation and triage with sample logs."""
    from step2.sanitizer import Sanitizer
    from step2.excerpt import ExcerptGenerator
    from step5.triage import TriageEngine
    from step6.planner import Planner
    from step7.policy import PolicyEngine

    print("1️⃣  Sanitizing logs...")
    sanitizer = Sanitizer()
    clean_log = sanitizer.sanitize(sample_log)
    print(f"   Done. ({len(clean_log)} chars)\n")

    print("2️⃣  Generating excerpt...")
    excerpt_gen = ExcerptGenerator()
    excerpt = excerpt_gen.generate(clean_log)
    print(f"   Done. ({len(excerpt.splitlines())} lines)")
    print(f"   First 5 lines:\n   " + "\n   ".join(excerpt.splitlines()[:5]) + "\n")

    print("3️⃣  Running triage...")
    triage = TriageEngine()
    result = triage.classify(excerpt, repo)
    print(f"   Failure Type: {result['failure_type']}")
    print(f"   Confidence:   {result['confidence']}")
    print(f"   Summary:      {result['summary']}\n")

    print("4️⃣  Generating plan...")
    planner = Planner()
    plan = planner.generate_plan(result, excerpt, repo)
    print(f"   Playbook:     {plan.get('playbook_id')}")
    print(f"   Risk Level:   {plan.get('risk_level')}")
    print(f"   Actions:      {plan.get('actions')}\n")

    print("5️⃣  Evaluating policy...")
    policy = PolicyEngine()
    decision = policy.evaluate(result, plan, repo)
    print(f"   Decision:     {decision['decision']}")
    print(f"   Reason:       {decision['reason']}")
    print(f"   Rules:        {decision['rules_triggered']}\n")


def _get_sample_failed_log() -> str:
    """Return a realistic sample failed CI log for testing."""
    return """
=== build/1_Build.txt ===
Run pip install -r requirements.txt
Collecting flask==3.0.0
  Downloading Flask-3.0.0-py3-none-any.whl (101 kB)
Collecting requests==2.31.0
  Downloading requests-2.31.0-py3-none-any.whl (62 kB)
Successfully installed flask-3.0.0 requests-2.31.0

Run python -m pytest tests/ -v
============================= test session starts ==============================
platform linux -- Python 3.12.0, pytest-8.0.0
collecting ... collected 5 items

tests/test_app.py::test_home PASSED
tests/test_app.py::test_health PASSED
tests/test_app.py::test_api_endpoint FAILED

=================================== FAILURES ===================================
________________________________ test_api_endpoint _____________________________

    def test_api_endpoint():
>       from app.utils import parse_data
E       ModuleNotFoundError: No module named 'app.utils'

tests/test_app.py:25: ModuleNotFoundError
=========================== short test summary info ============================
FAILED tests/test_app.py::test_api_endpoint - ModuleNotFoundError: No module named 'app.utils'
========================= 1 failed, 2 passed in 3.42s =========================
Error: Process completed with exit code 1
"""


if __name__ == "__main__":
    simulate_pipeline()
