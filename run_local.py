"""
run_local.py — Local Development Server

HOW TO USE:
───────────
    python run_local.py

This starts the FastAPI webhook server locally on http://localhost:8080

You can test with:
    POST http://localhost:8080/webhook  (simulated GitHub event)
    GET  http://localhost:8080/health   (health check)
    GET  http://localhost:8080/docs     (Swagger UI)

In development mode:
    - Storage uses local filesystem (./data/)
    - Queue logs messages locally (no SQS)
    - All artifacts are written to ./data/events/...
"""

import uvicorn
from step1.webhook_handler import app

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🚀 RepoMind CI Auto-Fix Agent — Local Dev Server")
    print("=" * 60)
    print("  Webhook:  http://localhost:8080/webhook")
    print("  Health:   http://localhost:8080/health")
    print("  Docs:     http://localhost:8080/docs")
    print("=" * 60 + "\n")

    uvicorn.run(
        "step1.webhook_handler:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
    )
