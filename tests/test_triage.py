"""
tests/test_triage.py — Unit tests for triage (heuristic mode)
"""

from step5.triage import TriageEngine


class TestHeuristicTriage:
    """Test the heuristic fallback (no LLM required)."""

    def setup_method(self):
        self.engine = TriageEngine()
        # Force heuristic by setting client to None
        self.engine._client = None

    def test_dependency_error(self):
        excerpt = "ModuleNotFoundError: No module named 'flask'\npip install flask"
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] in ("dependency_error", "import_error")
        assert result["confidence"] > 0

    def test_syntax_error(self):
        excerpt = "SyntaxError: invalid syntax\n  File 'app.py', line 42"
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] == "syntax_error"
        assert result["confidence"] > 0

    def test_test_failure(self):
        excerpt = "FAILED tests/test_app.py::test_api - AssertionError\n1 failed, 2 passed"
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] == "test_failure"

    def test_timeout(self):
        excerpt = "Operation timed out after 30 seconds\ndeadline exceeded"
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] == "timeout_error"

    def test_permission_error(self):
        excerpt = "Permission denied: /var/run/app.pid\nEACCES"
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] == "permission_error"

    def test_unknown(self):
        excerpt = "Process completed.\nDone."
        result = self.engine.classify(excerpt, "user/repo")
        assert result["failure_type"] == "unknown"
        assert result["confidence"] <= 0.5

    def test_result_structure(self):
        result = self.engine.classify("some error log", "user/repo")
        assert "failure_type" in result
        assert "confidence" in result
        assert "summary" in result
        assert isinstance(result["confidence"], float)
        assert 0 <= result["confidence"] <= 1
