"""
tests/test_sanitizer.py — Unit tests for log sanitization
"""

from step2.sanitizer import Sanitizer


class TestSanitizer:
    def setup_method(self):
        self.sanitizer = Sanitizer()

    def test_aws_access_key(self):
        text = "Using key AKIAIOSFODNN7EXAMPLE for access"
        result = self.sanitizer.sanitize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED:aws_access_key]" in result

    def test_github_token(self):
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = self.sanitizer.sanitize(text)
        assert "ghp_" not in result

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.sig"
        result = self.sanitizer.sanitize(text)
        assert "Bearer eyJ" not in result

    def test_email(self):
        text = "Contact admin@example.com for help"
        result = self.sanitizer.sanitize(text)
        assert "admin@example.com" not in result
        assert "[REDACTED:email]" in result

    def test_connection_string(self):
        text = "DATABASE_URL=postgres://user:pass@host:5432/db"
        result = self.sanitizer.sanitize(text)
        assert "postgres://user:pass" not in result

    def test_no_false_positive_on_normal_text(self):
        text = "Build completed successfully\nAll tests passed\n42 assertions"
        result = self.sanitizer.sanitize(text)
        assert result == text  # Nothing should be redacted

    def test_multiple_secrets(self):
        text = (
            "KEY=AKIAIOSFODNN7EXAMPLE\n"
            "email: test@test.com\n"
            "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh\n"
        )
        result = self.sanitizer.sanitize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "test@test.com" not in result
        assert "ghp_" not in result

    def test_private_ip(self):
        text = "Connecting to 192.168.1.100"
        result = self.sanitizer.sanitize(text)
        assert "192.168.1.100" not in result
        assert "[REDACTED:private_ip]" in result
