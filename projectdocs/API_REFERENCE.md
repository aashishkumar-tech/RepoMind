# 📡 API Reference — RepoMind CI Auto-Fix Agent

## 1. REST Endpoints

### 1.1 Webhook Endpoint

```
POST /webhook
```

**Description:** Receives GitHub workflow_run webhook events.

**Headers:**

| Header | Required | Description |
|--------|----------|-------------|
| `Content-Type` | Yes | `application/json` |
| `X-GitHub-Event` | Yes | Event type (must be `workflow_run`) |
| `X-Hub-Signature-256` | Yes | `sha256=<HMAC-SHA256 hex digest>` |
| `X-GitHub-Delivery` | No | Unique delivery ID |

**Request Body:** GitHub `workflow_run` webhook payload (see §2.1)

**Responses:**

| Status | Description |
|--------|-------------|
| `202 Accepted` | Event queued for processing |
| `200 OK` | Event skipped (not a failure, or non-matching event) |
| `401 Unauthorized` | Invalid webhook signature |
| `400 Bad Request` | Invalid payload |
| `500 Internal Server Error` | Server error |

**Response Body (202):**
```json
{
  "status": "queued",
  "event_id": "evt-myorg-service-a-123456789-20260213T154400Z",
  "message": "Event queued for processing"
}
```

---

### 1.2 Health Endpoint

```
GET /health
```

**Description:** Health check endpoint.

**Response (200):**
```json
{
  "status": "healthy",
  "service": "repomind-webhook"
}
```

---

### 1.3 Swagger UI

```
GET /docs
```

**Description:** Interactive API documentation (FastAPI auto-generated). Only available in local development.

---

## 2. Data Schemas

### 2.1 GitHub Webhook Payload (Input)

```json
{
  "action": "completed",
  "workflow_run": {
    "id": 123456789,
    "name": "CI",
    "conclusion": "failure",
    "html_url": "https://github.com/myorg/service-a/actions/runs/123456789",
    "head_branch": "main",
    "head_sha": "abc123def456"
  },
  "repository": {
    "full_name": "myorg/service-a",
    "html_url": "https://github.com/myorg/service-a"
  }
}
```

**Filter Criteria:** Only events where `action == "completed"` AND `workflow_run.conclusion == "failure"` are processed.

---

### 2.2 SQS Message (Internal)

```json
{
  "event_id": "evt-myorg-service-a-123456789-20260213T154400Z",
  "repo": "myorg/service-a",
  "workflow_run_id": 123456789,
  "run_url": "https://github.com/myorg/service-a/actions/runs/123456789",
  "head_branch": "main",
  "head_sha": "abc123def456",
  "timestamp": "2026-02-13T15:44:00Z"
}
```

---

### 2.3 Artifacts JSON (S3 Output)

Stored at: `events/<repo-slug>/<event-id>/artifacts.json`

```json
{
  "event_id": "evt-myorg-service-a-123456789-20260213T154400Z",
  "repo": "myorg/service-a",
  "status": "completed",
  "triage": {
    "failure_type": "dependency_error",
    "confidence": 0.87,
    "summary": "Missing dependency 'lodash' in package.json",
    "root_cause": "The package 'lodash' is imported but not listed in dependencies",
    "affected_files": ["package.json"]
  },
  "plan_summary": {
    "playbook_id": "fix_dependency_error",
    "actions": [
      "Add lodash to package.json dependencies",
      "Run npm install"
    ],
    "files_to_modify": ["package.json"],
    "code_changes": [
      {
        "file": "package.json",
        "description": "Add missing lodash dependency",
        "diff": "..."
      }
    ],
    "risk_level": "low",
    "estimated_impact": "Adds missing dependency"
  },
  "policy": {
    "decision": "allow",
    "reason": "Low-risk dependency fix with high confidence (0.87)",
    "rules_triggered": ["allow_low_risk_dependency_fix"]
  },
  "pr": {
    "url": "https://github.com/myorg/service-a/pull/42",
    "branch": "fix/dependency_error-154400Z",
    "commit_sha": "abc123",
    "title": "fix: resolve dependency_error (auto-fix)",
    "status": "created"
  },
  "indexing": {
    "status": "completed",
    "vectors_stored": 3,
    "collection": "repomind_events"
  }
}
```

---

### 2.4 Timeline JSON (S3 Output)

Stored at: `events/<repo-slug>/<event-id>/timeline.json`

```json
{
  "event_id": "evt-myorg-service-a-123456789-20260213T154400Z",
  "entries": [
    {
      "step": 2,
      "type": "logs_fetched",
      "timestamp": "2026-02-13T15:44:05Z",
      "duration_ms": 2345,
      "data": {"log_size_bytes": 45672}
    },
    {
      "step": 2,
      "type": "logs_sanitized",
      "timestamp": "2026-02-13T15:44:06Z",
      "duration_ms": 120,
      "data": {"patterns_matched": 3}
    },
    {
      "step": 2,
      "type": "excerpt_generated",
      "timestamp": "2026-02-13T15:44:06Z",
      "duration_ms": 80,
      "data": {"excerpt_lines": 45}
    },
    {
      "step": 5,
      "type": "triage_completed",
      "timestamp": "2026-02-13T15:44:08Z",
      "duration_ms": 1800,
      "data": {"triage_summary": "dependency_error (0.87 confidence)"}
    },
    {
      "step": 6,
      "type": "plan_generated",
      "timestamp": "2026-02-13T15:44:10Z",
      "duration_ms": 2100,
      "data": {"plan_summary": "Apply fix_dependency_error playbook"}
    },
    {
      "step": 7,
      "type": "policy_evaluated",
      "timestamp": "2026-02-13T15:44:10Z",
      "duration_ms": 15,
      "data": {"policy_summary": "Allowed (low-risk dependency fix)"}
    },
    {
      "step": 8,
      "type": "pr_created",
      "timestamp": "2026-02-13T15:44:15Z",
      "duration_ms": 4500,
      "data": {"pr_url": "https://github.com/myorg/service-a/pull/42"}
    }
  ]
}
```

---

### 2.5 Embedding JSON (S3 Backup)

Stored at: `embeddings/<repo-slug>/<event-id>/<type>_embedding.json`

```json
{
  "event_id": "evt-myorg-service-a-123456789-20260213T154400Z",
  "embedding_type": "excerpt",
  "model": "all-MiniLM-L6-v2",
  "dimensions": 384,
  "vector": [0.023, -0.156, 0.089, ...],
  "text_preview": "First 500 characters of the embedded text...",
  "timestamp": "2026-02-13T15:44:12Z"
}
```

Types: `excerpt_embedding`, `triage_embedding`, `plan_embedding`, `verification_embedding`

---

## 3. Error Response Format

All error responses follow a consistent format:

```json
{
  "detail": "Error message describing what went wrong",
  "status": "error"
}
```

---

## 4. Rate Limits

| Service | Limit |
|---------|-------|
| GitHub API | 5,000 requests/hour (authenticated) |
| Groq API | Varies by model (free tier: ~30 req/min) |
| Qdrant Cloud | Varies by plan |
| AWS API Gateway | 10,000 requests/second (default) |
