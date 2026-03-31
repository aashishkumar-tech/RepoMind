# 📁 Repository Structure — RepoMind CI Auto-Fix Agent

## Complete File Tree

```
RepoMind/
│
├── .env.example              # Environment variable template
├── .gitignore                # Git ignore rules
├── Makefile                  # Quick commands (make lint, test, format, all)
├── pyproject.toml            # Unified config (ruff, black, mypy, pytest, coverage)
├── requirements.txt          # Python dependencies (all packages)
├── requirements-dev.txt      # Dev dependencies (ruff, black, mypy, coverage)
├── repos.yaml                # Target repositories configuration
├── run_local.py              # Local development server (Uvicorn on port 8000)
├── test_local_pipeline.py    # Full pipeline simulation (no AWS needed)
├── template.yaml             # AWS SAM deployment template (IaC)
│
├── .github/                  # 🔄 CI/CD
│   └── workflows/
│       └── ci.yml            #    GitHub Actions: lint, format, typecheck, tests
│
├── projectdocs/              # 📚 Project documentation
│   ├── README.md             #    Documentation index
│   ├── ARCHITECTURE.md       #    System architecture
│   ├── HLD.md                #    High-Level Design
│   ├── LLD.md                #    Low-Level Design
│   ├── TECH_STACK.md         #    Technology stack
│   ├── INSTALLATION.md       #    Installation guide
│   ├── HOW_TO_RUN.md         #    How to run locally & deploy
│   ├── REPO_STRUCTURE.md     #    This file
│   ├── API_REFERENCE.md      #    REST API & data schemas
│   ├── PIPELINE_WORKFLOW.md  #    Step-by-step pipeline flow
│   ├── CONFIGURATION.md      #    Environment & policy config
│   ├── TESTING.md            #    Test strategy & guide
│   ├── DEPLOYMENT.md         #    AWS deployment guide
│   ├── SECURITY.md           #    Security documentation
│   ├── TROUBLESHOOTING.md    #    Debugging & FAQ
│   ├── CONTRIBUTING.md       #    Contribution guidelines
│   ├── GLOSSARY.md           #    Terminology reference
│   └── CHANGELOG.md          #    Version history
│
├── shared/                   # 🔧 Cross-cutting utilities
│   ├── __init__.py           #    Package init
│   ├── config.py             #    Centralized settings (singleton from .env)
│   ├── event_id.py           #    Event ID generation (evt-<slug>-<run>-<ts>)
│   ├── logger.py             #    Structured logging (structlog, JSON/console)
│   ├── timeline.py           #    Pipeline step timing & progress tracker
│   ├── storage.py            #    S3 (prod) / LocalStorage (dev) abstraction
│   ├── github_auth.py        #    GitHub App JWT auth + token caching
│   └── notifier.py           #    Email (SMTP) + PR comment notifications
│
├── step1/                    # 📡 Webhook Handler (GitHub → SQS)
│   ├── __init__.py           #    Package init
│   ├── models.py             #    Pydantic models (WebhookPayload, WorkflowRun)
│   ├── signature.py          #    HMAC-SHA256 webhook signature validation
│   ├── sqs_client.py         #    SQS publisher (prod) / LocalQueue (dev)
│   ├── webhook_handler.py    #    FastAPI app (/webhook, /health endpoints)
│   └── lambda_handler.py     #    Mangum adapter for AWS Lambda
│
├── step2/                    # ⚙️ Worker — Core Pipeline Orchestrator
│   ├── __init__.py           #    Package init
│   ├── log_fetcher.py        #    Download GitHub Actions logs (ZIP → text)
│   ├── sanitizer.py          #    Redact secrets (10 regex patterns)
│   ├── excerpt.py            #    Heuristic excerpt generator (error lines)
│   └── worker.py             #    Main orchestrator (calls Steps 3-8)
│
├── step3/                    # 🧠 Vector DB — Embeddings + Search (RAG)
│   ├── __init__.py           #    Package init
│   ├── embedder.py           #    sentence-transformers (all-MiniLM-L6-v2)
│   ├── indexer.py            #    Qdrant upsert + S3 backup
│   ├── rag_metrics.py        #    RAG evaluation (retrieval, context, generation quality)
│   └── retriever.py          #    Similarity search with filters
│
├── step4/                    # 🔀 LangGraph — Pipeline Graph Orchestration
│   ├── __init__.py           #    Package init
│   ├── models.py             #    PipelineState TypedDict, input/output models
│   ├── nodes.py              #    Graph nodes (evidence, triage, planner, policy)
│   └── graph.py              #    StateGraph builder + sequential fallback
│
├── step5/                    # 🔍 Triage — Failure Classification
│   ├── __init__.py           #    Package init
│   └── triage.py             #    Groq LLM classifier + keyword fallback
│
├── step6/                    # 📋 Planner — Fix Plan Generation
│   ├── __init__.py           #    Package init
│   └── planner.py            #    Groq LLM planner + template fallback
│
├── step7/                    # 🛡️ Policy — Safety Evaluation
│   ├── __init__.py           #    Package init
│   └── policy.py             #    Rule-based YAML policy engine (deny-by-default)
│
├── step8/                    # 🔀 PR Creator — GitHub Pull Request
│   ├── __init__.py           #    Package init
│   └── pr_creator.py         #    Create branch, apply changes, open PR
│
├── step9/                    # 🧹 Code Quality Gate — Pre-PR Validation
│   ├── __init__.py           #    Package init
│   └── code_checker.py       #    Syntax + ruff + black + mypy checks
│
├── step10/                   # ✅ Verifier + Rollback — Post-PR Validation
│   ├── __init__.py           #    Package init
│   ├── models.py             #    VerificationResult + RollbackResult dataclasses
│   ├── verifier.py           #    CI result verification on fix/* branches
│   └── rollback.py           #    Revert PR creator + anti-flapping + rate limiting
│
├── step11/                   # 📊 Observability + Kill Switch
│   ├── __init__.py           #    Package init
│   ├── metrics.py            #    Prometheus metrics registry + Pushgateway push
│   └── killswitch.py         #    SSM-backed kill switch + cache + decorator
│
├── monitoring/               # 🖥️ Monitoring Infrastructure (Docker Compose)
│   ├── _build_dashboard.py   #    Aceternity SaaS-style dashboard generator
│   ├── dashboard-preview.html #   Generated monitoring dashboard (Chart.js)
│   ├── docker-compose.yml    #    Pushgateway + Prometheus + Grafana stack
│   ├── prometheus.yml        #    Prometheus scrape config
│   └── provisioning/
│       └── datasources/
│           └── datasource.yml #   Grafana auto-provisioned Prometheus source
│
├── policy/                   # 📜 Policy Configuration
│   └── default.yaml          #    Default safety rules (7 rules, deny-by-default)
│
├── tests/                    # 🧪 Test Suite
│   ├── __init__.py           #    Package init
│   ├── test_signature.py     #    Webhook HMAC validation tests (6 tests)
│   ├── test_event_id.py      #    Event ID generation tests (7 tests)
│   ├── test_sanitizer.py     #    Log sanitization tests (8 tests)
│   ├── test_excerpt.py       #    Excerpt generation tests (7 tests)
│   ├── test_triage.py        #    Triage classification tests (8 tests)
│   ├── test_policy.py        #    Policy evaluation tests (8 tests)
│   ├── test_webhook.py       #    Webhook handler tests (3 tests)
│   ├── test_step3.py         #    Vector DB tests (6 tests, mocked)
│   ├── test_step4.py         #    LangGraph tests (8 tests, mocked)
│   ├── test_rag_metrics.py   #    RAG evaluation metrics tests (21 tests)
│   ├── test_step9.py         #    Code quality gate tests (12 tests)
│   ├── test_step10.py        #    Verifier + rollback tests (15 tests)
│   └── test_step11.py        #    Observability + kill switch tests (14 tests)
│
└── CICD/                     # 📐 Architecture Specs & Diagrams (reference)
    ├── CIAutoFixSystem.txt   #    Full architecture specification
    ├── TechStack.txt         #    Technology decisions per step
    ├── playbook.txt          #    Playbook & policy format specs
    ├── GenericPrompt.txt     #    LLM prompt templates
    ├── full-architecture/    #    System-wide diagrams (PlantUML, PDF)
    ├── step0/ ... step11/    #    Per-step specs and diagrams
    └── TECH/                 #    Additional tech documentation
```

---

## Module Summary

| Module | Files | Purpose |
|--------|-------|---------|
| `shared/` | 7 | Cross-cutting: config, logging, auth, storage, notifications |
| `step1/` | 5 | Webhook ingestion: validate, parse, queue |
| `step2/` | 4 | Core orchestrator: fetch logs, sanitize, excerpt, run pipeline |
| `step3/` | 4 | Vector DB: embed text, index events, retrieve similar failures, RAG metrics |
| `step4/` | 3 | LangGraph: graph nodes, state management, orchestration |
| `step5/` | 1 | Triage: LLM-powered failure classification |
| `step6/` | 1 | Planner: LLM-powered fix plan generation |
| `step7/` | 1 | Policy: rule-based safety evaluation |
| `step8/` | 1 | PR Creator: GitHub branch + pull request |
| `step9/` | 1 | Code Quality Gate: syntax + lint + format + type checks |
| `step10/` | 3 | Verifier: CI result checking + revert PR rollback |
| `step11/` | 2 | Observability: Prometheus metrics + SSM kill switch |
| `monitoring/` | 5 | Docker Compose: Pushgateway + Prometheus + Grafana + Dashboard |
| `policy/` | 1 | YAML policy configuration |
| `tests/` | 13 | Unit tests with mocks |
| **Total** | **53+** | **Complete CI auto-fix pipeline with observability** |

---

## File Size Estimates

| Category | Files | Approx. Lines |
|----------|-------|---------------|
| Source Code | 35 | ~5,200 |
| Tests | 13 | ~2,500 |
| Configuration | 10 | ~500 |
| Documentation | 19 | ~5,500 |
| **Total** | **77+** | **~13,700** |
