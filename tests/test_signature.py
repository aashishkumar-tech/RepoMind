"""
tests/test_signature.py — Unit tests for webhook signature validation
"""

import hmac
import hashlib
from step1.signature import validate_signature


def _make_signature(payload: bytes, secret: str) -> str:
    """Helper: create a valid GitHub-style HMAC-SHA256 signature."""
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


class TestSignatureValidation:
    """Tests for HMAC-SHA256 webhook signature validation."""

    def test_valid_signature(self):
        payload = b'{"action": "completed"}'
        secret = "test-secret-123"
        sig = _make_signature(payload, secret)
        assert validate_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = b'{"action": "completed"}'
        secret = "test-secret-123"
        wrong_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        assert validate_signature(payload, wrong_sig, secret) is False

    def test_empty_signature(self):
        payload = b'{"action": "completed"}'
        assert validate_signature(payload, "", "secret") is False

    def test_missing_prefix(self):
        payload = b'{"action": "completed"}'
        assert validate_signature(payload, "no-prefix-here", "secret") is False

    def test_different_payloads(self):
        secret = "my-secret"
        payload1 = b'{"a": 1}'
        payload2 = b'{"a": 2}'
        sig1 = _make_signature(payload1, secret)
        # Signature for payload1 should NOT validate payload2
        assert validate_signature(payload2, sig1, secret) is False

    def test_different_secrets(self):
        payload = b'{"test": true}'
        sig = _make_signature(payload, "secret-A")
        assert validate_signature(payload, sig, "secret-B") is False
