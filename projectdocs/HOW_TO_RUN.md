# 🚀 How to Run — RepoMind CI Auto-Fix Agent

## 1. Quick Start (Local Development)

### 1.1 Start the Webhook Server

```bash
# Activate virtual environment first
.\.venv\Scripts\Activate.ps1    # Windows PowerShell
# ## 9. Common Commands Reference

| Task | Command |
|------|---------|
| Install uv | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Create virtual env | `uv venv --python 3.12` |
| Install dependencies | `uv pip install -r requirements.txt` |
| Activate venv (Windows) | `.\.venv\Scripts\Activate.ps1` |
| Activate venv (Linux) | `source .venv/bin/activate` |
| Start local server | `python run_local.py` |
| Run all tests | `pytest tests/ -v` |
| Run pipeline simulation | `python test_local_pipeline.py` |
| Build for AWS | `sam build` |
| Deploy to AWS | `sam deploy` |
| View AWS logs | `sam logs -n WorkerFunction --stack-name repomind --tail` |
| Check health | `curl http://localhost:8000/health` |
| Interactive API docs | Open `http://localhost:8000/docs` in browser |n/activate     # Linux/macOS

# Start the server
python run_local.py
```

**Output:**
```
============================================================
  🚀 RepoMind CI Auto-Fix Agent — Local Dev Server
============================================================
  Webhook:  http://localhost:8000/webhook
  Health:   http://localhost:8000/health
  Docs:     http://localhost:8000/docs
============================================================
```

### 1.2 Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `http://localhost:8000/webhook` | POST | Receive GitHub webhook events |
| `http://localhost:8000/health` | GET | Health check |
| `http://localhost:8000/docs` | GET | Swagger UI (interactive API docs) |

---

## 2. Test the Health Endpoint

```bash
# Using curl
curl http://localhost:8000/health

# Using PowerShell
Invoke-RestMethod -Uri http://localhost:8000/health

# Expected response:
# {"status": "healthy", "service": "repomind-webhook"}
```

---

## 3. Simulate a Webhook Event

```bash
# Using curl (Linux/macOS)
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: workflow_run" \
  -H "X-Hub-Signature-256: sha256=test" \
  -d '{
    "action": "completed",
    "workflow_run": {
      "id": 123456789,
      "name": "CI",
      "conclusion": "failure",
      "html_url": "https://github.com/test/repo/actions/runs/123456789",
      "head_branch": "main",
      "head_sha": "abc123"
    },
    "repository": {
      "full_name": "test/repo",
      "html_url": "https://github.com/test/repo"
    }
  }'
```

```powershell
# Using PowerShell
$body = @{
    action = "completed"
    workflow_run = @{
        id = 123456789
        name = "CI"
        conclusion = "failure"
        html_url = "https://github.com/test/repo/actions/runs/123456789"
        head_branch = "main"
        head_sha = "abc123"
    }
    repository = @{
        full_name = "test/repo"
        html_url = "https://github.com/test/repo"
    }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri http://localhost:8000/webhook `
  -Method POST `
  -ContentType "application/json" `
  -Headers @{"X-GitHub-Event"="workflow_run"; "X-Hub-Signature-256"="sha256=test"} `
  -Body $body
```

> **Note:** In development mode, signature validation may be relaxed. In production, the HMAC-SHA256 signature must be valid.

---

## 4. Run the Full Pipeline Locally

The test pipeline simulates the entire flow with a sample failed log:

```bash
python test_local_pipeline.py
```

This runs:
1. Excerpt generation from sample CI logs
2. Triage (failure classification)
3. Plan generation
4. Policy evaluation

**No AWS, GitHub, or Groq credentials required** — uses local fallbacks.

---

## 5. Run Tests

### 5.1 Run All Tests

```bash
pytest tests/ -v
```

### 5.2 Run Specific Test File

```bash
pytest tests/test_signature.py -v
pytest tests/test_triage.py -v
pytest tests/test_step3.py -v
pytest tests/test_step4.py -v
```

### 5.3 Run with Coverage

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

### 5.4 Run with Detailed Output

```bash
pytest tests/ -v -s --tb=long
```

---

## 6. Deploy to AWS

### 6.1 Build with SAM

```bash
sam build
```

### 6.2 Deploy (First Time — Guided)

```bash
sam deploy --guided
```

You'll be prompted for:
- Stack name: `repomind`
- Region: `ap-south-1`
- GitHubAppId, GitHubInstallationId, GitHubWebhookSecret, GroqApiKey

### 6.3 Deploy (Subsequent — Quick)

```bash
sam deploy
```

### 6.4 Get the Webhook URL

```bash
# After deployment, find the webhook URL in outputs
sam list stack-outputs --stack-name repomind

# Output:
# WebhookUrl: https://xxxx.execute-api.ap-south-1.amazonaws.com/Prod/webhook
```

### 6.5 Configure GitHub Webhook

1. Go to your GitHub App settings
2. Set **Webhook URL** to the API Gateway URL from step 6.4
3. Events should start flowing automatically

---

## 7. View Logs

### 7.1 Local Development
Logs appear in the terminal with colored output.

### 7.2 AWS CloudWatch
```bash
# View webhook function logs
sam logs -n WebhookFunction --stack-name repomind --tail

# View worker function logs
sam logs -n WorkerFunction --stack-name repomind --tail
```

---

## 8. Development Workflow

```
 ┌─────────────────────────────────────────┐
 │  1. Edit code                           │
 │  2. Run tests:  pytest tests/ -v        │
 │  3. Start server: python run_local.py   │
 │  4. Test webhook: curl POST /webhook    │
 │  5. Check logs in terminal              │
 │  6. Deploy: sam build && sam deploy      │
 └─────────────────────────────────────────┘
```

---

## 9. Common Commands Reference

| Task | Command |
|------|---------|
| Start local server | `python run_local.py` |
| Run all tests | `pytest tests/ -v` |
| Run pipeline simulation | `python test_local_pipeline.py` |
| Build for AWS | `sam build` |
| Deploy to AWS | `sam deploy` |
| View AWS logs | `sam logs -n WorkerFunction --stack-name repomind --tail` |
| Check health | `curl http://localhost:8000/health` |
| Interactive API docs | Open `http://localhost:8000/docs` in browser |
| Install dependencies | `pip install -r requirements.txt` |
| Activate venv (Windows) | `.\venv\Scripts\Activate.ps1` |
| Activate venv (Linux) | `source venv/bin/activate` |
