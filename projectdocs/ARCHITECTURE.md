# 🏗️ Architecture Document — RepoMind CI Auto-Fix Agent

## 1. Overview

RepoMind is an **automated CI failure remediation system** that detects failed GitHub Actions workflows, diagnoses the root cause using LLM-powered analysis, generates a fix plan, evaluates safety policies, and creates a pull request — all without human intervention.

---

## 2. Architecture Principles

| Principle | Description |
|-----------|-------------|
| **Event-Driven** | Triggered by GitHub webhooks; asynchronous SQS processing |
| **Serverless-First** | AWS Lambda for compute; no servers to manage |
| **Single Responsibility** | Each step is a separate module doing one thing well |
| **Fail-Safe** | Policy engine denies by default; conservative approach |
| **Observable** | Structured JSON logging, timeline tracking, artifact storage |

| **Cost-Zero** | Designed to run entirely on AWS Free Tier + Groq free LLM |

---

## 3. High-Level Architecture

```
┌────────────────┐     ┌───────────────────┐     ┌───────────────┐
│  GitHub Actions │────▶│  API Gateway      │────▶│  Step 1       │
│  (CI Failure)   │     │  (Webhook URL)    │     │  Webhook      │
└────────────────┘     └───────────────────┘     │  Handler      │
                                                   └──────┬────────┘
                                                          │
                                                          ▼
                                                   ┌──────────────┐
                                                   │  Amazon SQS  │
                                                   │  Event Queue │
                                                   └──────┬───────┘
                                                          │
                                                          ▼
     ┌───────────────────────────────────────────────────────────────────┐
     │                    Step 2: Worker (Orchestrator)                   │
     │                                                                   │
     │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
     │  │Log Fetch │─▶│Sanitize  │─▶│Excerpt   │─▶│  S3 Save │         │
     │  └──────────┘  └──────────┘  └──────────┘  └──────────┘         │
     │                                                                   │
     │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
     │  │Step 5    │─▶│Step 6    │─▶│Step 7    │─▶│Step 8    │         │
     │  │Triage    │  │Planner   │  │Policy    │  │PR Create │         │
     │  └──────────┘  └──────────┘  └──────────┘  └──────────┘         │
     │                                                                   │
     │  ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
     │  │Step 3    │  │Artifacts │  │Timeline  │                       │
     │  │Indexer   │  │Save      │  │Save      │                       │
     │  └──────────┘  └──────────┘  └──────────┘                       │
     └───────────────────────────────────────────────────────────────────┘
                        │                    │
                        ▼                    ▼
                 ┌──────────────┐    ┌──────────────┐
                 │  Amazon S3   │    │  Qdrant      │
                 │  (Artifacts) │    │  (Vectors)   │
                 └──────────────┘    └──────────────┘
```

---

## 4. Component Architecture

### 4.1 Shared Layer (`shared/`)
The foundation layer providing cross-cutting concerns:

- **`config.py`** — Centralized settings from environment variables (singleton pattern)
- **`event_id.py`** — Deterministic event ID generation (`evt-<slug>-<run_id>-<timestamp>`)
- **`logger.py`** — Structured JSON logging via structlog
- **`timeline.py`** — Pipeline step timing and progress tracking
- **`storage.py`** — S3 (production) / local filesystem (dev) abstraction
- **`github_auth.py`** — GitHub App JWT auth with token caching
- **`notifier.py`** — Email (Gmail SMTP) + GitHub PR comment notifications

### 4.2 Step 1 — Webhook Handler (`step1/`)
**Purpose:** Receive GitHub webhook, validate, queue event.  
**Deployment:** API Gateway → Lambda  
**Key Design:** Extremely lightweight — no heavy processing, no S3 writes, no LLM calls.

### 4.3 Step 2 — Worker (`step2/`)
**Purpose:** Core orchestrator — runs the entire fix pipeline.  
**Deployment:** SQS-triggered Lambda  
**Key Design:** Only module that knows the full pipeline. Each sub-step is a separate module.

### 4.4 Step 3 — Vector DB (`step3/`)
**Purpose:** Embed event data and store/retrieve from Qdrant for RAG.  
**Components:** Embedder (sentence-transformers), Indexer (upsert), Retriever (search)

### 4.5 Step 4 — LangGraph Orchestration (`step4/`)
**Purpose:** Graph-based orchestration of Steps 3→5→6→7 with state management.  
**Key Design:** Sequential fallback if LangGraph fails.

### 4.6 Step 5 — Triage (`step5/`)
**Purpose:** Classify CI failure type using LLM (Groq) with keyword fallback.

### 4.7 Step 6 — Planner (`step6/`)
**Purpose:** Generate fix plan with playbook ID, actions, code changes.

### 4.8 Step 7 — Policy (`step7/`)
**Purpose:** Rule-based safety evaluation — first-matching-rule wins, deny by default.

### 4.9 Step 8 — PR Creator (`step8/`)
**Purpose:** Create GitHub branch, apply code changes, open pull request.

### 4.10 Step 9 — Code Quality Gate (`step9/`)
**Purpose:** Validate LLM-generated code changes before PR creation.  
**Tools:** `ast.parse` (syntax check), `ruff` (linting), `black` (formatting), `mypy` (type checking).  
**Severity:** Syntax + Ruff are **blocking** (fail = no PR). Black + Mypy are **warnings** only.  
**Design:** Fail-open — if the checker itself crashes, it does not block the PR.

### 4.11 Step 10 — Verifier + Rollback (`step10/`)
**Purpose:** Verify whether a fix branch CI passed after merge. Trigger rollback if CI failed.  
**Trigger:** `workflow_run.completed` webhook on `fix/*` branches, routed by Step 1.  
**Components:**
- `verifier.py` — Checks CI conclusion (pass/fail), triggers rollback on failure
- `rollback.py` — Creates revert PR via PyGithub with anti-flapping + rate limiting
- `models.py` — `VerificationResult` and `RollbackResult` dataclasses  

**Safety Guards:** Anti-flapping (max 1 rollback per event), rate limiting (3/hour/repo), kill switch check, audit trail in S3.

### 4.12 Step 11 — Observability + Kill Switch (`step11/`)
**Purpose:** Prometheus metrics via Pushgateway + global kill switch via AWS SSM.  
**Components:**
- `metrics.py` — Counters (events, PRs, rollbacks, errors), Histogram (step duration), Gauges (confidence, kill switch)
- `killswitch.py` — SSM-backed kill switch with fail-safe default (ON if unreachable), TTL cache, decorator  

**Infrastructure:** Pushgateway + Prometheus + Grafana via docker-compose on EC2 (or local).  
**Design:** Metrics are non-fatal (no-op if Pushgateway is down). Kill switch is fail-safe (halts if SSM is unreachable).

---

## 5. Data Architecture

### 5.1 S3 Storage Structure
```
events/
  <repo-slug>/
    <event-id>/
      logs/
        full_logs.txt       ← Raw CI logs (30-day retention)
        excerpt.txt         ← Heuristic excerpt (90-day retention)
      artifacts.json        ← Triage + Plan + Policy + PR (180-day retention)
      timeline.json         ← Step-by-step execution log (180-day retention)

embeddings/
  <repo-slug>/
    <event-id>/
      excerpt_embedding.json
      triage_embedding.json
      plan_embedding.json
      verification_embedding.json
```

### 5.2 Event ID Format
```
evt-<repo-slug>-<workflow-run-id>-<timestamp>
Example: evt-myorg-service-a-123456789-20260213T154400Z
```
Properties: globally unique, lexicographically sortable, human-readable, debug-friendly.

---

## 6. Communication Patterns

| From | To | Protocol | Format |
|------|----|----------|--------|
| GitHub | Step 1 | HTTPS POST | Webhook payload (JSON) |
| Step 1 | Step 2 | SQS Message | `SQSMessage` (JSON) |
| Step 2 | GitHub | HTTPS (httpx) | GitHub REST API |
| Step 2 | S3 | boto3 | JSON / Text artifacts |
| Step 2 | Qdrant | HTTP | Vector upserts/queries |
| Step 2 | Groq | HTTPS | LLM chat completion |
| Step 2 | Pushgateway | HTTP POST | Prometheus metrics |
| Step 2 | SSM | boto3 | Kill switch parameter read |
| Step 10 | GitHub | HTTPS (PyGithub) | Revert PR creation |

---

## 7. Error Handling Strategy

| Level | Strategy |
|-------|----------|
| **Network** | Exponential backoff retry (1s → 2s → 4s → 8s → 16s, max 5 retries) via tenacity |
| **LLM** | Fallback to keyword heuristic if Groq fails |
| **Policy** | Fail-closed: if policy engine errors, decision = deny |
| **Code Quality** | Fail-open: if checker crashes, pipeline continues (does not block PR) |
| **Verification** | Non-fatal: if verification fails, error logged but no cascading failure |
| **Rollback** | Anti-flapping (1 per event), rate limiting (3/hour/repo), kill switch check |
| **Kill Switch** | Fail-safe: if SSM unreachable, assume ON (halt pipeline) |
| **Metrics** | Non-fatal: if Pushgateway is down, log warning and continue |
| **Pipeline** | Partial artifacts saved on failure; error recorded in timeline |
| **Queue** | SQS DLQ after 3 failed processing attempts |

---

## 8. Security Architecture

- **Webhook Validation:** HMAC-SHA256 signature verification with constant-time comparison
- **Log Sanitization:** 10 regex patterns redact AWS keys, tokens, passwords, PII
- **GitHub Auth:** GitHub App JWT (short-lived) with installation token caching
- **Secrets:** Never stored in code; loaded from environment variables / AWS SSM
- **Policy Engine:** Conservative deny-by-default; only explicitly allowed fixes proceed

---

## 9. Deployment Architecture

- **Infrastructure-as-Code:** AWS SAM (`template.yaml`)
- **Compute:** AWS Lambda (Python 3.12, x86_64)
- **API:** Amazon API Gateway (REST)
- **Queue:** Amazon SQS with Dead Letter Queue
- **Storage:** Amazon S3 with lifecycle policies
- **Vector DB:** Qdrant Cloud (free tier) or self-hosted on EC2

---

## 10. Design Decisions

| Decision | Rationale |
|----------|-----------|
| SQS over Kafka | Simpler, serverless, free tier, sufficient for event volumes |
| Groq over OpenAI | Free/low-cost, fast inference, open-source models |
| sentence-transformers over API embeddings | Local execution, no API cost, 384-dim sufficient |
| First-matching-rule policy | Predictable evaluation order, easy to debug |
| Sequential fallback for LangGraph | Reliability over orchestration elegance |
| S3 over DynamoDB for artifacts | Better for large JSON blobs, lifecycle policies, lower cost |
