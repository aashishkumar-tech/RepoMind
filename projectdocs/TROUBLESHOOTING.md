# 🔧 Troubleshooting Guide — RepoMind CI Auto-Fix Agent

## 1. Common Issues

### 1.1 Installation Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `ModuleNotFoundError` | Dependencies not installed | `uv pip install -r requirements.txt` |
| `uv` command not found | uv not installed | Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` / Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `sentence-transformers` takes forever | Downloads PyTorch (~2GB) | Wait; it's a one-time download |
| SSL errors on install | Corporate proxy/firewall | Use `uv pip install` (handles SSL better) or: `pip install --trusted-host pypi.org -r requirements.txt` |
| Python version mismatch | Python < 3.10 | Install Python 3.12: [python.org](https://www.python.org/downloads/) or `uv python install 3.12` |
| `.venv` activation fails (Windows) | PowerShell execution policy | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |

### 1.2 Configuration Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `.env not loading` | Wrong location | Ensure `.env` is in project root (same level as `run_local.py`) |
| `Missing required env var` | Not set in `.env` | Copy from `.env.example`, fill all required values |
| `GITHUB_PRIVATE_KEY_PATH` error | File not found | Place `private-key.pem` in project root |
| `GROQ_API_KEY` empty | Not configured | Get free key from [console.groq.com](https://console.groq.com) |

### 1.3 Local Development Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| Port 8000 already in use | Another process running | Kill: `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F` |
| Webhook returns 401 | Invalid signature | In dev mode, check if signature validation is too strict |
| Triage returns "unknown" | No LLM available | Set `GROQ_API_KEY` or rely on keyword fallback |
| No artifacts saved | Storage not configured | In dev mode, check `./data/` directory exists |
| Connection refused on Qdrant | Qdrant not running | Start Docker: `docker run -p 6333:6333 qdrant/qdrant` |

### 1.4 AWS Deployment Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `sam build` fails | Docker not running | Start Docker Desktop |
| `sam deploy` permission error | IAM insufficient | Add `AWSLambdaFullAccess`, `AmazonS3FullAccess`, `AmazonSQSFullAccess` |
| Lambda timeout | Processing takes too long | Increase timeout in `template.yaml` (max 900s) |
| S3 AccessDenied | Missing bucket policy | Check SAM template `S3CrudPolicy` is set |
| SQS message not received | Batch size or visibility | Check `VisibilityTimeout` > Lambda timeout |

### 1.5 Pipeline Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| Logs empty / fetch fails | GitHub API rate limit | Check rate limit: `curl -H "Authorization: token xxx" https://api.github.com/rate_limit` |
| Triage always returns `unknown` | Groq API error | Check `GROQ_API_KEY`, check Groq status page |
| Policy always denies | Rules too strict | Review `policy/default.yaml`, adjust confidence thresholds |
| PR not created | Policy denied | Check artifacts.json → `policy.decision` |
| PR creation fails | GitHub permissions | Check GitHub App has `Contents: write` and `Pull requests: write` |

---

## 2. Debugging Steps

### 2.1 Check Configuration

```bash
# Verify Python
python --version

# Verify imports
python -c "from shared.config import settings; print(settings.ENVIRONMENT)"

# Verify .env is loaded
python -c "from shared.config import settings; print('APP_ID:', settings.GITHUB_APP_ID)"
```

### 2.2 Check Local Server

```bash
# Start server
python run_local.py

# In another terminal:
curl http://localhost:8080/health
# Expected: {"status": "healthy", "service": "repomind-webhook"}
```

### 2.3 Check Pipeline Steps

```bash
# Run pipeline simulation
python test_local_pipeline.py

# Run specific tests
pytest tests/test_triage.py -v -s
pytest tests/test_policy.py -v -s
```

### 2.4 Check AWS Logs

```bash
# Real-time logs
sam logs -n WebhookFunction --stack-name repomind --tail
sam logs -n WorkerFunction --stack-name repomind --tail

# Filter errors
sam logs -n WorkerFunction --stack-name repomind --filter ERROR

# Check DLQ
aws sqs get-queue-attributes \
  --queue-url <dlq-url> \
  --attribute-names ApproximateNumberOfMessages
```

### 2.5 Check S3 Artifacts

```bash
# List events
aws s3 ls s3://repomind-data-123456789012/events/ --recursive

# Read a specific artifact
aws s3 cp s3://repomind-data-123456789012/events/<slug>/<event-id>/artifacts.json -

# Read timeline
aws s3 cp s3://repomind-data-123456789012/events/<slug>/<event-id>/timeline.json -
```

---

## 3. Error Messages Reference

| Error Message | Module | Cause | Fix |
|--------------|--------|-------|-----|
| `Invalid webhook signature` | step1/signature.py | HMAC mismatch | Verify `GITHUB_WEBHOOK_SECRET` matches GitHub App setting |
| `Not a failed workflow run` | step1/webhook_handler.py | Event is not a failure | Normal — only failures are processed |
| `Failed to fetch logs` | step2/log_fetcher.py | GitHub API error | Check GitHub token, repo permissions, rate limits |
| `Triage fallback to heuristic` | step5/triage.py | Groq API unavailable | Check `GROQ_API_KEY`, Groq service status |
| `Policy denied` | step7/policy.py | Safety rules blocked fix | Review policy rules, adjust thresholds |
| `PR creation failed` | step8/pr_creator.py | GitHub API error | Check App permissions (Contents + PRs) |
| `Qdrant connection failed` | step3/indexer.py | Qdrant not running | Start Qdrant or skip vector indexing |
| `Collection not found` | step3/retriever.py | No data indexed yet | Run indexer first or ignore for new deployments |

---

## 4. FAQ

### Q: Can I run without Groq API key?

**A:** Yes, for development. Triage and Planner will fall back to keyword/template heuristics. Results won't be as accurate but the pipeline still works.

### Q: Can I run without Qdrant?

**A:** Yes. Vector indexing will be skipped with a warning. The pipeline still processes failures and creates PRs.

### Q: Can I run without AWS?

**A:** Yes. Set `ENVIRONMENT=development`. Storage uses local filesystem (`./data/`), queue logs messages locally. Perfect for development.

### Q: Why does policy always deny my fixes?

**A:** Check:

1. Is the `failure_type` in the allowed list? (Only dependency, import, syntax, config errors are auto-allowed)
2. Is the `confidence` above the threshold? (0.7–0.9 depending on type)
3. Is the `risk_level` "low"? (Medium and high are denied)
4. Review `policy/default.yaml` and adjust rules if needed.

### Q: How do I add a new failure type?

**A:**

1. Add to `FAILURE_TYPES` list in `step5/triage.py`
2. Add keyword patterns in `_keyword_fallback()`
3. Add a policy rule in `policy/default.yaml`
4. Add a test in `tests/test_triage.py`

### Q: How do I add support for a new repository?

**A:**

1. Install the GitHub App on the repository
2. Optionally create `policy/<org>-<repo>.yaml` for custom rules
3. Add to `repos.yaml` if maintaining a registry

### Q: The first run is very slow. Why?

**A:** First run downloads the `all-MiniLM-L6-v2` model (~90MB). Subsequent runs use the cached model and are much faster.

---

## 5. Getting Help

1. **Check logs:** Always start with the logs (terminal or CloudWatch)
2. **Run tests:** `pytest tests/ -v -s` to isolate the issue
3. **Check artifacts:** Look at `artifacts.json` and `timeline.json` in S3
4. **Review policy:** `policy/default.yaml` for blocked fixes
5. **Open an issue:** Provide logs, artifacts, and error messages
