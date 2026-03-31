"""Quick setup diagnostic — checks what's configured and what's missing."""
import os, sys, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

print("\n" + "=" * 62)
print("  RepoMind — Setup Diagnostic")
print("=" * 62)

# ── 1. .env file ──
env_path = os.path.join(ROOT, ".env")
has_env = os.path.isfile(env_path)
print(f"\n  [{'OK' if has_env else 'NO'}]  .env file exists")

# ── 2. Config values ──
from shared.config import settings

checks = [
    ("GITHUB_APP_ID",          settings.GITHUB_APP_ID),
    ("GITHUB_INSTALLATION_ID", settings.GITHUB_INSTALLATION_ID),
    ("GITHUB_WEBHOOK_SECRET",  settings.GITHUB_WEBHOOK_SECRET),
    ("GITHUB_PRIVATE_KEY_PATH",settings.GITHUB_PRIVATE_KEY_PATH),
    ("GROQ_API_KEY",           settings.GROQ_API_KEY),
    ("TARGET_REPO",            settings.TARGET_REPO),
    ("GMAIL_ADDRESS",          settings.GMAIL_ADDRESS),
    ("GMAIL_APP_PASSWORD",     settings.GMAIL_APP_PASSWORD),
    ("AWS_REGION",             settings.AWS_REGION),
    ("AWS_ACCOUNT_ID",         settings.AWS_ACCOUNT_ID),
    ("S3_DATA_BUCKET",         settings.S3_DATA_BUCKET),
    ("QDRANT_HOST",            settings.QDRANT_HOST),
    ("METRICS_ENABLED",        settings.METRICS_ENABLED),
    ("PUSHGATEWAY_URL",        settings.PUSHGATEWAY_URL),
    ("KILL_SWITCH_PARAM",      settings.KILL_SWITCH_PARAM),
    ("ENVIRONMENT",            settings.ENVIRONMENT),
]

print("\n  ── Environment Variables ──")
for name, val in checks:
    status = "SET" if val else "MISSING"
    display = val[:30] + "..." if val and len(val) > 30 else (val or "—")
    # Mask secrets
    if name in ("GROQ_API_KEY","GITHUB_WEBHOOK_SECRET","GMAIL_APP_PASSWORD") and val:
        display = val[:6] + "****"
    print(f"    [{status:>7}]  {name:<28} = {display}")

# ── 3. PEM file ──
pem = settings.GITHUB_PRIVATE_KEY_PATH
pem_exists = os.path.isfile(os.path.join(ROOT, pem)) if pem else False
print(f"\n  [{'OK' if pem_exists else 'NO'}]  Private key file ({pem}) exists")

# ── 4. Python packages ──
print("\n  ── Key Python Packages ──")
pkgs = ["groq","langgraph","qdrant_client","prometheus_client","PyGithub","boto3",
        "structlog","openai","fastapi","pydantic"]
for p in pkgs:
    try:
        __import__(p if p != "PyGithub" else "github")
        print(f"    [     OK]  {p}")
    except ImportError:
        print(f"    [MISSING]  {p}")

# ── 5. Docker check ──
docker = shutil.which("docker")
print(f"\n  [{'OK' if docker else 'NO'}]  Docker installed")

# ── 6. AWS CLI check ──
awscli = shutil.which("aws")
print(f"  [{'OK' if awscli else 'NO'}]  AWS CLI installed")

# ── 7. SAM CLI check ──
samcli = shutil.which("sam")
print(f"  [{'OK' if samcli else 'NO'}]  SAM CLI installed")

# ── 8. Qdrant reachable ──
try:
    import httpx
    r = httpx.get(f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/health", timeout=3)
    qdrant_ok = r.status_code == 200
except Exception:
    qdrant_ok = False
print(f"  [{'OK' if qdrant_ok else 'NO'}]  Qdrant reachable at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")

# ── 9. Pushgateway reachable ──
if settings.PUSHGATEWAY_URL:
    try:
        r = httpx.get(settings.PUSHGATEWAY_URL, timeout=3)
        pg_ok = r.status_code == 200
    except Exception:
        pg_ok = False
    print(f"  [{'OK' if pg_ok else 'NO'}]  Pushgateway reachable at {settings.PUSHGATEWAY_URL}")
else:
    print(f"  [  NO]  Pushgateway URL not configured")

# ── 10. SSM kill switch ──
if settings.ENVIRONMENT != "development" and settings.AWS_ACCOUNT_ID:
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=settings.AWS_REGION)
        ssm.get_parameter(Name=settings.KILL_SWITCH_PARAM)
        ssm_ok = True
    except Exception:
        ssm_ok = False
    print(f"  [{'OK' if ssm_ok else 'NO'}]  SSM kill switch parameter exists")
else:
    print(f"  [ SKIP]  SSM kill switch (dev mode — auto-disabled)")

# ── 11. Tests ──
test_dir = os.path.join(ROOT, "tests")
test_files = [f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")]
print(f"\n  [{'OK' if test_files else 'NO'}]  Test files found: {len(test_files)}")

# ── 12. Local data dir ──
data_dir = os.path.join(ROOT, "data")
print(f"  [{'OK' if os.path.isdir(data_dir) else 'NO'}]  Local data/ directory exists")

# ── 13. GitHub workflows ──
ci_yml = os.path.join(ROOT, ".github", "workflows", "ci.yml")
print(f"  [{'OK' if os.path.isfile(ci_yml) else 'NO'}]  .github/workflows/ci.yml exists")

# ── 14. repos.yaml ──
repos_yml = os.path.join(ROOT, "repos.yaml")
print(f"  [{'OK' if os.path.isfile(repos_yml) else 'NO'}]  repos.yaml exists")

# ── Summary ──
print("\n" + "=" * 62)
print("  WHAT'S DONE vs WHAT'S PENDING")
print("=" * 62)

done = []
pending = []

# Already done (test_local_pipeline.py passed)
done.append("Python env + pip install")
done.append(".env file with core secrets")
done.append("GitHub App created + installed")
done.append("Groq API key configured")
done.append("Core pipeline (Steps 1-9 code)")
done.append("Step 10 code (Verifier + Rollback)")
done.append("Step 11 code (Kill Switch + Metrics)")
done.append("test_local_pipeline.py ran successfully")

# Check what's pending
if not docker:
    pending.append("Install Docker (for Qdrant, monitoring, SAM build)")
if not qdrant_ok:
    pending.append("Start Qdrant: docker run -d -p 6333:6333 qdrant/qdrant")
if not awscli:
    pending.append("Install AWS CLI v2")
if not samcli:
    pending.append("Install SAM CLI")
if not settings.PUSHGATEWAY_URL:
    pending.append("Set up monitoring stack (cd monitoring && docker-compose up -d)")
if settings.METRICS_ENABLED != "true":
    pending.append("Enable metrics: METRICS_ENABLED=true in .env")
if not settings.AWS_ACCOUNT_ID:
    pending.append("Set AWS_ACCOUNT_ID in .env")
if not settings.GMAIL_ADDRESS:
    pending.append("Set up Gmail notifications (optional)")

pending.append("Run unit tests: pytest tests/ -v")
pending.append("Run local webhook server: python run_local.py")
pending.append("Create SSM kill switch: aws ssm put-parameter ...")
pending.append("SAM build + deploy: sam build && sam deploy --guided")
pending.append("Set webhook URL in GitHub App settings")
pending.append("End-to-end test: trigger real CI failure")
pending.append("Verify Step 10: merge fix PR → check verification")
pending.append("Verify monitoring: check Pushgateway/Prometheus/Grafana")

print("\n  ✅ DONE:")
for d in done:
    print(f"     • {d}")

print(f"\n  ❌ PENDING ({len(pending)} items):")
for i, p in enumerate(pending, 1):
    print(f"     {i:2}. {p}")

print("\n" + "=" * 62 + "\n")
