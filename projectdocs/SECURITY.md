# 🔒 Security Document — RepoMind CI Auto-Fix Agent

## 1. Security Overview

RepoMind processes sensitive data including CI logs, source code references, and GitHub credentials. This document describes the security measures implemented at every layer.

---

## 2. Threat Model

| Threat | Risk | Mitigation |
|--------|------|------------|
| **Forged webhook** | Unauthorized pipeline trigger | HMAC-SHA256 signature validation |
| **Secret leakage in logs** | Credential exposure | 10-pattern sanitizer, S3 encryption |
| **Malicious PR** | Code injection via auto-fix | Policy engine (deny-by-default), risk limits |
| **LLM prompt injection** | Manipulated triage/plan | Input sanitization, structured output, low temp |
| **Token theft** | GitHub/Groq API abuse | Short-lived JWT, env vars, no hardcoding |
| **S3 data exposure** | Unauthorized artifact access | Bucket policies, no public access |

---

## 3. Authentication & Authorization

### 3.1 GitHub App Authentication

```
┌─────────────────────────────────────────────────┐
│  Authentication Flow                             │
│                                                  │
│  Private Key (.pem)                              │
│       │                                          │
│       ▼                                          │
│  Generate JWT (RS256, 10-min expiry)             │
│       │                                          │
│       ▼                                          │
│  Exchange JWT → Installation Token (~1hr)        │
│       │                                          │
│       ▼                                          │
│  Authenticated API calls (PyGithub)              │
└─────────────────────────────────────────────────┘
```

**Security Properties:**
- Private key never leaves the server
- JWT expires in 10 minutes (short window)
- Installation tokens cached in memory only (not persisted)
- Tokens auto-refresh before expiry

### 3.2 Webhook Signature Validation

```python
# Implementation: step1/signature.py
def validate_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**Security Properties:**
- HMAC-SHA256 (cryptographically secure)
- `hmac.compare_digest()` — constant-time comparison (prevents timing attacks)
- Raw payload bytes validated (prevents JSON re-serialization attacks)
- 401 returned immediately on failure (no processing)

---

## 4. Secret Management

### 4.1 Environment Variables

All secrets are loaded from environment variables — **never hardcoded**:

| Secret | Env Var | Storage |
|--------|---------|---------|
| GitHub App ID | `GITHUB_APP_ID` | .env / SSM |
| Installation ID | `GITHUB_INSTALLATION_ID` | .env / SSM |
| Private Key | `GITHUB_PRIVATE_KEY_PATH` | File on disk / SSM |
| Webhook Secret | `GITHUB_WEBHOOK_SECRET` | .env / SSM (NoEcho) |
| Groq API Key | `GROQ_API_KEY` | .env / SSM (NoEcho) |
| Gmail Password | `GMAIL_APP_PASSWORD` | .env / SSM |

### 4.2 SAM Template (NoEcho)

Sensitive parameters in `template.yaml` use `NoEcho: true`:

```yaml
Parameters:
  GitHubWebhookSecret:
    Type: String
    NoEcho: true   # Masked in CloudFormation console
  GroqApiKey:
    Type: String
    NoEcho: true
```

### 4.3 `.gitignore` Protection

```gitignore
.env
private-key.pem
*.pem
data/
.aws-sam/
```

---

## 5. Log Sanitization

### 5.1 Sanitizer Patterns

The `Sanitizer` class (`step2/sanitizer.py`) applies 10 regex patterns to all CI logs:

| # | Pattern | Detects | Replacement |
|---|---------|---------|-------------|
| 1 | `AKIA[0-9A-Z]{16}` | AWS Access Key ID | `[REDACTED:aws_access_key]` |
| 2 | `[A-Za-z0-9/+=]{40}` | AWS Secret Key | `[REDACTED:aws_secret_key]` |
| 3 | `gh[ps]_[A-Za-z0-9_]{36,}` | GitHub Token | `[REDACTED:github_token]` |
| 4 | `Bearer\s+[A-Za-z0-9\-._~+/]+=*` | Bearer Token | `[REDACTED:bearer_token]` |
| 5 | `(?i)password\s*[:=]\s*\S+` | Password Field | `[REDACTED:password_field]` |
| 6 | `[email pattern]` | Email Address | `[REDACTED:email_address]` |
| 7 | `\b(?:10\|172\.(?:1[6-9]\|2\d\|3[01])\|192\.168)\.\d+\.\d+\b` | Private IP | `[REDACTED:private_ip]` |
| 8 | `(?i)(?:mysql\|postgres\|mongodb\|redis)://\S+` | Connection String | `[REDACTED:connection_string]` |
| 9 | `eyJ[...JWT pattern...]` | JWT Token | `[REDACTED:jwt_token]` |
| 10 | `(?i)(?:secret\|api_key\|token)\s*[:=]\s*\S+` | Generic Secret | `[REDACTED:generic_secret]` |

### 5.2 Sanitization Pipeline

```
Raw CI Logs → Sanitizer (10 patterns) → Sanitized Logs → Excerpt → S3
                                                                    │
                                                            Sanitized text
                                                            stored, NOT raw
```

**Important:** Sanitization happens BEFORE any storage, LLM calls, or embedding generation.

---

## 6. Policy Engine (Safety Guardrails)

### 6.1 Deny-by-Default Design

```
Rule Evaluation:
  1. Check rules in order (first match wins)
  2. If NO rule matches → DEFAULT DENY
  3. If policy engine ERRORS → DENY (fail-closed)
```

### 6.2 Risk Level Constraints

| Risk Level | Auto-Fix Allowed | Conditions |
|------------|-----------------|------------|
| `low` | ✅ Yes | High confidence, known failure type |
| `medium` | ⚠️ Limited | Per-rule basis, some types only |
| `high` | ❌ Never | Always denied |

### 6.3 Confidence Thresholds

| Failure Type | Min Confidence for Auto-Fix |
|-------------|---------------------------|
| Dependency Error | 0.70 |
| Import Error | 0.80 |
| Syntax Error | 0.90 |
| Config Error | 0.85 |
| All others | Denied |

---

## 7. LLM Security

### 7.1 Input Sanitization

- Logs are sanitized before LLM processing
- No raw secrets reach the LLM prompt
- Excerpt is truncated to prevent prompt overflow

### 7.2 Output Validation

- LLM responses parsed as JSON (structured output)
- `failure_type` validated against whitelist (10 known types)
- `confidence` validated as float in [0, 1]
- `risk_level` validated against `low/medium/high`
- Invalid responses → fallback to heuristic (no blind trust)

### 7.3 Temperature Control

| Step | Temperature | Rationale |
|------|-------------|-----------|
| Triage | 0.1 | Deterministic classification |
| Planner | 0.2 | Slightly creative for plan generation |

---

## 8. Network Security

### 8.1 External Connections

| Connection | Protocol | Authentication |
|-----------|----------|----------------|
| GitHub API | HTTPS | Installation Token |
| Groq API | HTTPS | API Key (header) |
| Qdrant | HTTP/HTTPS | Optional API Key |
| Gmail SMTP | TLS (port 587) | App Password |

### 8.2 AWS Security

- Lambda runs in VPC (optional, for Qdrant access)
- S3 bucket: no public access, default encryption
- SQS: no public access, IAM-only
- API Gateway: HTTPS only

---

## 9. Data Retention & Privacy

| Data | Retention | Encryption |
|------|-----------|------------|
| Raw CI logs | 30 days | S3 default (AES-256) |
| Excerpts | 90 days | S3 default |
| Artifacts | 180 days | S3 default |
| Embeddings | 1 year | S3 + Qdrant |
| Timeline | 180 days | S3 default |

---

## 10. Security Best Practices

| # | Practice | Implementation |
|---|----------|----------------|
| 1 | Never hardcode secrets | `.env` + env vars |
| 2 | Sanitize before storage | Sanitizer runs first |
| 3 | Validate webhook origin | HMAC-SHA256 |
| 4 | Deny by default | Policy engine |
| 5 | Short-lived tokens | JWT (10min), install token (~1hr) |
| 6 | Constant-time comparison | `hmac.compare_digest()` |
| 7 | Input validation | Pydantic models everywhere |
| 8 | Error masking | Don't expose internals in API responses |
| 9 | Git ignore secrets | `.gitignore` for `.env`, `.pem` |
| 10 | Least privilege IAM | SAM policies scoped to specific resources |
