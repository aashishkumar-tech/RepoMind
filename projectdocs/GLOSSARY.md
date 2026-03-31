# 📖 Glossary — RepoMind CI Auto-Fix Agent

## Core Concepts

| Term | Definition |
|------|-----------|
| **CI (Continuous Integration)** | Automated process of building, testing, and validating code changes on every commit/push. |
| **CD (Continuous Deployment)** | Automated process of deploying validated code to production environments. |
| **CI/CD Pipeline** | The complete automated workflow from code commit to production deployment. |
| **Auto-Fix** | Automatically generating and applying code fixes for CI failures without human intervention. |
| **Pipeline** | The sequential processing chain in RepoMind: webhook → worker → triage → plan → policy → PR. |

---

## RepoMind-Specific Terms

| Term | Definition |
|------|-----------|
| **Event** | A single CI failure occurrence, identified by a unique `event_id`. |
| **Event ID** | Unique identifier: `evt-<repo-slug>-<run-id>-<timestamp>`. Example: `evt-myorg-service-a-123456789-20260213T154400Z` |
| **Repo Slug** | Normalized repository identifier: `owner/repo` → `owner-repo` (lowercase, no special chars). |
| **Excerpt** | Condensed version of CI logs containing only error-relevant lines (typically 50–200 lines). |
| **Triage** | The process of classifying a CI failure into a known category (e.g., dependency_error, import_error). |
| **Playbook** | A predefined set of fix actions for a specific failure type (YAML format). |
| **Plan** | The generated fix strategy including playbook ID, actions, code changes, and risk level. |
| **Policy** | Safety rules that determine whether an auto-fix is allowed (YAML-based, deny-by-default). |
| **Artifacts** | Structured JSON data recording the outcome of each pipeline step (stored in S3). |
| **Timeline** | Chronological log of all pipeline steps with timestamps and durations (stored in S3). |
| **Verification** | The process of checking the CI re-run result on a fix/* branch to confirm the auto-fix worked. |
| **Rollback** | Automatically reverting a failed fix by creating a revert PR that restores the original code. |
| **Anti-Flapping** | Safety mechanism preventing the same event from being rolled back multiple times (S3 marker check). |
| **Rate Limiting** | Restricting the number of rollbacks per hour to prevent cascading automated reverts. |
| **Kill Switch** | Emergency mechanism to instantly halt all auto-fix operations, stored in AWS SSM Parameter Store. |
| **Pushgateway** | Prometheus component that accepts metrics pushed from short-lived jobs (Lambda functions). |

---

## Architecture Terms

| Term | Definition |
|------|-----------|
| **uv** | Ultra-fast Python package and project manager written in Rust by Astral. Replaces pip, pip-tools, virtualenv in a single tool. 10–100x faster than pip. |
| **Webhook** | HTTP callback — GitHub sends a POST request to our endpoint when a CI event occurs. |
| **HMAC-SHA256** | Hash-based Message Authentication Code using SHA-256. Used to verify webhook authenticity. |
| **SQS (Simple Queue Service)** | AWS managed message queue. Decouples webhook reception from processing. |
| **DLQ (Dead Letter Queue)** | Secondary queue for messages that fail processing after max retries. |
| **Lambda** | AWS serverless compute service. Runs code without managing servers. |
| **API Gateway** | AWS service that creates, publishes, and manages REST APIs. |
| **SAM (Serverless Application Model)** | AWS framework for building serverless applications using CloudFormation templates. |
| **SSM (Systems Manager) Parameter Store** | AWS service for storing configuration data and secrets. Used for kill switch state. Free for standard parameters. |
| **Mangum** | Python adapter that translates AWS Lambda events into ASGI requests for FastAPI. |

---

## AI / ML Terms

| Term | Definition |
|------|-----------|
| **LLM (Large Language Model)** | AI model trained on text data, used for classification and text generation. RepoMind uses Groq's Llama 3.1. |
| **Groq** | AI inference platform providing free-tier access to open-source LLMs (Llama, Mixtral). |
| **RAG (Retrieval-Augmented Generation)** | Technique combining vector search (retrieval) with LLM generation for context-aware responses. |
| **Embedding** | Dense numerical vector representation of text, used for similarity search. RepoMind uses 384-dimensional vectors. |
| **Vector DB** | Database optimized for storing and searching high-dimensional vectors. RepoMind uses Qdrant. |
| **Qdrant** | Open-source vector similarity search engine used for storing and querying event embeddings. |
| **sentence-transformers** | Python library for generating text embeddings. Model: `all-MiniLM-L6-v2`. |
| **Temperature** | LLM parameter controlling randomness (0.0 = deterministic, 1.0 = creative). Triage uses 0.1, Planner uses 0.2. |
| **JSON Mode** | LLM output mode that guarantees valid JSON responses. |
| **Confidence Score** | Float 0.0–1.0 indicating how certain the triage classification is. |

---

## Monitoring & Observability Terms

| Term | Definition |
|------|-----------|
| **Prometheus** | Open-source time-series monitoring system that scrapes and stores metrics. |
| **Grafana** | Open-source visualization platform for creating dashboards from Prometheus data. |
| **Counter** | Prometheus metric that only goes up (e.g., total events, total errors). |
| **Histogram** | Prometheus metric that samples observations into configurable buckets (e.g., latency distribution). |
| **Gauge** | Prometheus metric that can go up and down (e.g., confidence score, kill switch state). |
| **Pushgateway** | Prometheus component that accepts metrics pushed from short-lived jobs like Lambda functions. |
| **Fail-Safe** | Design principle where system failure defaults to the safest state (kill switch ON = halt). |
| **TTL (Time-to-Live)** | Duration a cached value remains valid before re-fetching (kill switch uses 30s TTL). |

---

## Pipeline Terms

| Term | Definition |
|------|-----------|
| **Step 1 (Webhook Handler)** | Receives GitHub webhook, validates signature, queues event to SQS. |
| **Step 2 (Worker)** | Core orchestrator — runs the entire pipeline from log fetch to PR creation. |
| **Step 3 (Vector DB)** | Embeds event data and stores/retrieves from Qdrant for RAG. |
| **Step 4 (LangGraph)** | Directed graph orchestration of Steps 3→5→6→7. |
| **Step 5 (Triage)** | Classifies the CI failure type using LLM or keyword heuristic. |
| **Step 6 (Planner)** | Generates a fix plan with actions and code changes. |
| **Step 7 (Policy)** | Evaluates safety rules to approve or deny the auto-fix. |
| **Step 8 (PR Creator)** | Creates a GitHub branch and pull request with the fix. |
| **Step 9 (Code Quality Gate)** | Validates LLM-generated code with syntax, ruff, black, and mypy checks before PR creation. |
| **Step 10 (Verifier + Rollback)** | Verifies CI result on fix/* branches; automatically reverts failed fixes with anti-flapping and rate limiting. |
| **Step 11 (Observability + Kill Switch)** | Prometheus metrics collection via Pushgateway, plus SSM-backed emergency kill switch with fail-safe behavior. |

---

## Failure Types

| Type | Description | Example Error |
|------|-------------|---------------|
| `dependency_error` | Missing or incompatible package | `Cannot find module 'lodash'` |
| `import_error` | Module import failure | `ModuleNotFoundError: No module named 'foo'` |
| `syntax_error` | Code syntax issues | `SyntaxError: invalid syntax` |
| `test_failure` | Test assertions failing | `FAILED tests/test_foo.py::test_bar` |
| `type_error` | Type mismatch | `TypeError: expected str, got int` |
| `configuration_error` | Config file issues | `Config file not found` |
| `build_error` | Build process failure | `Build failed with exit code 1` |
| `lint_error` | Linting violations | `Linting errors found` |
| `runtime_error` | Runtime exceptions | `RuntimeError: out of memory` |
| `unknown` | Unclassifiable failure | Catch-all category |

---

## Policy Terms

| Term | Definition |
|------|-----------|
| **Decision** | The policy outcome: `allow` (proceed), `deny` (block), or `manual_review` (human needed). |
| **Risk Level** | `low`, `medium`, or `high` — assessed by the Planner based on fix impact. |
| **First-Match-Wins** | Policy evaluation strategy — rules checked in order, first matching rule determines the decision. |
| **Fail-Closed** | Safety principle — if the policy engine errors, the decision defaults to `deny`. |
| **Fail-Open** | Resilience principle — if the code quality checker crashes, pipeline continues without blocking PR. |
| **Blocking Check** | A code quality check (syntax, ruff) whose failure prevents PR creation. |
| **Warning Check** | A code quality check (black, mypy) whose failure is logged but does not prevent PR creation. |
| **Deny-by-Default** | Default behavior — if no rule matches, the fix is denied (safety-first approach). |

---

## Security Terms

| Term | Definition |
|------|-----------|
| **Sanitization** | Process of removing/redacting sensitive data (passwords, tokens, keys) from text. |
| **Constant-Time Comparison** | `hmac.compare_digest()` — prevents timing attacks by always comparing full strings. |
| **GitHub App** | A first-class GitHub integration with granular permissions, preferred over personal tokens. |
| **Installation Token** | Short-lived OAuth token (~1 hour) generated from GitHub App JWT. |
| **JWT (JSON Web Token)** | Compact token format used for GitHub App authentication (RS256 signed). |
| **NoEcho** | CloudFormation parameter flag that masks secret values in the console. |

---

## Acronyms

| Acronym | Full Form |
|---------|-----------|
| **API** | Application Programming Interface |
| **ASGI** | Asynchronous Server Gateway Interface |
| **AWS** | Amazon Web Services |
| **CI** | Continuous Integration |
| **CD** | Continuous Deployment |
| **CLI** | Command Line Interface |
| **DLQ** | Dead Letter Queue |
| **HLD** | High-Level Design |
| **HMAC** | Hash-based Message Authentication Code |
| **HTTP** | HyperText Transfer Protocol |
| **IaC** | Infrastructure as Code |
| **JWT** | JSON Web Token |
| **LLD** | Low-Level Design |
| **LLM** | Large Language Model |
| **PR** | Pull Request |
| **RAG** | Retrieval-Augmented Generation |
| **REST** | Representational State Transfer |
| **S3** | Simple Storage Service |
| **SAM** | Serverless Application Model |
| **SDK** | Software Development Kit |
| **SMTP** | Simple Mail Transfer Protocol |
| **SQS** | Simple Queue Service |
| **SSM** | Systems Manager (AWS) |
| **TLS** | Transport Layer Security |
| **TTL** | Time-to-Live |
| **VPC** | Virtual Private Cloud |
