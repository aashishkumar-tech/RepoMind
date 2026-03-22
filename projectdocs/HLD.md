# 📐 High-Level Design (HLD) — RepoMind CI Auto-Fix Agent

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | RepoMind CI Auto-Fix Agent |
| **Version** | 1.0.0-alpha |
| **Author** | RepoMind Team |
| **Date** | February 2026 |
| **Status** | Implementation Phase |

---

## 2. System Overview

RepoMind is a **serverless, event-driven pipeline** that automatically detects, diagnoses, and fixes CI/CD failures in GitHub repositories. The system uses LLM-powered analysis (Groq) for intelligent failure classification and fix generation, combined with a rule-based policy engine for safety.

### 2.1 Goals

- **Zero human intervention** for low-risk, high-confidence CI failures
- **Sub-5-minute** response time from failure detection to PR creation
- **Zero cost** — runs entirely on AWS Free Tier + Groq free LLM tier
- **Fail-safe** — deny by default, conservative policy enforcement

### 2.2 Non-Goals (Phase 1)

- Multi-cloud support (AWS only)
- Real-time monitoring dashboard
- Custom LLM fine-tuning
- Multi-language playbook execution

---

## 3. Major Components

### 3.1 Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      EXTERNAL                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ GitHub       │  │ Groq         │  │ Qdrant       │  │
│  │ (Repos/API)  │  │ (LLM API)   │  │ (Vector DB)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└─────────┼──────────────────┼──────────────────┼──────────┘
          │                  │                  │
┌─────────┼──────────────────┼──────────────────┼──────────┐
│         │        AWS CLOUD │                  │          │
│  ┌──────▼───────┐  ┌──────┴───────┐  ┌──────▼───────┐  │
│  │ API Gateway  │  │ Lambda       │  │ S3           │  │
│  │ (Ingress)    │  │ (Compute)    │  │ (Storage)    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  │
│         │                  │                             │
│  ┌──────▼───────┐  ┌──────▼───────┐                     │
│  │ SQS Queue    │  │ CloudWatch   │                     │
│  │ (Messaging)  │  │ (Logs)       │                     │
│  └──────────────┘  └──────────────┘                     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility | Technology |
|-----------|---------------|------------|
| **Webhook Handler** | Receive & validate GitHub events | FastAPI + Mangum on Lambda |
| **Message Queue** | Decouple webhook from processing | Amazon SQS + DLQ |
| **Worker** | Orchestrate entire fix pipeline | Lambda (SQS-triggered) |
| **Log Fetcher** | Download GitHub Actions logs | httpx + tenacity |
| **Sanitizer** | Redact secrets from logs | regex patterns |
| **Excerpt Generator** | Extract relevant log sections | Heuristic + LLM |
| **Triage Engine** | Classify failure type | Groq LLM + keyword fallback |
| **Planner** | Generate fix plan | Groq LLM + template fallback |
| **Policy Engine** | Approve/deny auto-fix | Rule-based YAML evaluation |
| **Code Quality Gate** | Validate generated code before PR | ast + ruff + black + mypy |
| **Verifier** | Check CI result on fix/* branches | PyGithub API |
| **Rollback Client** | Revert failed fix PRs automatically | PyGithub + S3 markers |
| **Metrics Registry** | Collect pipeline metrics (counters, histograms) | prometheus-client + Pushgateway |
| **Kill Switch** | Emergency halt of all auto-fix operations | AWS SSM Parameter Store |
| **PR Creator** | Create fix branch + PR | PyGithub API |
| **Vector Indexer** | Embed & store for RAG | sentence-transformers + Qdrant |
| **Graph Orchestrator** | Coordinate analysis steps | LangGraph |
| **Storage** | Persist artifacts & logs | S3 (prod) / local filesystem (dev) |

---

## 4. Data Flow

### 4.1 Primary Pipeline Flow

```
 ① GitHub CI Fails
       │
       ▼
 ② Webhook received (Step 1)
       │ Validate HMAC signature
       │ Parse payload
       │ Generate event_id
       ▼
 ③ Message queued to SQS
       │
       ▼
 ④ Worker triggered (Step 2)
       │
       ├──▶ ⑤ Fetch CI logs from GitHub API
       ├──▶ ⑥ Sanitize logs (redact secrets)
       ├──▶ ⑦ Generate excerpt (key error lines)
       ├──▶ ⑧ Store logs + excerpt in S3
       │
       ├──▶ ⑨ Triage: classify failure type (Step 5)
       │       Input: excerpt
       │       Output: failure_type, confidence, summary
       │
       ├──▶ ⑩ Plan: generate fix actions (Step 6)
       │       Input: triage + excerpt
       │       Output: playbook_id, actions, code_changes
       │
       ├──▶ ⑪ Policy: evaluate safety (Step 7)
       │       Input: triage + plan
       │       Output: allow / deny + reason
       │
       ├──▶ ⑪.5 Code Quality Gate (Step 9)
       │       Input: code_changes from plan
       │       Output: pass/fail + check details
       │       Blocking: syntax + ruff failures prevent PR
       │
       ├──▶ ⑫ PR: create fix pull request (Step 8)
       │       Input: plan + policy (if allowed)
       │       Output: PR URL, branch, commit SHA
       │
       ├──▶ ⑬ Index: embed & store vectors (Step 3)
       │       Input: excerpt, triage, plan
       │       Output: Qdrant vectors + S3 backup
       │
       ├──▶ ⑭ Save artifacts.json to S3
       ├──▶ ⑮ Save timeline.json to S3
       ├──▶ ⑯ Push metrics to Pushgateway (Step 11)
       └──▶ ⑰ Send notification (email / PR comment)

 ⑱ Fix PR triggers CI re-run on fix/* branch
       │
       ▼
 ⑲ GitHub sends workflow_run.completed webhook
       │
       ▼
 ⑳ Worker routes to Verification (Step 10)
       │
       ├──▶ CI passed → status = "verified" ✅
       │
       └──▶ CI failed → Rollback triggered
               │ Anti-flapping check (S3 marker)
               │ Rate limit check (max/hour)
               ▼
              Create revert PR, notify, audit
```

### 4.2 Data Contracts Between Steps

| Source | Target | Data | Format |
|--------|--------|------|--------|
| GitHub | Step 1 | `workflow_run` event | JSON webhook payload |
| Step 1 | SQS | `event_id, repo, run_id, run_url, timestamp` | JSON |
| Step 2 | Step 5 | `excerpt` text | String |
| Step 5 | Step 6 | `failure_type, confidence, summary` | Dict |
| Step 6 | Step 7 | `playbook_id, actions, risk_level, confidence` | Dict |
| Step 6 | Step 9 | `code_changes` list | List[Dict] |
| Step 9 | Step 8 | `quality report (pass/fail, checks)` | Dict |
| Step 7 | Step 8 | `decision (allow/deny), reason` | Dict |
| Step 8 | S3 | `pr_url, branch, commit_sha` | Dict |
| Step 8 | Step 10 | `fix/* branch triggers CI re-run` | GitHub webhook |
| Step 10 | S3 | `rollback marker, audit record` | JSON |
| Step 10 | GitHub | `revert PR (if CI failed)` | PyGithub API |
| Step 11 | Pushgateway | `counters, histogram, gauges` | Prometheus exposition |
| Step 11 | SSM | `kill switch state read` | boto3 SSM API |

---

## 5. Deployment Topology

### 5.1 Production (AWS)

```
Region: ap-south-1 (Mumbai) — configurable

┌─ API Gateway ─────────────────┐
│  POST /webhook                │
│  GET  /health                 │
└──────────┬────────────────────┘
           ▼
┌─ Lambda: repomind-webhook ────┐
│  Memory: 256 MB               │
│  Timeout: 30s                 │
│  Runtime: Python 3.12         │
└──────────┬────────────────────┘
           ▼
┌─ SQS: repomind-events ───────┐
│  Visibility: 360s             │
│  Retention: 24h               │
│  DLQ: max 3 receives         │
└──────────┬────────────────────┘
           ▼
┌─ Lambda: repomind-worker ─────┐
│  Memory: 1024 MB              │
│  Timeout: 300s                │
│  Runtime: Python 3.12         │
│  Batch Size: 1                │
└───────────────────────────────┘
```

### 5.2 Development (Local)

```
┌─ Uvicorn (localhost:8080) ────┐
│  FastAPI app                  │
│  Local filesystem storage     │
│  In-memory queue              │
│  Swagger UI at /docs          │
└───────────────────────────────┘
```

---

## 6. Scalability Considerations

| Concern | Strategy |
|---------|----------|
| **Concurrent failures** | SQS handles queuing; Lambda auto-scales |
| **Large logs** | Heuristic excerpt reduces to ~200-300 lines |
| **LLM rate limits** | Tenacity retry with exponential backoff |
| **S3 growth** | Lifecycle policies: 30d logs, 180d artifacts |
| **Vector DB growth** | Qdrant handles millions of vectors; optional cleanup |

---

## 7. Availability & Reliability

| Feature | Mechanism |
|---------|-----------|
| **Retry on failure** | SQS retry (max 3) → DLQ |
| **Network resilience** | Tenacity exponential backoff on HTTP calls |
| **Partial failure** | Worker saves partial artifacts even on error |
| **Monitoring** | CloudWatch Logs + Prometheus + Grafana dashboards |
| **LLM unavailability** | Keyword heuristic fallback for triage |
| **Kill switch** | SSM parameter instantly halts all auto-fix operations |
| **Rollback safety** | Anti-flapping + rate limiting prevent cascading reverts |

---

## 8. Integration Points

| System | Integration Method | Purpose |
|--------|--------------------|---------|
| **GitHub** | Webhook (inbound) + REST API (outbound) | Event source + PR creation |
| **Groq** | REST API (outbound) | LLM inference for triage & planning |
| **Qdrant** | HTTP API (outbound) | Vector storage & similarity search |
| **AWS S3** | boto3 SDK | Artifact & log storage |
| **AWS SQS** | boto3 SDK | Event queuing |
| **AWS SSM** | boto3 SDK | Kill switch parameter read |
| **Gmail** | SMTP | Email notifications |
| **Prometheus Pushgateway** | HTTP push | Metrics collection from Lambda |
| **Prometheus** | HTTP scrape | Time-series storage |
| **Grafana** | HTTP UI | Metrics dashboards |
