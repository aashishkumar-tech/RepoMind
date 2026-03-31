# ⚙️ Configuration Guide — RepoMind CI Auto-Fix Agent

## 1. Environment Variables

All configuration is managed through environment variables, loaded from a `.env` file in the project root.

### 1.1 Complete Variable Reference

#### AWS Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | No | `ap-south-1` | AWS region for all services |
| `AWS_ACCOUNT_ID` | Prod only | *(empty)* | AWS account ID |
| `S3_SAM_BUCKET` | Prod only | `repomind-sam-deployments` | S3 bucket for SAM artifacts |
| `S3_DATA_BUCKET` | Prod only | `repomind-data` | S3 bucket for event data |

#### GitHub App Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_APP_ID` | Yes | *(empty)* | GitHub App ID |
| `GITHUB_INSTALLATION_ID` | Yes | *(empty)* | Installation ID for the target org/repo |
| `GITHUB_PRIVATE_KEY_PATH` | Yes | `private-key.pem` | Path to GitHub App private key file |
| `GITHUB_WEBHOOK_SECRET` | Yes | *(empty)* | Webhook HMAC secret for signature validation |

#### LLM Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | *(empty)* | Groq API key for LLM access |

#### Email Notifications

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GMAIL_ADDRESS` | No | *(empty)* | Gmail sender address |
| `GMAIL_APP_PASSWORD` | No | *(empty)* | Gmail App Password (NOT regular password) |
| `NOTIFICATION_EMAILS` | No | *(empty)* | Comma-separated recipient list |

#### Vector Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `QDRANT_HOST` | No | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | No | `6333` | Qdrant server port |

#### Application Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENVIRONMENT` | No | `development` | `development` or `production` |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `TARGET_REPO` | No | *(empty)* | Target repo for testing (e.g., `owner/repo`) |

#### Observability & Monitoring

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `METRICS_ENABLED` | No | `false` | Enable Prometheus metrics recording |
| `PUSHGATEWAY_URL` | No | *(empty)* | Pushgateway endpoint (e.g., `http://localhost:9091`) |
| `KILL_SWITCH_PARAM` | No | `/repomind/kill_switch` | SSM parameter name for global kill switch |

#### Verification & Rollback (Step 10)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VERIFICATION_ENABLED` | No | `true` | Enable post-PR CI verification |
| `MAX_ROLLBACKS_PER_HOUR` | No | `3` | Max revert PRs per repo per hour (rate limit) |

---

### 1.2 Setup `.env` File

```bash
# Copy the template
cp .env.example .env

# Edit with your values
notepad .env          # Windows
# nano .env           # Linux
# code .env           # VS Code
```

### 1.3 Required vs Optional

**Minimum for local development (no AWS):**
```bash
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

**Minimum for full pipeline:**
```bash
GITHUB_APP_ID=123456
GITHUB_INSTALLATION_ID=789012
GITHUB_PRIVATE_KEY_PATH=private-key.pem
GITHUB_WEBHOOK_SECRET=your-secret
GROQ_API_KEY=gsk_your_key
```

**For AWS deployment:**
```bash
AWS_REGION=ap-south-1
AWS_ACCOUNT_ID=123456789012
S3_DATA_BUCKET=repomind-data-123456789012
```

**For observability (Step 11):**
```bash
METRICS_ENABLED=true
PUSHGATEWAY_URL=http://localhost:9091
KILL_SWITCH_PARAM=/repomind/kill_switch
```

**For verification (Step 10):**
```bash
VERIFICATION_ENABLED=true
MAX_ROLLBACKS_PER_HOUR=3
```

---

## 2. Policy Configuration

### 2.1 File Location

```
policy/
  default.yaml       ← Default policy (always loaded)
  myorg-service-a.yaml   ← Repo-specific override (optional)
```

### 2.2 Policy Schema

```yaml
version: 1
scope:
  description: "Human-readable description"

defaults:
  allow_auto_fix: false        # Global default
  max_risk_level: "medium"     # Max allowed risk

rules:                         # Ordered list — first match wins
  - id: rule_identifier        # Unique ID
    description: "..."         # Human-readable
    when:                      # Match criteria
      failure_types: [...]     # List of failure types to match
      max_risk_level: "low"    # Max risk for this rule
      min_confidence: 0.7      # Min triage confidence
    decision: "allow"          # allow | deny | manual_review
```

### 2.3 Current Default Rules

| # | Rule ID | Matches | Decision |
|---|---------|---------|----------|
| 1 | `allow_low_risk_dependency_fix` | dependency_error, risk≤low, conf≥0.7 | ✅ Allow |
| 2 | `allow_import_fix` | import_error, risk≤low, conf≥0.8 | ✅ Allow |
| 3 | `allow_syntax_fix` | syntax_error, risk≤low, conf≥0.9 | ✅ Allow |
| 4 | `allow_config_fix` | config_error, risk≤low, conf≥0.85 | ✅ Allow |
| 5 | `deny_high_risk` | risk≥high | ❌ Deny |
| 6 | `deny_low_confidence` | conf≤0.5 | ❌ Deny |
| 7 | `default_deny` | everything else | ❌ Deny |

### 2.4 Adding Custom Rules

Add a new rule before `default_deny`:

```yaml
rules:
  # ... existing rules ...
  
  - id: allow_test_fix_on_staging
    description: "Allow test fixes on staging repos"
    when:
      failure_types: ["test_failure"]
      max_risk_level: "medium"
      min_confidence: 0.75
    decision: "allow"
  
  - id: default_deny
    # ... keep this last
```

---

## 3. Repository Configuration

### 3.1 File: `repos.yaml`

Lists target repositories the system monitors:

```yaml
repos:
  - name: "myorg/service-a"
    enabled: true
  - name: "myorg/service-b"
    enabled: true
```

---

## 4. AWS SAM Configuration

### 4.1 File: `template.yaml`

**Deploy-time Parameters:**

| Parameter | Description | NoEcho |
|-----------|-------------|--------|
| `GitHubAppId` | GitHub App ID | No |
| `GitHubInstallationId` | Installation ID | No |
| `GitHubWebhookSecret` | Webhook HMAC secret | Yes |
| `GroqApiKey` | Groq API key | Yes |

**Lambda Settings:**

| Function | Memory | Timeout | Trigger |
|----------|--------|---------|---------|
| `WebhookFunction` | 256 MB | 30s | API Gateway POST |
| `WorkerFunction` | 1024 MB | 300s | SQS (batch=1) |

**S3 Lifecycle:**

| Prefix | Retention |
|--------|-----------|
| `events/` | 180 days |

---

## 5. Logging Configuration

### 5.1 Log Levels

| Level | When to Use |
|-------|-------------|
| `DEBUG` | Local development (verbose) |
| `INFO` | Standard operation (default) |
| `WARNING` | Non-critical issues |
| `ERROR` | Failures requiring attention |

### 5.2 Log Format

**Development:** Colored console output
```
2026-02-13 15:44:00 [INFO] step2.worker: Processing event evt-...
```

**Production:** JSON for CloudWatch
```json
{"timestamp": "2026-02-13T15:44:00Z", "level": "info", "logger": "step2.worker", "event": "Processing event", "event_id": "evt-..."}
```

---

## 6. Configuration Precedence

```
1. Environment Variables (highest priority)
2. .env file
3. Code defaults (lowest priority)
```

The `Settings.from_env()` method reads each variable with fallback:
```python
os.getenv("VARIABLE_NAME", "default_value")
```
