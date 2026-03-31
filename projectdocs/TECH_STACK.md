# 🔧 Tech Stack Document — RepoMind CI Auto-Fix Agent

## 1. Overview

RepoMind is built on a **100% free-tier** stack using Python, AWS Free Tier, Groq (free LLM), and open-source tools. No paid services are required for development or initial production deployment.

---

## 2. Core Language & Tooling

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Python** | 3.12+ | Primary language for all components |
| **uv** | Latest | Ultra-fast Python package & project manager (replaces pip/venv) |

> **Why uv?** Written in Rust, 10–100x faster than pip. Handles virtual environments, dependency resolution, and package installation in a single tool. See [docs.astral.sh/uv](https://docs.astral.sh/uv/).

---

## 3. Web & API Framework

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.115.12 | REST API framework for webhook handler |
| `uvicorn` | 0.34.2 | ASGI server for local development |
| `mangum` | 0.19.0 | FastAPI → AWS Lambda adapter |
| `pydantic` | 2.11.3 | Data validation, serialization, type safety |

---

## 4. AWS Services (Free Tier)

| Service | Purpose | Free Tier Limit |
|---------|---------|-----------------|
| **API Gateway** | Webhook ingress endpoint | 1M API calls/month |
| **AWS Lambda** | Compute (webhook + worker) | 1M requests + 400K GB-sec/month |
| **Amazon SQS** | Event message queue + DLQ | 1M requests/month |
| **Amazon S3** | Artifact & log storage | 5 GB storage |
| **CloudWatch** | Logging & monitoring | 5 GB log data/month |
| **SSM Parameter Store** | Kill switch state (Standard tier) | Free (standard params) |

---

## 5. GitHub Integration

| Package | Version | Purpose |
|---------|---------|---------|
| `PyGithub` | 2.6.0 | GitHub REST API client (repos, PRs, files) |
| `PyJWT` | 2.10.1 | JWT generation for GitHub App auth |
| `cryptography` | 44.0.3 | RSA key handling for JWT signing |

**GitHub Services Used:**

- GitHub App (free) — authentication
- GitHub Actions — CI trigger source
- GitHub API — log downloads, PR creation

---

## 6. HTTP & Resilience

| Package | Version | Purpose |
|---------|---------|---------|
| `httpx` | 0.28.1 | Async/sync HTTP client for API calls |
| `tenacity` | 9.1.2 | Retry with exponential backoff |

---

## 7. LLM & AI

| Service/Package | Version | Purpose |
|----------------|---------|---------|
| `groq` | 0.25.0 | Groq Python SDK for LLM inference |
| **Groq Cloud** | Free tier | LLM API (openai/gpt-oss-120b) |

**LLM Usage:**

- Step 5 (Triage): Failure classification (JSON mode, temp=0.1)
- Step 6 (Planner): Fix plan generation (JSON mode, temp=0.2)

---

## 8. Embeddings & Vector Search

| Package | Version | Purpose |
|---------|---------|---------|
| `sentence-transformers` | 4.1.0 | Local embedding model |
| `qdrant-client` | 1.14.2 | Vector database client |

**Model:** `all-MiniLM-L6-v2` — 384 dimensions, runs locally, free  
**Vector DB:** Qdrant Cloud Free Tier or self-hosted on EC2 t2.micro

---

## 9. Pipeline Orchestration

| Package | Version | Purpose |
|---------|---------|---------|
| `langgraph` | 0.2.60 | Directed graph workflow orchestration |

**Graph Flow:** evidence → triage → planner → policy  
**Fallback:** Sequential execution if LangGraph fails

---

## 10. Configuration & Utilities

| Package | Version | Purpose |
|---------|---------|---------|
| `python-dotenv` | 1.1.0 | Load .env files for local development |
| `pyyaml` | 6.0.2 | Parse policy & config YAML files |
| `boto3` | 1.38.24 | AWS SDK for Python (S3, SQS) |

---

## 11. Logging & Observability

| Package | Version | Purpose |
|---------|---------|---------|
| `structlog` | 25.1.0 | Structured JSON logging |

**Production:** JSON output for CloudWatch parsing  
**Development:** Colored console output for readability

---

## 12. Testing

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | 8.3.5 | Test framework |
| `pytest-asyncio` | 0.26.0 | Async test support |
| `pytest-cov` | 6.1.1 | Test coverage reporting |

---

## 13. Infrastructure-as-Code

| Technology | Purpose |
|-----------|---------|
| **AWS SAM** | Serverless Application Model — `template.yaml` |
| **CloudFormation** | Underlying IaC engine |

---

## 14. Code Quality Gate (Step 9)

| Package | Version | Purpose |
|---------|---------|---------|
| `ruff` | 0.8.6 | Ultra-fast Python linter (blocking check) |
| `black` | 24.10.0 | Python code formatter (warning check) |
| `mypy` | 1.14.1 | Static type checker (warning check) |
| `coverage[toml]` | 7.6.10 | Code coverage measurement |

**Built-in:** `ast.parse` (Python stdlib) — syntax validation (blocking check)  
**Config:** `pyproject.toml` — unified configuration for all tools  
**CI:** `.github/workflows/ci.yml` — GitHub Actions pipeline

---

## 15. Verification & Rollback (Step 10)

| Package | Version | Purpose |
|---------|---------|---------|
| `PyGithub` | 2.6.0 | Revert PR creation via GitHub API |
| `boto3` | 1.38.24 | S3 rollback markers + rate limiting counters |

**Anti-Flapping:** S3 marker prevents rolling back the same event twice  
**Rate Limiting:** Max N rollbacks per hour (configurable via `MAX_ROLLBACKS_PER_HOUR`)  
**Audit:** Rollback records stored in S3 for post-mortem analysis

---

## 16. Observability & Kill Switch (Step 11)

| Package | Version | Purpose |
|---------|---------|---------|
| `prometheus-client` | 0.21.1 | Prometheus metrics (Counters, Histograms, Gauges) |

**Metrics Published:**

- `repomind_events_total` — Webhook events received
- `repomind_pipeline_duration_seconds` — End-to-end latency histogram
- `repomind_prs_created_total` — PRs opened
- `repomind_verification_total` — CI verification outcomes
- `repomind_rollbacks_total` — Rollbacks triggered
- `repomind_errors_total` — Errors by step

**Kill Switch:** AWS SSM Parameter Store (`/repomind/kill_switch`)  
**Push Model:** Metrics pushed to Pushgateway at pipeline end (Lambda-compatible)  
**Fail-Safe:** SSM unreachable → assume kill switch ON (halt pipeline)  
**Cache:** 30-second TTL to minimize SSM API calls

---

## 17. Monitoring Infrastructure

| Technology | Purpose |
|-----------|---------|
| **Prometheus Pushgateway** | Receives metrics pushed from Lambda |
| **Prometheus** | Scrapes Pushgateway, stores time-series data |
| **Grafana** | Dashboard UI for metrics visualization |
| **Docker Compose** | Local/EC2 deployment of monitoring stack |

**Ports:** Pushgateway :9091 · Prometheus :9090 · Grafana :3000

---

## 18. Cost Summary

```
┌─────────────────────────────────────────┐
│         TOTAL MONTHLY COST: $0          │
├─────────────────────────────────────────┤
│ AWS Free Tier:     $0                   │
│ Groq LLM:         $0 (free tier)       │
│ Qdrant Cloud:     $0 (free tier)       │
│ GitHub:           $0 (free)            │
│ sentence-transformers: $0 (local)      │
│ All Python packages: $0 (open source)  │
└─────────────────────────────────────────┘
```
