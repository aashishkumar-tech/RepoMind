# 📋 Changelog — RepoMind CI Auto-Fix Agent

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.2.0-alpha] — 2026-02-26

### 🆕 RAG Evaluation Metrics

#### Added

**Step 3 — RAG Metrics (`step3/rag_metrics.py`)**
- `RAGEvaluator` class — Comprehensive RAG pipeline quality evaluation
  - **Retrieval metrics:** hit rate, mean/max/min similarity, MRR, recall@K, staleness ratio, score distribution
  - **Context quality metrics:** relevance, diversity, freshness, failure type match rate, duplicate detection
  - **Generation impact metrics:** confidence delta, type alignment, grounding score, RAG value score
  - **Grading system:** Composite score → letter grade (A–F) with breakdown
- `evaluate_rag()` — Convenience function for one-shot evaluation

**Monitoring Dashboard (`monitoring/`)**
- `_build_dashboard.py` — Aceternity SaaS-style dashboard generator (Chart.js 4.4.4)
  - Pure black background, blue-cyan gradients, glassmorphism cards
  - Frosted navbar, animated hero section, full footer
  - Muted chart palette (#4a6fa5, #3d8b9e, #4a9e7a, #c9a84c, #b85c5c)
  - 6 consolidated sections: Pipeline, Quality, Triage, Policy, Timing, System
  - ES5-only JavaScript (no const/let/arrow functions)
- `dashboard-preview.html` — Generated output (35,786 bytes, 15/15 sanity checks pass)

**Tests**
- `tests/test_rag_metrics.py` — 21 tests: retrieval, context, generation, grading, edge cases

---

### 🆕 Step 10 — Verifier + Rollback

#### Added

**Step 10 — Fix Verification (`step10/`)**
- `verifier.py` — Verifies whether fix branch CI passed or failed after merge
  - Checks workflow_run conclusion via GitHub API
  - Only processes fix/* branches (ignores everything else)
  - Triggers rollback on CI failure via RollbackClient
  - Records verification metrics to Prometheus
- `rollback.py` — Creates revert PRs for failed auto-fixes
  - Anti-flapping: max 1 rollback per event (checked via S3 marker)
  - Rate limiting: max 3 rollbacks per repo per hour (configurable)
  - Creates descriptive revert PR with full context
  - Comments on original fix PR with rollback notification
  - Sends email notification on rollback
  - Full audit trail in S3
- `models.py` — `VerificationResult` and `RollbackResult` dataclasses

**Webhook Routing**
- `step1/webhook_handler.py` — Routes fix/* branch workflow_run events to Step 10
- `step1/models.py` — Added `message_type` and `conclusion` fields to SQSMessage
- `step1/models.py` — Added `is_completed_workflow()` method to GitHubWebhookPayload

**Worker Integration**
- `step2/worker.py` — Routes verification messages to `_handle_verification()`
- Stores verification results in S3 under `events/{slug}/{event_id}/verification.json`

**Tests**
- `tests/test_step10.py` — 15 tests: models, verify pass/fail, rollback, anti-flapping, rate limiting

---

### 🆕 Step 11 — Observability + Kill Switch

#### Added

**Step 11 — Prometheus Metrics (`step11/`)**
- `metrics.py` — Central Prometheus metrics registry + Pushgateway push
  - 7 Counters: events, policy decisions, quality checks, PRs, verifications, rollbacks, errors
  - 1 Histogram: pipeline step duration (with custom buckets)
  - 2 Gauges: triage confidence, kill switch state
  - Custom CollectorRegistry (avoids global state conflicts)
  - No-op fallback when prometheus_client is not installed
  - `push_metrics()` — Non-blocking push to Pushgateway (fire-and-forget)
- `killswitch.py` — Global kill switch via AWS SSM Parameter Store
  - `is_kill_switch_enabled()` — Reads SSM parameter /repomind/kill_switch
  - Fail-safe: if SSM unreachable → assume ON (halt pipeline)
  - 30-second TTL cache to avoid hammering SSM
  - Development mode bypass (always OFF in dev)
  - `@require_kill_switch_off` decorator for protecting side-effect functions
  - `clear_cache()` for test isolation

**Monitoring Infrastructure (`monitoring/`)**
- `docker-compose.yml` — Pushgateway + Prometheus + Grafana stack
- `prometheus.yml` — Prometheus config (scrapes Pushgateway every 15s)
- `provisioning/datasources/datasource.yml` — Auto-provisions Prometheus in Grafana

**Worker Integration**
- Kill switch check at pipeline start (before any processing)
- Metrics recording throughout pipeline (events, errors, policy, quality, PRs)
- Metrics push at pipeline end via `_finalize()`

**Configuration**
- `shared/config.py` — Added PUSHGATEWAY_URL, METRICS_ENABLED, KILL_SWITCH_PARAM, VERIFICATION_ENABLED, MAX_ROLLBACKS_PER_HOUR
- `requirements.txt` — Added prometheus-client==0.21.1
- `template.yaml` — Added SSM read permissions, PushgatewayUrl parameter, new env vars

**Tests**
- `tests/test_step11.py` — 14 tests: metrics registry, no-op fallback, push success/failure, kill switch on/off/fail-safe/cache, decorator

---

## [1.1.0-alpha] — 2026-02-26

### 🆕 Step 9 — Code Quality Gate

#### Added

**Step 9 — Code Quality Checker (`step9/`)**
- `code_checker.py` — Validates LLM-generated code changes before PR creation
  - Syntax check via `ast.parse()` (blocking: broken code → no PR)
  - Ruff lint check (blocking: undefined names, unused imports)
  - Black format check (non-blocking: warning only)
  - Mypy type check (non-blocking: warning only)
  - Writes files to temp dir, runs tools, cleans up
  - Fail-open on checker errors (don't block PR if checker itself crashes)

**Worker Integration**
- Step 9 runs after Policy (Step 7) and before PR Creation (Step 8)
- `PipelineContext` now includes `code_quality` field
- `artifacts.json` now includes `code_quality` section with full report

**CI/CD Pipeline**
- `.github/workflows/ci.yml` — GitHub Actions workflow: lint, format, typecheck, tests
- `pyproject.toml` — Unified config for ruff, black, mypy, pytest, coverage
- `requirements-dev.txt` — Development dependencies (ruff, black, mypy, coverage)
- `Makefile` — Quick commands: `make lint`, `make format`, `make test`, `make all`

**Tests**
- `test_step9.py` — 12 tests for CodeChecker: syntax validation, empty changes, mixed files, report structure, nested paths

---

## [1.0.0-alpha] — 2026-02-25

### 🎉 Initial Release — Alpha

#### Added

**Tooling**
- Adopted **uv** as the primary Python package & project manager (replaces pip/venv)
- Virtual environment creation via `uv venv --python 3.12`
- Dependency installation via `uv pip install -r requirements.txt`

**Shared Layer (`shared/`)**
- `config.py` — Centralized settings from environment variables with singleton pattern
- `event_id.py` — Deterministic event ID generation (`evt-<slug>-<run_id>-<timestamp>`)
- `logger.py` — Structured logging via structlog (JSON in prod, colored console in dev)
- `timeline.py` — Pipeline step timing and progress tracking
- `storage.py` — S3 (production) and local filesystem (development) storage abstraction
- `github_auth.py` — GitHub App JWT authentication with installation token caching
- `notifier.py` — Email (Gmail SMTP) and GitHub PR comment notifications

**Step 1 — Webhook Handler**
- `models.py` — Pydantic models for GitHub webhook payload
- `signature.py` — HMAC-SHA256 webhook signature validation
- `sqs_client.py` — SQS publisher with local development fallback
- `webhook_handler.py` — FastAPI app with `/webhook` and `/health` endpoints
- `lambda_handler.py` — Mangum adapter for AWS Lambda deployment

**Step 2 — Worker (Core Orchestrator)**
- `log_fetcher.py` — GitHub Actions log downloader with retry
- `sanitizer.py` — 10-pattern secret redaction engine
- `excerpt.py` — Heuristic CI log excerpt generator
- `worker.py` — Full pipeline orchestrator (Steps 2→8)

**Step 3 — Vector DB**
- `embedder.py` — sentence-transformers embedding (all-MiniLM-L6-v2, 384-dim)
- `indexer.py` — Qdrant vector upsert with S3 backup
- `retriever.py` — Similarity search with filters for RAG

**Step 4 — LangGraph Orchestration**
- `models.py` — PipelineState TypedDict for graph state
- `nodes.py` — Graph nodes: evidence, triage, planner, policy
- `graph.py` — StateGraph builder with sequential fallback

**Step 5 — Triage**
- `triage.py` — Groq LLM failure classifier with keyword fallback (10 failure types)

**Step 6 — Planner**
- `planner.py` — Groq LLM fix plan generator with template fallback

**Step 7 — Policy**
- `policy.py` — Rule-based YAML policy engine (deny-by-default, first-match-wins)

**Step 8 — PR Creator**
- `pr_creator.py` — GitHub branch + PR creation with code changes

**Infrastructure**
- `template.yaml` — AWS SAM template (API Gateway, Lambda, SQS, S3)
- `policy/default.yaml` — Default safety policy (7 rules)
- `repos.yaml` — Target repository configuration
- `.env.example` — Environment variable template
- `requirements.txt` — Python dependencies
- `run_local.py` — Local development server (Uvicorn)
- `test_local_pipeline.py` — Full pipeline simulation

**Tests**
- `test_signature.py` — 6 tests for webhook HMAC validation
- `test_event_id.py` — 7 tests for event ID generation
- `test_sanitizer.py` — 8 tests for log sanitization
- `test_excerpt.py` — 7 tests for excerpt generation
- `test_triage.py` — 8 tests for failure classification
- `test_policy.py` — 8 tests for policy evaluation
- `test_webhook.py` — 3 tests for HTTP endpoints
- `test_step3.py` — 6 tests for vector DB (mocked)
- `test_step4.py` — 8 tests for LangGraph (mocked)

**Documentation**
- Complete `projectdocs/` folder with 17 documents

---

## [Unreleased] — Planned

### Planned Features

- **Production Deployment** — SAM deploy to AWS, webhook URL configuration
- **End-to-End Testing** — Full pipeline test with real CI failure
- **Grafana Dashboards** — Import provisioned dashboards from monitoring/
- **Step 11** — Observability + Kill Switch (Prometheus, Redis kill switch)
- Custom playbook YAML support
- Multi-repo policy management
- Dashboard UI for monitoring
- Slack/Teams notification integration
- Webhook replay for debugging
