# 🔬 Low-Level Design (LLD) — RepoMind CI Auto-Fix Agent

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | RepoMind CI Auto-Fix Agent |
| **Version** | 1.0.0-alpha |
| **Date** | February 2026 |

---

## 2. Module-Level Design

### 2.1 Shared Layer (`shared/`)

#### 2.1.1 `config.py` — Settings Management
```
┌─────────────────────────────────┐
│         Settings (dataclass)     │
├─────────────────────────────────┤
│ + AWS_REGION: str               │
│ + AWS_ACCOUNT_ID: str           │
│ + S3_SAM_BUCKET: str            │
│ + S3_DATA_BUCKET: str           │
│ + GITHUB_APP_ID: str            │
│ + GITHUB_INSTALLATION_ID: str   │
│ + GITHUB_PRIVATE_KEY_PATH: str  │
│ + GITHUB_WEBHOOK_SECRET: str    │
│ + GROQ_API_KEY: str             │
│ + GMAIL_ADDRESS: str            │
│ + GMAIL_APP_PASSWORD: str       │
│ + NOTIFICATION_EMAILS: List[str]│
│ + QDRANT_HOST: str              │
│ + QDRANT_PORT: int              │
│ + TARGET_REPO: str              │
│ + LOG_LEVEL: str                │
│ + ENVIRONMENT: str              │
├─────────────────────────────────┤
│ + from_env() → Settings         │
│ + validate_required(keys) → None│
└─────────────────────────────────┘
Singleton: settings = Settings.from_env()
```

**Pattern:** Singleton via module-level instantiation  
**Load Order:** .env file → os.environ → defaults  
**Validation:** `validate_required()` for fail-fast startup

#### 2.1.2 `event_id.py` — Event Identification
```python
def generate_event_id(repo: str, run_id: int) -> str:
    """Returns: evt-<slug>-<run_id>-<YYYYMMDDTHHmmssZ>"""

def extract_repo_slug(event_id: str) -> str:
    """Extracts 'myorg-service-a' from event_id"""
```

**Slug Rules:**
- `owner/repo` → `owner-repo` (replace `/` with `-`)
- Lowercase, strip special chars
- Max 60 chars

#### 2.1.3 `logger.py` — Structured Logging
```python
def get_logger(name: str) -> structlog.BoundLogger:
    """Production: JSON output. Dev: colored console."""
```

**Configuration:**
- Production (`ENVIRONMENT=production`): JSON processor chain
- Development: ConsoleRenderer with colors
- Adds: timestamp, log level, logger name

#### 2.1.4 `timeline.py` — Pipeline Progress Tracking
```
┌────────────────────────────────┐
│        Timeline                 │
├────────────────────────────────┤
│ + event_id: str                │
│ + entries: List[Dict]          │
│ - _step_starts: Dict           │
├────────────────────────────────┤
│ + start_step(step, name) → None│
│ + record(step, type, data)     │
│ + record_error(step, error)    │
│ + to_dict() → Dict             │
└────────────────────────────────┘
```

**Entry Schema:**
```json
{
  "step": 5,
  "type": "triage_completed",
  "timestamp": "2026-02-13T15:44:30Z",
  "duration_ms": 1234,
  "data": { "triage_summary": "..." }
}
```

#### 2.1.5 `storage.py` — Storage Abstraction
```
┌────────────────────────────┐
│   StorageProtocol (ABC)     │
├────────────────────────────┤
│ + put_text(key, text)       │
│ + put_json(key, data)       │
│ + get_text(key) → str       │
│ + get_json(key) → dict      │
│ + exists(key) → bool        │
└────────┬───────────┬────────┘
         │           │
    ┌────▼────┐ ┌────▼──────┐
    │S3Storage│ │LocalStorage│
    │ (prod)  │ │  (dev)     │
    └─────────┘ └────────────┘

Factory: get_storage() → StorageProtocol
```

**S3Storage:** Uses boto3 S3 client, bucket from settings  
**LocalStorage:** Writes to `./data/` directory  
**Selection:** Based on `settings.ENVIRONMENT`

#### 2.1.6 `github_auth.py` — GitHub App Authentication
```python
class GitHubAuth:
    _token_cache: Optional[str]
    _token_expires: Optional[datetime]

    def _generate_jwt() -> str
        """RS256 JWT, 10-minute expiry"""

    def _get_installation_token() -> str
        """POST /app/installations/{id}/access_tokens, cached ~1hr"""

    def get_github_client() -> Github
        """Returns authenticated PyGithub instance"""
```

**Token Lifecycle:**
1. Generate JWT from private key (10-min expiry)
2. Exchange JWT for installation token (~1-hour validity)
3. Cache installation token; refresh when expired
4. Return PyGithub client with token

#### 2.1.7 `notifier.py` — Notification System
```
┌────────────────────────────────────┐
│          Notifier                   │
├────────────────────────────────────┤
│ + send_email(subject, body) → bool │
│ + post_pr_comment(repo, pr, msg)   │
│ + notify_pipeline_success(ctx)     │
│ + notify_pipeline_failure(ctx, err)│
│ + notify_policy_denied(ctx)        │
└────────────────────────────────────┘
```

---

### 2.2 Step 1 — Webhook Handler (`step1/`)

#### 2.2.1 Data Models
```
┌──────────────────────────────┐
│ GitHubWebhookPayload         │
├──────────────────────────────┤
│ + action: str                │
│ + workflow_run: WorkflowRun  │
│ + repository: Repository     │
├──────────────────────────────┤
│ + is_failed_workflow() → bool│
└──────────────────────────────┘

┌─────────────────────┐  ┌────────────────────┐
│ WorkflowRun         │  │ Repository         │
├─────────────────────┤  ├────────────────────┤
│ + id: int           │  │ + full_name: str   │
│ + name: str         │  │ + html_url: str    │
│ + conclusion: str   │  └────────────────────┘
│ + html_url: str     │
│ + head_branch: str  │
│ + head_sha: str     │
└─────────────────────┘
```

#### 2.2.2 Signature Validation
```python
def validate_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    1. Compute HMAC-SHA256 of raw payload with secret
    2. Compare with 'sha256=<hex>' from X-Hub-Signature-256 header
    3. Use hmac.compare_digest() for constant-time comparison
    """
```

#### 2.2.3 Webhook Handler (FastAPI)
```python
@app.post("/webhook")
async def handle_webhook(request: Request):
    """
    Flow:
    1. Read raw body
    2. Validate HMAC signature → 401 if invalid
    3. Parse JSON → GitHubWebhookPayload
    4. Check is_failed_workflow() → 200 (skip) if not
    5. Generate event_id
    6. Publish SQSMessage to queue
    7. Return 202 Accepted
    """

@app.get("/health")
async def health(): → {"status": "healthy"}
```

#### 2.2.4 SQS Client
```
┌─────────────────────────────┐
│   QueueProtocol (ABC)        │
├─────────────────────────────┤
│ + publish(message: dict)     │
└──────┬──────────┬────────────┘
       │          │
  ┌────▼───┐ ┌───▼──────────┐
  │SQSClient│ │LocalQueue    │
  │ (boto3) │ │ (log only)   │
  └─────────┘ └──────────────┘
```

---

### 2.3 Step 2 — Worker (`step2/`)

#### 2.3.1 Pipeline Context
```
┌─────────────────────────────────┐
│     PipelineContext (dataclass)  │
├─────────────────────────────────┤
│ + event_id: str                 │
│ + repo: str                     │
│ + workflow_run_id: int          │
│ + run_url: str                  │
│ + head_branch: str              │
│ + head_sha: str                 │
│ + raw_logs: Optional[str]       │
│ + sanitized_logs: Optional[str] │
│ + excerpt: Optional[str]        │
│ + triage: Optional[Dict]        │
│ + plan_summary: Optional[Dict]  │
│ + policy: Optional[Dict]        │
│ + code_quality: Optional[Dict]  │
│ + pr: Optional[Dict]            │
│ + verification: Optional[Dict]  │
│ + message_type: str             │  "ci_failure" | "verification"
│ + status: str                   │
│ + error: Optional[str]          │
├─────────────────────────────────┤
│ + to_artifacts() → Dict         │
└─────────────────────────────────┘
```

#### 2.3.2 Worker Orchestration Flow
```python
class Worker:
    def process_event(self, message: dict) → Dict:
        """
        0. Check kill switch (Step 11) → halt if ON
        1. Parse SQS message → PipelineContext
        1b. If message_type == 'verification' → route to _handle_verification()
        2. Fetch logs (LogFetcher)
        3. Sanitize logs (Sanitizer)
        4. Generate excerpt (ExcerptGenerator)
        5. Store logs/excerpt to S3
        6. Run triage (TriageEngine)
        7. Generate plan (Planner)
        8. Evaluate policy (PolicyEngine)
        9. Run code quality gate (CodeChecker)
        10. If allowed & quality passed → Create PR (PRCreator)
        11. Index vectors (Indexer)
        12. Save artifacts.json + timeline.json
        13. Record metrics + push to Pushgateway (Step 11)
        14. Send notification
        15. Return result summary
        """
```

#### 2.3.3 Log Fetcher
```python
class LogFetcher:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=16))
    def fetch_logs(self, repo: str, run_id: int) → str:
        """
        1. GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs
        2. Follow redirect → download ZIP
        3. Extract all .txt files from ZIP
        4. Concatenate with section headers
        5. Return combined log text
        """
```

#### 2.3.4 Sanitizer
```python
class Sanitizer:
    DEFAULT_PATTERNS = [
        ("aws_access_key",    r"AKIA[0-9A-Z]{16}"),
        ("aws_secret_key",    r"[A-Za-z0-9/+=]{40}"),
        ("github_token",      r"gh[ps]_[A-Za-z0-9_]{36,}"),
        ("bearer_token",      r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
        ("password_field",    r"(?i)password\s*[:=]\s*\S+"),
        ("email_address",     r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        ("private_ip",        r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d+\.\d+\b"),
        ("connection_string", r"(?i)(?:mysql|postgres|mongodb|redis)://\S+"),
        ("jwt_token",         r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        ("generic_secret",    r"(?i)(?:secret|api_key|apikey|token)\s*[:=]\s*['\"]?\S+"),
    ]

    def sanitize(self, text: str) → str:
        """Replace each pattern match with [REDACTED:<type>]"""
```

#### 2.3.5 Excerpt Generator
```python
class ExcerptGenerator:
    def generate(self, logs: str, max_lines: int = 200) → str:
        """
        Phase 1 — Heuristic:
        1. Split logs into lines
        2. Find lines with error keywords
        3. Add N context lines before/after
        4. Clean ANSI codes
        5. Deduplicate
        6. Truncate to max_lines

        Phase 2 — LLM (if needed):
        If excerpt is too long/noisy → LLM summary
        """
```

---

### 2.4 Step 3 — Vector DB (`step3/`)

#### 2.4.1 Embedder
```python
class Embedder:
    MODEL_NAME = "all-MiniLM-L6-v2"  # 384 dimensions
    _model = None  # Lazy-loaded singleton

    def embed_text(self, text: str) → List[float]:
        """Encode single text → 384-dim vector"""

    def embed_batch(self, texts: List[str]) → List[List[float]]:
        """Encode multiple texts → list of 384-dim vectors"""
```

#### 2.4.2 Indexer
```python
class Indexer:
    COLLECTION = "repomind_events"
    VECTOR_DIM = 384

    def index_event(self, event_id, repo, excerpt, triage, plan) → Dict:
        """
        1. Generate embeddings for excerpt, triage, plan
        2. Create Qdrant collection if not exists
        3. Upsert points with payload metadata
        4. Backup embeddings to S3
        5. Return indexing summary
        """
```

**Qdrant Point Payload:**
```json
{
  "event_id": "evt-...",
  "repo": "owner/repo",
  "embedding_type": "excerpt|triage|plan",
  "failure_type": "dependency_error",
  "text_preview": "first 500 chars..."
}
```

#### 2.4.3 Retriever
```python
class Retriever:
    def search(self, query_text, limit=5, filters=None) → List[SearchResult]:
        """
        1. Embed query text
        2. Search Qdrant with optional filters
        3. Filter by score_threshold
        4. Return SearchResult objects
        """

    def search_similar_failures(self, excerpt, repo=None, limit=5):
        """Convenience: search for similar past failures"""
```

**SearchResult:**
```python
@dataclass
class SearchResult:
    event_id: str
    score: float
    embedding_type: str
    text_preview: str
    metadata: Dict
```

---

### 2.5 Step 4 — LangGraph Orchestration (`step4/`)

#### 2.5.1 State Schema
```python
class PipelineState(TypedDict):
    event_id: str
    repo: str
    excerpt: str
    evidence: List[Dict]       # From Step 3 retriever
    triage: Optional[Dict]     # From Step 5
    plan_summary: Optional[Dict]  # From Step 6
    policy: Optional[Dict]     # From Step 7
    verification: Optional[Dict]  # From Step 10
    status: str
    errors: List[str]
```

#### 2.5.2 Graph Structure
```
 START
   │
   ▼
 evidence_node (Step 3 retrieval)
   │
   ▼
 triage_node (Step 5)
   │
   ▼
 planner_node (Step 6)
   │
   ▼
 policy_node (Step 7)
   │
   ▼
  END
```

**Fallback:** If LangGraph compilation fails → sequential execution of node functions.

---

### 2.6 Step 5 — Triage (`step5/`)

```python
class TriageEngine:
    FAILURE_TYPES = [
        "dependency_error", "import_error", "syntax_error",
        "test_failure", "type_error", "configuration_error",
        "build_error", "lint_error", "runtime_error", "unknown"
    ]

    def classify(self, excerpt: str, repo: str = "") → Dict:
        """
        1. Call Groq LLM (JSON mode, temp=0.1)
        2. Parse response → failure_type, confidence, summary
        3. Validate failure_type ∈ FAILURE_TYPES
        4. Fallback: keyword heuristic if LLM fails
        """

    def _keyword_fallback(self, excerpt: str) → Dict:
        """Match keywords: 'ModuleNotFoundError' → import_error, etc."""
```

**LLM Response Schema:**
```json
{
  "failure_type": "dependency_error",
  "confidence": 0.87,
  "summary": "Missing dependency 'lodash' in package.json",
  "root_cause": "...",
  "affected_files": ["package.json"]
}
```

---

### 2.7 Step 6 — Planner (`step6/`)

```python
class Planner:
    def generate_plan(self, triage: Dict, excerpt: str, repo: str = "") → Dict:
        """
        1. Call Groq LLM with triage + excerpt
        2. Parse → playbook_id, actions, files_to_modify, code_changes, risk_level
        3. Fallback: template plan per failure_type
        """
```

**Plan Schema:**
```json
{
  "playbook_id": "fix_dependency_error",
  "actions": ["update package.json", "run npm install"],
  "files_to_modify": ["package.json"],
  "code_changes": [
    {
      "file": "package.json",
      "description": "Add missing dependency",
      "diff": "..."
    }
  ],
  "risk_level": "low",
  "estimated_impact": "Adds missing dependency"
}
```

---

### 2.8 Step 7 — Policy (`step7/`)

```python
class PolicyEngine:
    def evaluate(self, triage: Dict, plan: Dict, repo: str = "") → Dict:
        """
        1. Load policy YAML (repo-specific or default.yaml)
        2. Iterate rules in order
        3. First matching rule → return decision
        4. No match → deny (fail-closed)
        """

    def _matches_rule(self, rule, triage, plan) → bool:
        """Check: failure_types, risk_level, confidence thresholds"""
```

**Policy Rule Evaluation Order:**
1. `allow_low_risk_dependency_fix` (confidence ≥ 0.7, risk = low)
2. `allow_import_fix` (confidence ≥ 0.8, risk = low)
3. `allow_syntax_fix` (confidence ≥ 0.9, risk = low)
4. `allow_config_fix` (confidence ≥ 0.85, risk = low)
5. `deny_high_risk` (risk = high)
6. `deny_low_confidence` (confidence ≤ 0.5)
7. `default_deny` (catch-all)

---

### 2.9 Step 8 — PR Creator (`step8/`)

```python
class PRCreator:
    def create_pr(self, repo, event_id, triage, plan, excerpt="") → Dict:
        """
        1. Get GitHub client (authenticated)
        2. Get default branch
        3. Create branch: fix/<type>-<short_id>
        4. Apply code_changes (create/update files)
        5. If no changes → placeholder commit
        6. Create PR with detailed markdown body
        7. Return: pr_url, branch, commit_sha, title, status
        """
```

**PR Branch Naming:** `fix/<failure_type>-<last_8_chars_of_event_id>`  
**PR Body:** Markdown with triage summary, plan details, policy status, confidence badge

---

### 2.10 Step 9 — Code Quality Gate (`step9/`)

```python
class CodeChecker:
    BLOCKING_TOOLS = {"syntax", "ruff"}

    def check(self, code_changes: List[Dict[str, Any]]) → Dict:
        """
        1. Filter Python files (.py), skip deletes
        2. Write proposed code to temp directory
        3. Run checks: syntax → ruff → black → mypy
        4. Build report with pass/fail per tool
        5. Clean up temp directory
        6. Return structured report
        """

    def _check_syntax(self, py_files: List[Path]) → CheckResult:
        """ast.parse() each file — always available (stdlib)"""

    def _check_ruff(self, tmp_dir: Path) → CheckResult:
        """Run `ruff check --select E,W,F` — blocking"""

    def _check_black(self, tmp_dir: Path) → CheckResult:
        """Run `black --check --quiet` — warning only"""

    def _check_mypy(self, tmp_dir: Path) → CheckResult:
        """Run `mypy --ignore-missing-imports` — warning only"""

    def _build_report(self, results: List[CheckResult]) → Dict:
        """Aggregate results, count blocking failures"""
```

**CheckResult:**
```python
@dataclass
class CheckResult:
    tool: str          # "syntax", "ruff", "black", "mypy"
    passed: bool       # True if check passed
    severity: str      # "blocking" or "warning"
    details: str       # Human-readable summary
    raw_output: str    # Full tool output
```

**Report Schema:**
```json
{
  "passed": true,
  "total_checks": 4,
  "passed_checks": 3,
  "failed_checks": 1,
  "blocking_failures": 0,
  "checks": [...],
  "summary": "✅ All blocking checks passed (1 warning)"
}
```

---

### 2.11 Step 10 — Verifier + Rollback (`step10/`)

#### 2.11.1 Data Models
```
┌─────────────────────────────────┐
│     VerificationResult          │
├─────────────────────────────────┤
│ + status: str                   │  "verified" | "failed" | "skipped"
│ + ci_conclusion: str            │  "success" | "failure" | "cancelled"
│ + fix_branch: str               │
│ + rollback_triggered: bool      │
│ + rollback_pr_url: Optional[str]│
├─────────────────────────────────┤
│ + to_dict() → Dict              │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│       RollbackResult            │
├─────────────────────────────────┤
│ + status: str                   │  "rolled_back" | "skipped" | "error"
│ + revert_pr_url: Optional[str]  │
│ + reason: str                   │
│ + original_pr_number: Optional  │
├─────────────────────────────────┤
│ + to_dict() → Dict              │
└─────────────────────────────────┘
```

#### 2.11.2 Verifier
```python
class Verifier:
    def verify(self, repo, branch, conclusion, event_id) → VerificationResult:
        """
        1. Check branch starts with 'fix/'
        2. If not fix/* → return skipped
        3. If conclusion == 'success' → return verified
        4. If conclusion != 'success' → check kill switch
        5. If kill switch ON → skip rollback
        6. Trigger rollback via RollbackClient
        7. Record metrics (Step 11)
        8. Return result
        """
```

#### 2.11.3 Rollback Client
```python
class RollbackClient:
    def rollback(self, repo, branch, event_id) → RollbackResult:
        """
        1. Anti-flapping: Check S3 marker (skip if already rolled back)
        2. Rate limiting: Check hourly counter (skip if max exceeded)
        3. Find merged PR for branch via GitHub API
        4. Revert files: restore base branch content
        5. Create revert PR with audit body
        6. Comment on original PR
        7. Send email notification
        8. Store rollback record in S3
        9. Record metrics (Step 11)
        """
```

**Anti-Flapping S3 Key:** `rollbacks/{event_id}/marker.json`  
**Rate Limit S3 Key:** `rollbacks/counters/{YYYY-MM-DD-HH}.json`  
**Audit Record S3 Key:** `rollbacks/{event_id}/record.json`

---

### 2.12 Step 11 — Observability + Kill Switch (`step11/`)

#### 2.12.1 Metrics Registry
```
┌───────────────────────────────────────┐
│         MetricsRegistry               │
├───────────────────────────────────────┤
│ + events_total: Counter               │  labels: repo, action
│ + pipeline_duration: Histogram        │  buckets: 1,5,10,30,60,120,300
│ + policy_decisions: Counter           │  labels: repo, decision
│ + quality_checks: Counter             │  labels: repo, result
│ + prs_created: Counter               │  labels: repo
│ + verification: Counter              │  labels: repo, result
│ + rollbacks: Counter                 │  labels: repo, result
│ + errors: Counter                    │  labels: step, error_type
│ + triage_confidence: Gauge           │  labels: repo
│ + kill_switch_state: Gauge           │  (no labels)
├───────────────────────────────────────┤
│ - _registry: CollectorRegistry        │
│ - _enabled: bool                      │
├───────────────────────────────────────┤
│ Disabled mode → _NoOpMetric stubs     │
└───────────────────────────────────────┘
```

```python
def push_metrics(registry: MetricsRegistry, job="repomind"):
    """
    Push all metrics to Prometheus Pushgateway.
    Non-fatal: errors logged but don't crash pipeline.
    Skipped if PUSHGATEWAY_URL not configured.
    """
```

#### 2.12.2 Kill Switch
```python
def is_kill_switch_enabled(settings) → bool:
    """
    1. Development mode → always return False (disabled)
    2. Check 30s TTL cache
    3. Read SSM: /repomind/kill_switch
    4. Value 'true'/'1'/'yes'/'enabled' → return True
    5. SSM error (network/permissions) → return True (fail-safe)
    6. Cache result with TTL
    """

def clear_cache():
    """Reset cache for testing."""

@require_kill_switch_off
def some_function():
    """Decorator: raises RuntimeError if kill switch is ON."""
```

**Cache Structure:**
```python
_cache = {
    "value": True/False,
    "expires_at": time.time() + 30
}
```

---

## 3. Error Handling Matrix

| Module | Error Type | Handling |
|--------|-----------|----------|
| `signature.py` | Invalid HMAC | Return 401 Unauthorized |
| `log_fetcher.py` | GitHub API 404/500 | Retry 3x with exponential backoff |
| `triage.py` | Groq API failure | Fall back to keyword heuristic |
| `planner.py` | Groq API failure | Fall back to template plan |
| `policy.py` | YAML parse error | Use hardcoded default rules |
| `policy.py` | Evaluation error | Deny (fail-closed) |
| `pr_creator.py` | GitHub API error | Record error, skip PR |
| `code_checker.py` | Tool not installed | Skip that check, log warning |
| `code_checker.py` | Checker crash | Fail-open: allow PR creation |
| `indexer.py` | Qdrant unavailable | Log warning, skip indexing |
| `graph.py` | LangGraph error | Fall back to sequential execution |
| `worker.py` | Any critical error | Save partial artifacts, notify, DLQ |
| `verifier.py` | GitHub API error | Log warning, return skipped |
| `rollback.py` | Anti-flapping match | Skip rollback, return skipped |
| `rollback.py` | Rate limit exceeded | Skip rollback, return skipped |
| `rollback.py` | Revert PR failure | Log error, return error status |
| `metrics.py` | Pushgateway unreachable | Log warning, continue (non-fatal) |
| `killswitch.py` | SSM unreachable | Return True — fail-safe (halt pipeline) |
| `killswitch.py` | SSM permission error | Return True — fail-safe (halt pipeline) |

---

## 4. Concurrency & Threading

| Component | Model |
|-----------|-------|
| Webhook Handler | Async (FastAPI/ASGI) |
| Worker | Synchronous (single SQS message at a time, batch_size=1) |
| Embedder | Synchronous (CPU-bound, model inference) |
| Qdrant Client | Synchronous HTTP |
| S3 Client | Synchronous boto3 |

---

## 5. Configuration Hierarchy

```
Environment Variables (.env)
       │
       ▼
Settings Dataclass (shared/config.py)
       │
       ├──▶ Policy YAML (policy/default.yaml)
       ├──▶ Repos YAML (repos.yaml)
       └──▶ SAM Template (template.yaml)
```

Priority: Environment Variables > .env file > Code defaults
