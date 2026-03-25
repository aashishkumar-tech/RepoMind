"""
tests/test_excerpt.py — Unit tests for excerpt generation
"""

from step2.excerpt import ExcerptGenerator


class TestExcerptGenerator:
    def setup_method(self):
        self.generator = ExcerptGenerator()

    def test_extracts_error_lines(self):
        log = "\n".join([
            "Installing dependencies...",
            "Step 1: Download",
            "Step 2: Build",
            "ERROR: ModuleNotFoundError: No module named 'flask'",
            "Build failed",
            "Step 3: Cleanup",
        ])
        excerpt = self.generator.generate(log)
        assert "ModuleNotFoundError" in excerpt
        assert "Build failed" in excerpt

    def test_handles_empty_log(self):
        excerpt = self.generator.generate("")
        assert isinstance(excerpt, str)

    def test_handles_no_errors(self):
        log = "All good\nBuild passed\nDone"
        excerpt = self.generator.generate(log)
        # Should still return something (tail lines)
        assert isinstance(excerpt, str)
        assert len(excerpt) > 0

    def test_strips_ansi_codes(self):
        log = "\x1b[31mERROR\x1b[0m: Something failed"
        excerpt = self.generator.generate(log)
        assert "\x1b[" not in excerpt
        assert "ERROR" in excerpt

    def test_respects_max_lines(self):
        # Create a very long log
        lines = [f"Line {i}: some output" for i in range(1000)]
        lines[500] = "ERROR: test failure here"
        log = "\n".join(lines)
        
        generator = ExcerptGenerator(max_excerpt_lines=50)
        excerpt = generator.generate(log)
        assert len(excerpt.splitlines()) <= 50

    def test_includes_context_around_errors(self):
        lines = [f"Line {i}" for i in range(20)]
        lines[10] = "FATAL: crash happened"
        log = "\n".join(lines)
        
        generator = ExcerptGenerator(context_lines=3, tail_lines=0)
        excerpt = generator.generate(log)
        
        # Should include lines 7-13 (10±3)
        assert "Line 7" in excerpt or "Line 8" in excerpt
        assert "FATAL: crash happened" in excerpt


class TestExcerptWithRealLog:
    """Test with a realistic CI log."""

    def test_pytest_failure(self):
        log = """
Run python -m pytest tests/ -v
============================= test session starts ==============================
platform linux -- Python 3.12.0, pytest-8.0.0
collecting ... collected 5 items

tests/test_app.py::test_home PASSED
tests/test_app.py::test_health PASSED
tests/test_app.py::test_api FAILED

FAILED tests/test_app.py::test_api - AssertionError: expected 200 got 500
========================= 1 failed, 2 passed in 3.42s =========================
Error: Process completed with exit code 1
"""
        generator = ExcerptGenerator()
        excerpt = generator.generate(log)
        assert "FAILED" in excerpt
        assert "AssertionError" in excerpt
        assert "exit code 1" in excerpt
