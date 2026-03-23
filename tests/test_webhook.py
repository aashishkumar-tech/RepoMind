"""
tests/test_webhook.py — Integration tests for the webhook endpoint
"""

import json
import hmac
import hashlib

import pytest
from fastapi.testclient import TestClient

from step1.webhook_handler import app
from shared.config import settings


@pytest.fixture
def client():
    return TestClient(app)


def _sign_payload(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_headers(payload: bytes, event_type: str = "workflow_run") -> dict:
    """Build request headers with proper signature if webhook secret is configured."""
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event_type,
    }
    if settings.GITHUB_WEBHOOK_SECRET:
        headers["X-Hub-Signature-256"] = _sign_payload(payload, settings.GITHUB_WEBHOOK_SECRET)
    else:
        headers["X-Hub-Signature-256"] = ""
    return headers


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "repomind-webhook"


class TestWebhookEndpoint:
    def test_non_workflow_event_ignored(self, client):
        payload = json.dumps({"action": "created"}).encode()
        response = client.post(
            "/webhook",
            content=payload,
            headers=_make_headers(payload, event_type="push"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_successful_workflow_not_failure(self, client):
        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 12345,
                "conclusion": "success",
                "html_url": "https://github.com/user/repo/actions/runs/12345",
            },
            "repository": {
                "id": 1,
                "full_name": "user/repo",
            },
        }
        body = json.dumps(payload).encode()
        response = client.post(
            "/webhook",
            content=body,
            headers=_make_headers(body, event_type="workflow_run"),
        )
        assert response.status_code == 200
        assert "ignored" in response.json()["status"]

    def test_failed_workflow_accepted(self, client):
        payload = {
            "action": "completed",
            "workflow_run": {
                "id": 12345,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/user/repo/actions/runs/12345",
                "head_branch": "main",
                "head_sha": "abc123",
            },
            "repository": {
                "id": 1,
                "full_name": "user/repo",
                "html_url": "https://github.com/user/repo",
                "default_branch": "main",
            },
        }
        body = json.dumps(payload).encode()
        response = client.post(
            "/webhook",
            content=body,
            headers=_make_headers(body, event_type="workflow_run"),
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "event_id" in data
        assert data["event_id"].startswith("evt-")
