# 🔄 Pipeline Workflow — RepoMind CI Auto-Fix Agent

## 1. Pipeline Overview

The RepoMind pipeline processes CI failures through **11 steps** (Steps 1–11 implemented). Each step has a single responsibility and communicates through well-defined data contracts.

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE FLOW                                 │
│                                                                  │
│  GitHub CI ──▶ Step 1 ──▶ SQS ──▶ Step 2 (orchestrates all)    │
│               Webhook          Worker                            │
│                                  │                               │
│                    ┌─────────────┼─────────────┐                │
│                    ▼             ▼             ▼                │
│               Fetch Logs   Sanitize      Excerpt                │
│                    │             │             │                │
│                    └─────────────┼─────────────┘                │
│                                  ▼                               │
│                    ┌─────────────────────────┐                  │
│                    │  Step 4: LangGraph      │                  │
│                    │  ┌───────────────────┐  │                  │
│                    │  │ Step 3: Evidence   │  │                  │
│                    │  │ Step 5: Triage     │  │                  │
│                    │  │ Step 6: Planner    │  │                  │
│                    │  │ Step 7: Policy     │  │                  │
│                    │  └───────────────────┘  │                  │
│                    └───────────┬─────────────┘                  │
│                                ▼                                 │
│                          Step 8: PR Creator                      │
│                                ▼                                 │
│                     Save Artifacts + Notify                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Step-by-Step Detail

### Step 1 — Webhook Handler 📡

| Field | Value |
|-------|-------|
| **Module** | `step1/webhook_handler.py` |
| **Trigger** | GitHub `workflow_run` webhook (POST) |
| **Runtime** | API Gateway → Lambda (256 MB, 30s timeout) |

**Flow:**

1. Receive HTTP POST from GitHub
2. Validate HMAC-SHA256 signature (`X-Hub-Signature-256` header)
3. Parse JSON → `GitHubWebhookPayload` model
4. Check: `action == "completed"` AND `conclusion == "failure"`
5. Generate unique `event_id`: `evt-<slug>-<run_id>-<timestamp>`
6. Publish minimal message to SQS queue
7. Return `202 Accepted`

**Input:** Raw HTTP request with GitHub webhook payload  
**Output:** SQS message with `event_id, repo, workflow_run_id, run_url, timestamp`

**Does NOT do:** Fetch logs, call LLM, write S3, heavy processing

---

### Step 2 — Worker (Core Orchestrator) ⚙️

| Field | Value |
|-------|-------|
| **Module** | `step2/worker.py` |
| **Trigger** | SQS message from Step 1 |
| **Runtime** | Lambda (1024 MB, 300s timeout, batch_size=1) |

**Flow:**

1. Parse SQS message → `PipelineContext`
2. **Fetch logs:** Download GitHub Actions ZIP logs via API
3. **Sanitize:** Redact secrets (10 regex patterns)
4. **Excerpt:** Extract error-relevant lines (heuristic)
5. **Store:** Upload `full_logs.txt` + `excerpt.txt` to S3
6. **Triage:** Classify failure type (Step 5)
7. **Plan:** Generate fix actions (Step 6)
8. **Policy:** Evaluate safety rules (Step 7)
9. **PR:** If policy allows → create GitHub PR (Step 8)
10. **Index:** Embed & store vectors in Qdrant (Step 3)
11. **Artifacts:** Save `artifacts.json` + `timeline.json` to S3
12. **Notify:** Send email / PR comment notification

**Input:** SQS message  
**Output:** `artifacts.json`, `timeline.json`, PR (if allowed)

---

### Step 3 — Vector DB (Embeddings + RAG) 🧠

| Field | Value |
|-------|-------|
| **Module** | `step3/embedder.py`, `step3/indexer.py`, `step3/retriever.py` |
| **Called by** | Step 2 (Worker) after PR creation |

**Components:**

| Component | Purpose | Details |
|-----------|---------|---------|
| **Embedder** | Text → 384-dim vector | Uses `all-MiniLM-L6-v2` (local, free) |
| **Indexer** | Store vectors in Qdrant | Creates collection, upserts points, S3 backup |
| **Retriever** | Search similar events | Similarity search with repo/type filters |

**Embedding Types:**

- `excerpt_embedding` — CI log excerpt
- `triage_embedding` — Failure classification summary
- `plan_embedding` — Fix plan description
- `verification_embedding` — Post-fix verification (future)

**Qdrant Collection:** `repomind_events` (384 dimensions, Cosine distance)

---

### Step 4 — LangGraph Orchestration 🔀

| Field | Value |
|-------|-------|
| **Module** | `step4/graph.py`, `step4/nodes.py`, `step4/models.py` |
| **Called by** | Step 2 (Worker) — optional orchestration layer |

**Graph Nodes:**

```
START → evidence_node → triage_node → planner_node → policy_node → END
```

| Node | Calls | Purpose |
|------|-------|---------|
| `evidence_node` | Step 3 Retriever | Find similar past failures (RAG) |
| `triage_node` | Step 5 TriageEngine | Classify the failure |
| `planner_node` | Step 6 Planner | Generate fix plan |
| `policy_node` | Step 7 PolicyEngine | Evaluate safety |

**State:** `PipelineState` TypedDict flows through all nodes.  
**Fallback:** If LangGraph fails → sequential function execution.

---

### Step 5 — Triage (Failure Classification) 🔍

| Field | Value |
|-------|-------|
| **Module** | `step5/triage.py` |
| **Called by** | Step 2 (Worker) or Step 4 (triage_node) |

**Classification Categories:**

| Type | Example Error |
|------|---------------|
| `dependency_error` | `Cannot find module 'lodash'` |
| `import_error` | `ModuleNotFoundError: No module named 'foo'` |
| `syntax_error` | `SyntaxError: invalid syntax` |
| `test_failure` | `FAILED tests/test_foo.py::test_bar` |
| `type_error` | `TypeError: expected str, got int` |
| `configuration_error` | `Config file not found` |
| `build_error` | `Build failed with exit code 1` |
| `lint_error` | `Linting errors found` |
| `runtime_error` | `RuntimeError: ...` |
| `unknown` | Unclassifiable failure |

**LLM:** Groq `openai/gpt-oss-120b` (JSON mode, temperature=0.1)  
**Fallback:** Keyword matching heuristic if LLM unavailable

**Output:**

```json
{
  "failure_type": "dependency_error",
  "confidence": 0.87,
  "summary": "Missing dependency 'lodash'"
}
```

---

### Step 6 — Planner (Fix Plan Generation) 📋

| Field | Value |
|-------|-------|
| **Module** | `step6/planner.py` |
| **Called by** | Step 2 (Worker) or Step 4 (planner_node) |

**Input:** Triage result + excerpt  
**LLM:** Groq `openai/gpt-oss-120b` (JSON mode, temperature=0.2)  
**Fallback:** Template-based plan per failure type

**Output:**

```json
{
  "playbook_id": "fix_dependency_error",
  "actions": ["Add lodash to dependencies", "Run npm install"],
  "files_to_modify": ["package.json"],
  "code_changes": [...],
  "risk_level": "low"
}
```

---

### Step 7 — Policy (Safety Evaluation) 🛡️

| Field | Value |
|-------|-------|
| **Module** | `step7/policy.py` |
| **Called by** | Step 2 (Worker) or Step 4 (policy_node) |
| **Config** | `policy/default.yaml` |

**Evaluation Logic:**

1. Load policy rules (YAML or hardcoded defaults)
2. Iterate rules in order
3. First matching rule → return its decision
4. No match → **DENY** (fail-closed, conservative)

**Decisions:** `allow`, `deny`, `manual_review`

**Output:**

```json
{
  "decision": "allow",
  "reason": "Low-risk dependency fix with high confidence",
  "rules_triggered": ["allow_low_risk_dependency_fix"]
}
```

---

### Step 8 — PR Creator (GitHub Pull Request) 🔀

| Field | Value |
|-------|-------|
| **Module** | `step8/pr_creator.py` |
| **Called by** | Step 2 (Worker) — only if policy decision = "allow" |

**Flow:**

1. Authenticate via GitHub App
2. Get repository default branch
3. Create branch: `fix/<failure_type>-<event_id_suffix>`
4. Apply `code_changes` from plan (create/update files)
5. If no changes → create placeholder commit
6. Create Pull Request with detailed markdown body
7. Return PR URL, branch, commit SHA

---

### Step 9 — Code Quality Gate 🧹

| Field | Value |
|-------|-------|
| **Module** | `step9/code_checker.py` |
| **Called by** | Step 2 (Worker) — after Policy (Step 7), before PR Creation (Step 8) |

**Purpose:** Validate LLM-generated code changes before creating a pull request. Catches syntax errors, lint violations, formatting issues, and type errors.

**Quality Checks:**

| Tool | Check Type | Severity | Always Available |
|------|-----------|----------|-----------------|
| `ast.parse` | Python syntax validation | **Blocking** | ✅ (stdlib) |
| `ruff` | Linting (style + bugs) | **Blocking** | Requires install |
| `black --check` | Formatting verification | Warning | Requires install |
| `mypy` | Static type checking | Warning | Requires install |

**Flow:**

1. Receive `code_changes` list from Planner (Step 6)
2. Filter Python files only (`.py` extension), skip deletes
3. Write proposed files to a temp directory
4. Run each tool against the temp files
5. Collect results into a structured report
6. Clean up temp directory
7. Return report with pass/fail status

**Blocking vs Warning:**

- **Blocking** (`syntax`, `ruff`): If any blocking check fails → PR creation is skipped
- **Warning** (`black`, `mypy`): Logged but do not prevent PR creation

**Fail-Open Design:** If the code checker itself crashes (e.g., tool not installed), it does **not** block PR creation. Errors are logged and the pipeline continues.

**Output:**

```json
{
  "passed": true,
  "total_checks": 4,
  "passed_checks": 3,
  "failed_checks": 1,
  "blocking_failures": 0,
  "checks": [
    {"tool": "syntax", "passed": true, "severity": "blocking", "details": "All files passed syntax check"},
    {"tool": "ruff", "passed": true, "severity": "blocking", "details": "No lint violations"},
    {"tool": "black", "passed": false, "severity": "warning", "details": "1 file would be reformatted"},
    {"tool": "mypy", "passed": true, "severity": "warning", "details": "No type errors found"}
  ],
  "summary": "✅ All blocking checks passed (1 warning)"
}
```

---

### Step 10 — Verifier + Rollback 🔄

| Field | Value |
|-------|-------|
| **Module** | `step10/verifier.py`, `step10/rollback.py` |
| **Trigger** | `workflow_run.completed` on `fix/*` branches |
| **Runtime** | Routed via Worker Lambda |

**Flow:**

1. GitHub fires `workflow_run.completed` on a `fix/*` branch
2. Step 1 detects `fix/*` branch, sets `message_type="verification"`
3. Worker routes to `_handle_verification()` → `Verifier.verify()`
4. Verifier checks CI conclusion (`success` or `failure`)
5. If **passed** → log success, record metrics, done
6. If **failed** → check kill switch → anti-flapping check → rate limit check
7. `RollbackClient` creates revert PR via PyGithub
8. Comment on original fix PR, send email notification
9. Store verification result + rollback record in S3

**Safety Guards:**

- Anti-flapping: max 1 rollback per event (S3 marker `rollback.json`)
- Rate limiting: max 3 rollbacks per repo per hour (configurable)
- Kill switch: checked before creating revert PR
- Revert PR: creates PR, not direct push (human review still required)
- Audit trail: everything stored in S3

**Output:**

```json
{
  "status": "failed",
  "ci_conclusion": "failure",
  "fix_branch": "fix/missing_import-abc12345",
  "repo": "user/mlproject",
  "rollback_triggered": true,
  "rollback_pr_url": "https://github.com/user/mlproject/pull/99",
  "message": "Fix failed: CI failed on fix/missing_import-abc12345. Rollback triggered."
}
```

---

### Step 11 — Observability + Kill Switch 📊

| Field | Value |
|-------|-------|
| **Module** | `step11/metrics.py`, `step11/killswitch.py` |
| **Infrastructure** | Pushgateway + Prometheus + Grafana (docker-compose) |
| **Kill Switch** | AWS SSM Parameter Store (`/repomind/kill_switch`) |

**Metrics (via Prometheus):**

| Metric | Type | Labels |
|--------|------|--------|
| `repomind_events_total` | Counter | repo, status |
| `repomind_pipeline_duration_seconds` | Histogram | repo, step |
| `repomind_triage_confidence` | Gauge | repo, failure_type |
| `repomind_policy_decisions_total` | Counter | repo, decision |
| `repomind_quality_checks_total` | Counter | repo, result |
| `repomind_prs_created_total` | Counter | repo |
| `repomind_verification_total` | Counter | repo, result |
| `repomind_rollbacks_total` | Counter | repo, reason |
| `repomind_errors_total` | Counter | repo, step |
| `repomind_kill_switch_state` | Gauge | — |

**Kill Switch Behavior:**

| SSM Value | Pipeline Behavior |
|-----------|-------------------|
| `"off"` | Normal operation |
| `"on"` | Pipeline halts, no PRs or rollbacks |
| Unreachable | **Fail-safe: halt** (assume ON) |
| Development mode | Always OFF (bypass) |

**Design:** Metrics are non-fatal (no-op if Pushgateway is down). Kill switch defaults to safe behavior.

---

## 3. Pipeline Timing (Typical)

| Step | Duration | Notes |
|------|----------|-------|
| Step 1 (Webhook) | ~100ms | Lightweight validation + SQS publish |
| Step 2 (Log Fetch) | 2–5s | GitHub API download + ZIP extraction |
| Step 2 (Sanitize) | ~100ms | Regex matching |
| Step 2 (Excerpt) | ~100ms | Heuristic line extraction |
| Step 5 (Triage) | 1–3s | Groq LLM inference |
| Step 6 (Plan) | 2–4s | Groq LLM inference |
| Step 7 (Policy) | ~10ms | Rule evaluation |
| Step 9 (Quality) | ~50ms | Syntax + lint + format + type checks |
| Step 8 (PR) | 3–8s | GitHub API calls |
| Step 3 (Index) | 1–3s | Embedding + Qdrant upsert |
| Step 11 (Kill Switch) | ~20ms | SSM parameter read (cached 30s) |
| Step 11 (Metrics Push) | ~50ms | HTTP POST to Pushgateway |
| Step 10 (Verify) | ~200ms | GitHub API check + rollback |
| **Total** | **10–25s** | **End-to-end** |

---

## 4. Pipeline Status Values

| Status | Meaning |
|--------|---------|
| `completed` | Full pipeline success, PR created |
| `policy_denied` | Pipeline completed but PR not created (policy deny) |
| `quality_blocked` | Pipeline completed but PR not created (code quality gate failed) |
| `halted` | Pipeline stopped by kill switch |
| `verified` | Fix branch CI passed verification (Step 10) |
| `rolled_back` | Fix branch CI failed, revert PR created (Step 10) |
| `failed` | Pipeline error (partial artifacts saved) |
| `triage_failed` | Could not classify the failure |
| `plan_failed` | Could not generate a fix plan |
