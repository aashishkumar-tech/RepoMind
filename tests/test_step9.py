"""
tests/test_step9.py — Unit tests for Step 9 Code Quality Gate

Tests the CodeChecker against various code quality scenarios:
    - Valid Python code passes all checks
    - Syntax errors are caught and block PR
    - Empty code changes pass (no files = nothing to check)
    - Non-Python files are skipped
    - Delete actions are skipped
    - Report structure is correct
    - Blocking vs non-blocking severity works correctly
"""

from step9.code_checker import CodeChecker, CheckResult


class TestCheckResult:
    """Test the CheckResult data class."""

    def test_check_result_to_dict(self):
        result = CheckResult(
            tool="ruff",
            passed=True,
            severity="error",
            issues=[],
            detail="No issues",
        )
        d = result.to_dict()
        assert d["tool"] == "ruff"
        assert d["passed"] is True
        assert d["severity"] == "error"
        assert d["issues"] == []
        assert d["detail"] == "No issues"

    def test_check_result_with_issues(self):
        result = CheckResult(
            tool="syntax",
            passed=False,
            severity="error",
            issues=["line 5: invalid syntax"],
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert len(d["issues"]) == 1


class TestCodeChecker:
    """Test the CodeChecker engine."""

    def setup_method(self):
        self.checker = CodeChecker()

    # ── No changes ──

    def test_empty_code_changes(self):
        """No code changes → pass (nothing to check)."""
        report = self.checker.check([])
        assert report["passed"] is True
        assert report["total_checks"] == 0
        assert "No code changes" in report["summary"]

    def test_no_python_files(self):
        """Only non-Python files → pass (nothing to lint)."""
        changes = [
            {"file": "README.md", "action": "modify", "new_content": "# Hello"},
            {"file": "config.yaml", "action": "create", "new_content": "key: value"},
        ]
        report = self.checker.check(changes)
        assert report["passed"] is True
        assert "No Python files" in report["summary"]

    def test_delete_action_skipped(self):
        """Delete actions should be skipped (nothing to lint)."""
        changes = [
            {"file": "old_module.py", "action": "delete", "new_content": ""},
        ]
        report = self.checker.check(changes)
        assert report["passed"] is True

    # ── Syntax checks ──

    def test_valid_python_syntax(self):
        """Valid Python code should pass syntax check."""
        changes = [
            {
                "file": "fix.py",
                "action": "create",
                "new_content": "import os\n\ndef hello():\n    return 'world'\n",
            }
        ]
        report = self.checker.check(changes)
        assert report["passed"] is True
        # At least the syntax check should have run
        syntax_checks = [c for c in report["checks"] if c["tool"] == "syntax"]
        assert len(syntax_checks) >= 1
        assert all(c["passed"] for c in syntax_checks)

    def test_invalid_python_syntax_blocks(self):
        """Syntax errors should be caught and block the PR."""
        changes = [
            {
                "file": "broken.py",
                "action": "create",
                "new_content": "def hello(\n    return 'world'\n",
            }
        ]
        report = self.checker.check(changes)
        assert report["passed"] is False
        assert report["blocking_failures"] >= 1

        syntax_checks = [c for c in report["checks"] if c["tool"] == "syntax"]
        failed = [c for c in syntax_checks if not c["passed"]]
        assert len(failed) >= 1
        assert failed[0]["severity"] == "error"

    def test_multiple_files_one_broken(self):
        """If one file has syntax error, the whole report fails."""
        changes = [
            {
                "file": "good.py",
                "action": "create",
                "new_content": "x = 1\n",
            },
            {
                "file": "bad.py",
                "action": "create",
                "new_content": "def f(\n",
            },
        ]
        report = self.checker.check(changes)
        assert report["passed"] is False
        assert report["blocking_failures"] >= 1

    # ── Report structure ──

    def test_report_structure(self):
        """Report should have all expected fields."""
        changes = [
            {
                "file": "app.py",
                "action": "modify",
                "new_content": "print('hello')\n",
            }
        ]
        report = self.checker.check(changes)

        assert "passed" in report
        assert "total_checks" in report
        assert "passed_checks" in report
        assert "failed_checks" in report
        assert "blocking_failures" in report
        assert "checks" in report
        assert "summary" in report
        assert isinstance(report["checks"], list)
        assert isinstance(report["passed"], bool)

    def test_report_counts_correct(self):
        """passed_checks + failed_checks should equal total_checks."""
        changes = [
            {
                "file": "test.py",
                "action": "create",
                "new_content": "x = 42\n",
            }
        ]
        report = self.checker.check(changes)
        assert report["passed_checks"] + report["failed_checks"] == report["total_checks"]

    # ── Mixed file types ──

    def test_mixed_file_types(self):
        """Only Python files should be checked; others ignored."""
        changes = [
            {"file": "data.json", "action": "create", "new_content": '{"key": "val"}'},
            {
                "file": "script.py",
                "action": "create",
                "new_content": "x = 1\ny = 2\n",
            },
            {"file": "style.css", "action": "create", "new_content": "body {}"},
        ]
        report = self.checker.check(changes)
        # Should only check script.py
        syntax_checks = [c for c in report["checks"] if c["tool"] == "syntax"]
        assert len(syntax_checks) == 1

    # ── Content with missing new_content ──

    def test_empty_new_content_skipped(self):
        """Changes with empty new_content should be skipped."""
        changes = [
            {"file": "empty.py", "action": "modify", "new_content": ""},
        ]
        report = self.checker.check(changes)
        assert report["passed"] is True

    # ── Subdirectory structure ──

    def test_nested_file_paths(self):
        """Files in subdirectories should work correctly."""
        changes = [
            {
                "file": "src/models/user.py",
                "action": "create",
                "new_content": "class User:\n    pass\n",
            },
            {
                "file": "src/utils/helpers.py",
                "action": "create",
                "new_content": "def helper():\n    return True\n",
            },
        ]
        report = self.checker.check(changes)
        assert report["passed"] is True
        syntax_checks = [c for c in report["checks"] if c["tool"] == "syntax"]
        assert len(syntax_checks) == 2
