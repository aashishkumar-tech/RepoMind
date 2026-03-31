# 📦 Installation Guide — RepoMind CI Auto-Fix Agent

## 1. Prerequisites

### 1.1 Required Software

| Software | Version | Purpose | Install |
|----------|---------|---------|---------|
| **Python** | 3.10+ (3.12 recommended) | Runtime | [python.org](https://www.python.org/downloads/) |
| **uv** | Latest | Fast Python package & project manager | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Git** | 2.x+ | Version control | [git-scm.com](https://git-scm.com/) |
| **AWS CLI** | 2.x | AWS deployment | [AWS CLI Install](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **AWS SAM CLI** | 1.x | Serverless deployment | [SAM CLI Install](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) |

### 1.2 Required Accounts (Free)

| Account | Purpose | Sign Up |
|---------|---------|---------|
| **GitHub Account** | Source code, GitHub App | [github.com](https://github.com) |
| **AWS Account** | Lambda, SQS, S3, API Gateway | [aws.amazon.com](https://aws.amazon.com/free/) |
| **Groq Account** | Free LLM API access | [console.groq.com](https://console.groq.com) |
| **Qdrant Cloud** *(optional)* | Managed vector DB | [cloud.qdrant.io](https://cloud.qdrant.io) |

---

## 2. Clone the Repository

```bash
git clone https://github.com/your-org/RepoMind.git
cd RepoMind
```

---

## 3. Install uv (Package Manager)

**uv** is an extremely fast Python package and project manager written in Rust. It replaces `pip`, `pip-tools`, `virtualenv`, and more — in a single tool.

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Linux / macOS
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Verify Installation
```bash
uv --version
```

> **Why uv?** It is 10–100x faster than pip, handles virtual environments automatically, and provides deterministic dependency resolution.

---

## 4. Python Environment Setup

### Option A: uv (Recommended — Fastest)

```bash
# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source .venv/bin/activate
```

> **Note:** `uv venv` creates a `.venv` directory by default. If you prefer a custom name: `uv venv myenv`

### Option B: Standard venv

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source .venv/bin/activate
```

### Option C: Conda

```bash
conda create -n repomind python=3.12 -y
conda activate repomind
```

---

## 5. Install Dependencies

### Using uv (Recommended — ~10x faster than pip)

```bash
uv pip install -r requirements.txt
```

### Using pip (Alternative)

```bash
pip install -r requirements.txt
```

This installs all packages:
- `fastapi`, `uvicorn`, `mangum` — Web framework
- `boto3` — AWS SDK
- `PyGithub`, `PyJWT`, `cryptography` — GitHub integration
- `httpx`, `tenacity` — HTTP + retry
- `groq` — LLM SDK
- `sentence-transformers` — Embedding model
- `qdrant-client` — Vector DB
- `langgraph` — Pipeline orchestration
- `structlog` — Logging
- `pytest`, `pytest-asyncio`, `pytest-cov` — Testing

> **Note:** First run will download the `all-MiniLM-L6-v2` model (~90MB). This is automatic.

---

## 6. Environment Configuration

### 6.1 Create `.env` File

```bash
# Copy the example
cp .env.example .env
```

### 6.2 Fill in Values

Edit `.env` with your credentials:

```bash
# ── AWS ──
AWS_REGION=ap-south-1
AWS_ACCOUNT_ID=123456789012
S3_SAM_BUCKET=repomind-sam-deployments
S3_DATA_BUCKET=repomind-data

# ── GitHub App ──
GITHUB_APP_ID=your_app_id
GITHUB_INSTALLATION_ID=your_installation_id
GITHUB_PRIVATE_KEY_PATH=private-key.pem
GITHUB_WEBHOOK_SECRET=your_webhook_secret

# ── Groq LLM ──
GROQ_API_KEY=gsk_your_groq_api_key

# ── Email Notifications ──
GMAIL_ADDRESS=your.email@gmail.com
GMAIL_APP_PASSWORD=your_app_password
NOTIFICATION_EMAILS=team@example.com

# ── Qdrant ──
QDRANT_HOST=localhost
QDRANT_PORT=6333

# ── App ──
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

---

## 7. GitHub App Setup

### 7.1 Create a GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Fill in:
   - **Name:** `RepoMind CI AutoFix`
   - **Homepage URL:** `https://github.com/your-org/RepoMind`
   - **Webhook URL:** Your API Gateway URL (or `https://smee.io/...` for local dev)
   - **Webhook Secret:** Generate a strong secret, save to `.env`
3. **Permissions:**
   - Repository: `Contents` → Read & Write
   - Repository: `Pull requests` → Read & Write
   - Repository: `Actions` → Read
   - Repository: `Metadata` → Read
4. **Subscribe to events:** `Workflow run`
5. **Generate Private Key** → Download `.pem` file → Save as `private-key.pem` in project root

### 7.2 Install the App

1. Go to your GitHub App → **Install App**
2. Select repositories to monitor
3. Note the **Installation ID** from the URL → Save to `.env`

---

## 8. AWS Configuration

### 8.1 Configure AWS CLI

```bash
aws configure
# Enter: Access Key ID, Secret Access Key, Region (ap-south-1), Output format (json)
```

### 8.2 Create S3 Buckets

```bash
# SAM deployment bucket
aws s3 mb s3://repomind-sam-deployments --region ap-south-1

# Data bucket (or let SAM create it)
aws s3 mb s3://repomind-data-YOUR_ACCOUNT_ID --region ap-south-1
```

---

## 9. Qdrant Setup (Optional — for Vector Search)

### Option A: Docker (Recommended for Local Dev)

```bash
docker run -p 6333:6333 qdrant/qdrant
```

### Option B: Qdrant Cloud Free Tier

1. Sign up at [cloud.qdrant.io](https://cloud.qdrant.io)
2. Create a free cluster
3. Update `.env`:
   ```
   QDRANT_HOST=your-cluster.qdrant.io
   QDRANT_PORT=6333
   ```

### Option C: Skip (Development Only)

Vector indexing will log warnings but won't block the pipeline.

---

## 10. Verify Installation

```bash
# Check Python version
python --version

# Check uv version
uv --version

# Check all imports work
python -c "import fastapi, boto3, groq, structlog, qdrant_client; print('All imports OK!')"

# Run tests
pytest tests/ -v

# Start local server
python run_local.py
```

---

## 11. Troubleshooting Installation

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `uv pip install -r requirements.txt` again |
| `sentence-transformers` slow install | Normal — downloads PyTorch (~2GB first time) |
| `.env` not loading | Ensure file is in project root, not `.env.example` |
| AWS credentials error | Run `aws configure` or check `~/.aws/credentials` |
| GitHub private key error | Ensure `private-key.pem` exists and path is correct in `.env` |
| Qdrant connection refused | Start Docker container or skip for dev mode |
| `uv` not found | Reinstall: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| `pip` SSL error (Windows) | Use `uv pip install` instead (handles SSL better), or: `pip install --trusted-host pypi.org -r requirements.txt` |
| `.venv` activation fails (Windows) | Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
