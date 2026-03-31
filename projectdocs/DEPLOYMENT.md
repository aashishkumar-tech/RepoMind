# ☁️ Deployment Guide — RepoMind CI Auto-Fix Agent

## 1. Deployment Overview

RepoMind uses **AWS SAM (Serverless Application Model)** for infrastructure-as-code deployment. All resources are defined in `template.yaml`.

### 1.1 Architecture

```
┌─────────────────────────────────────────────┐
│              AWS Account                     │
│                                              │
│  ┌─ API Gateway ──────────────────────────┐  │
│  │  POST /webhook  →  WebhookFunction     │  │
│  │  GET  /health   →  WebhookFunction     │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ SQS ─────────────────────────────────┐  │
│  │  repomind-events     → WorkerFunction  │  │
│  │  repomind-events-dlq  (dead letters)   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ S3 ──────────────────────────────────┐  │
│  │  repomind-data-{AccountId}             │  │
│  │  Lifecycle: 180-day expiry on events/  │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Lambda ──────────────────────────────┐  │
│  │  repomind-webhook (256MB, 30s)         │  │
│  │  repomind-worker  (1024MB, 300s)       │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ CloudWatch ──────────────────────────┐  │
│  │  /aws/lambda/repomind-webhook          │  │
│  │  /aws/lambda/repomind-worker           │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

---

## 2. Prerequisites

| Requirement | Install |
|-------------|---------|
| Python 3.12+ | [python.org](https://www.python.org/downloads/) |
| uv | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| AWS CLI v2 | [Install Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| AWS SAM CLI | [Install Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) |
| Docker | [Install Guide](https://docs.docker.com/get-docker/) (needed for `sam build`) |
| AWS Account | [Free Tier Signup](https://aws.amazon.com/free/) |
| Configured credentials | `aws configure` |

---

## 3. Step-by-Step Deployment

### 3.1 Create SAM Deployment Bucket

```bash
aws s3 mb s3://repomind-sam-deployments --region ap-south-1
```

### 3.2 Build the Application

```bash
sam build
```

This creates a `.aws-sam/build/` directory with bundled Lambda packages.

### 3.3 Deploy (First Time — Guided)

```bash
sam deploy --guided
```

**Prompts:**

| Prompt | Suggested Value |
|--------|----------------|
| Stack name | `repomind` |
| Region | `ap-south-1` |
| GitHubAppId | Your GitHub App ID |
| GitHubInstallationId | Your Installation ID |
| GitHubWebhookSecret | Your webhook secret |
| GroqApiKey | Your Groq API key |
| Confirm deploy | `y` |
| Create IAM roles | `y` |
| Save config to samconfig.toml | `y` |

### 3.4 Deploy (Subsequent)

```bash
sam deploy
```

Uses saved `samconfig.toml` configuration.

### 3.5 Verify Deployment

```bash
# List stack outputs
sam list stack-outputs --stack-name repomind

# Expected outputs:
# WebhookUrl: https://xxxx.execute-api.ap-south-1.amazonaws.com/Prod/webhook
# EventQueueUrl: https://sqs.ap-south-1.amazonaws.com/.../repomind-events
# DataBucketName: repomind-data-123456789012
```

---

## 4. Post-Deployment Configuration

### 4.1 Configure GitHub Webhook

1. Go to your **GitHub App** → Settings
2. Set **Webhook URL** to the `WebhookUrl` from step 3.5
3. Set **Content type** to `application/json`
4. Set **Secret** to match `GITHUB_WEBHOOK_SECRET`
5. Select events: **Workflow runs**
6. Click **Save**

### 4.2 Upload Private Key

```bash
# The private key must be accessible to the Lambda function
# Option 1: Bundle with the code (simpler, less secure)
cp private-key.pem .aws-sam/build/WorkerFunction/

# Option 2: AWS SSM Parameter Store (recommended for production)
aws ssm put-parameter \
  --name "/repomind/github-private-key" \
  --type SecureString \
  --value file://private-key.pem
```

### 4.3 Test the Webhook

```bash
# Health check
curl https://xxxx.execute-api.ap-south-1.amazonaws.com/Prod/health

# Expected: {"status": "healthy", "service": "repomind-webhook"}
```

---

## 5. Monitoring

### 5.1 View Logs

```bash
# Webhook function logs (real-time)
sam logs -n WebhookFunction --stack-name repomind --tail

# Worker function logs
sam logs -n WorkerFunction --stack-name repomind --tail

# Filter for errors
sam logs -n WorkerFunction --stack-name repomind --filter "ERROR"
```

### 5.2 Check SQS Queue

```bash
# Queue depth
aws sqs get-queue-attributes \
  --queue-url https://sqs.ap-south-1.amazonaws.com/.../repomind-events \
  --attribute-names ApproximateNumberOfMessages

# Dead letter queue
aws sqs get-queue-attributes \
  --queue-url https://sqs.ap-south-1.amazonaws.com/.../repomind-events-dlq \
  --attribute-names ApproximateNumberOfMessages
```

### 5.3 Check S3 Artifacts

```bash
# List recent events
aws s3 ls s3://repomind-data-123456789012/events/ --recursive | tail -20

# Download an artifact
aws s3 cp s3://repomind-data-123456789012/events/myorg-repo/evt-.../artifacts.json .
```

---

## 6. Updating the Deployment

```bash
# Make code changes, then:
sam build && sam deploy
```

---

## 7. Teardown

```bash
# Delete the stack (removes all resources)
sam delete --stack-name repomind

# Manually empty and delete S3 bucket if needed
aws s3 rb s3://repomind-data-123456789012 --force
```

---

## 8. Production Checklist

| # | Item | Status |
|---|------|--------|
| 1 | All env vars configured in SAM parameters | ☐ |
| 2 | GitHub App installed on target repos | ☐ |
| 3 | Webhook URL set in GitHub App | ☐ |
| 4 | Private key deployed securely (SSM preferred) | ☐ |
| 5 | S3 lifecycle policies active | ☐ |
| 6 | DLQ monitoring alarm configured | ☐ |
| 7 | CloudWatch alarms for Lambda errors | ☐ |
| 8 | Policy rules reviewed for target repos | ☐ |
| 9 | Qdrant cluster running (if using vector search) | ☐ |
| 10 | Dry-run test completed successfully | ☐ |

---

## 9. Cost Monitoring

```bash
# Check AWS billing (monthly)
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-02-28 \
  --granularity MONTHLY \
  --metrics "BlendedCost" \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["AWS Lambda","Amazon Simple Queue Service","Amazon Simple Storage Service"]}}'
```

**Expected:** $0/month within AWS Free Tier limits.
