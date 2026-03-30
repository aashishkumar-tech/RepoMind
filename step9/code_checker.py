"""
step9/code_checker.py — Code Quality Gate

HOW IT WORKS:
─────────────
Validates the LLM-generated code changes BEFORE a PR is created.

The pipeline already has a Policy Gate (Step 7) that checks *what* is
being changed. Step 9 checks *how well* the code is written:

    1. Collect all proposed code changes from the plan
    2. Write them to a temporary directory
    3. Run linters/formatters/type-checkers against the temp files
    4. Return a quality report: { passed, checks, issues }
    5. If critical issues found → block the PR

CHECKS RUN:
    ┌──────────────┬───────────────────────────────────────┬──────────┐
    │ Tool         │ What it checks                        │ Severity │
    ├──────────────┼───────────────────────────────────────┼──────────┤
    │ ruff         │ Linting (pyflakes, isort, pep8, etc.) │ error    │
    │ black        │ Formatting (PEP 8 style)              │ warning  │
    │ mypy         │ Static type checking                  │ warning  │
    │ syntax       │ Python AST parse (does it even parse?)│ error    │
    └──────────────┴───────────────────────────────────────┴──────────┘

SEVERITY:
    "error"   → blocks PR creation (critical: syntax errors, import issues)
    "warning" → included in report but does NOT block PR

WHY RUN QUALITY CHECKS:
    LLMs can generate code that:
    - Has unused imports
    - Breaks formatting conventions
    - Introduces type mismatches
    - Has syntax errors (rare but possible)
    Running checks BEFORE the PR catches these early.

COMMUNICATION:
─────────────
Worker (step2/worker.py) calls AFTER policy (Step 7), BEFORE PR (Step 8):
    checker = CodeChecker()
    report = checker.check(plan["code_changes"])
    if not report["passed"]:
        # block PR, record in artifacts
"""

import os
import ast
import shutil
import tempfile
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path

from shared.logger import get_logger

logger = get_logger("step9.code_checker")


# ──────────────────────────────────────────────
# Individual check result
# ──────────────────────────────────────────────
class CheckResult:
    """Result of a single quality check."""

    def __init__(
        self,
        tool: str,
        passed: bool,
        severity: str = "error",
        issues: Optional[List[str]] = None,
        detail: str = "",
    ):
        self.tool = tool
        self.passed = passed
        self.severity = severity  # "error" | "warning"
        self.issues = issues or []
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "passed": self.passed,
            "severity": self.severity,
            "issues": self.issues,
            "detail": self.detail,
        }


# ──────────────────────────────────────────────
# Code Quality Gate
# ──────────────────────────────────────────────
class CodeChecker:
    """
    Validates proposed code changes against quality standards.

    Runs linting, formatting, and type checks on the code
    the LLM generated, BEFORE it becomes a PR.
    """

    # Tools that block PR if they fail
    BLOCKING_TOOLS = {"syntax", "ruff"}

    def check(self, code_changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run all quality checks on the proposed code changes.

        Args:
            code_changes: List of change dicts from Step 6 (Planner).
                Each: {"file": "path", "action": "modify", "new_content": "..."}

        Returns:
            {
                "passed": True/False,
                "total_checks": int,
                "passed_checks": int,
                "failed_checks": int,
                "blocking_failures": int,
                "checks": [ CheckResult.to_dict(), ... ],
                "summary": "human-readable summary"
            }
        """
        if not code_changes:
            logger.info("no_code_changes_to_check")
            return self._build_report([], "No code changes to validate")

        # Filter to Python files with new content
        python_changes = self._filter_python_changes(code_changes)

        if not python_changes:
            logger.info("no_python_files_to_check")
            return self._build_report([], "No Python files in code changes")

        logger.info(
            "code_check_start",
            num_files=len(python_changes),
            files=[c["file"] for c in python_changes],
        )

        # Write changes to temp directory
        temp_dir = None
        try:
            temp_dir = self._write_temp_files(python_changes)
            results = []

            # 1. Syntax check (always runs, always blocking)
            results.extend(self._check_syntax(python_changes))

            # 2. Ruff lint (if available)
            ruff_result = self._check_ruff(temp_dir)
            if ruff_result:
                results.append(ruff_result)

            # 3. Black format check (if available)
            black_result = self._check_black(temp_dir)
            if black_result:
                results.append(black_result)

            # 4. Mypy type check (if available)
            mypy_result = self._check_mypy(temp_dir)
            if mypy_result:
                results.append(mypy_result)

            return self._build_report(results)

        except Exception as e:
            logger.error("code_check_error", error=str(e))
            # On checker failure, don't block the PR — fail open
            return self._build_report(
                [CheckResult("code_checker", False, "warning", [str(e)], "Checker itself failed")],
                "Code checker encountered an error — proceeding anyway",
            )

        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ──────────────────────────────────────────
    # Filtering
    # ──────────────────────────────────────────
    def _filter_python_changes(
        self, code_changes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter to Python file changes that have new content."""
        python_exts = {".py"}
        result = []
        for change in code_changes:
            file_path = change.get("file", "")
            action = change.get("action", "")
            new_content = change.get("new_content", "")

            if action == "delete":
                continue  # Nothing to lint on a deleted file

            ext = Path(file_path).suffix
            if ext in python_exts and new_content:
                result.append(change)

        return result

    # ──────────────────────────────────────────
    # Temp directory setup
    # ──────────────────────────────────────────
    def _write_temp_files(self, python_changes: List[Dict[str, Any]]) -> str:
        """Write proposed code changes to a temp directory for checking."""
        temp_dir = tempfile.mkdtemp(prefix="repomind_check_")

        for change in python_changes:
            file_path = change["file"]
            content = change.get("new_content", "")

            # Recreate directory structure in temp
            full_path = Path(temp_dir) / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

        logger.debug("temp_files_written", temp_dir=temp_dir)
        return temp_dir

    # ──────────────────────────────────────────
    # Check 1: Syntax Validation (ast.parse)
    # ──────────────────────────────────────────
    def _check_syntax(
        self, python_changes: List[Dict[str, Any]]
    ) -> List[CheckResult]:
        """
        Parse each Python file with ast.parse().
        If it doesn't parse → the code is broken → block PR.
        """
        results = []
        for change in python_changes:
            file_path = change["file"]
            content = change.get("new_content", "")

            try:
                ast.parse(content, filename=file_path)
                results.append(
                    CheckResult(
                        tool="syntax",
                        passed=True,
                        severity="error",
                        detail=f"{file_path}: valid syntax",
                    )
                )
            except SyntaxError as e:
                results.append(
                    CheckResult(
                        tool="syntax",
                        passed=False,
                        severity="error",
                        issues=[f"{file_path}:{e.lineno}: {e.msg}"],
                        detail=f"{file_path}: syntax error at line {e.lineno}",
                    )
                )
                logger.warning(
                    "syntax_error_found",
                    file=file_path,
                    line=e.lineno,
                    msg=e.msg,
                )

        return results

    # ──────────────────────────────────────────
    # Check 2: Ruff Lint
    # ──────────────────────────────────────────
    def _check_ruff(self, temp_dir: str) -> Optional[CheckResult]:
        """
        Run `ruff check` on the temp directory.

        Ruff is extremely fast (~100ms for small files).
        Catches: unused imports, undefined names, style issues.
        """
        if not self._tool_available("ruff"):
            logger.debug("ruff_not_available")
            return None

        try:
            result = subprocess.run(
                ["ruff", "check", temp_dir, "--output-format", "text", "--no-fix"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return CheckResult(
                    tool="ruff",
                    passed=True,
                    severity="error",
                    detail="No linting issues found",
                )
            else:
                issues = [
                    line.strip()
                    for line in result.stdout.strip().split("\n")
                    if line.strip() and not line.startswith("Found")
                ]
                # Strip temp dir path from issues for cleaner output
                issues = [self._strip_temp_path(i, temp_dir) for i in issues]

                return CheckResult(
                    tool="ruff",
                    passed=False,
                    severity="error",
                    issues=issues[:20],  # Cap at 20 issues
                    detail=f"Found {len(issues)} linting issue(s)",
                )

        except subprocess.TimeoutExpired:
            return CheckResult(
                tool="ruff",
                passed=False,
                severity="warning",
                issues=["Ruff timed out after 30 seconds"],
                detail="Timeout",
            )
        except Exception as e:
            logger.warning("ruff_check_error", error=str(e))
            return None

    # ──────────────────────────────────────────
    # Check 3: Black Format Check
    # ──────────────────────────────────────────
    def _check_black(self, temp_dir: str) -> Optional[CheckResult]:
        """
        Run `black --check` on the temp directory.

        Black checks PEP 8 formatting. Non-blocking (warning only).
        """
        if not self._tool_available("black"):
            logger.debug("black_not_available")
            return None

        try:
            result = subprocess.run(
                ["black", "--check", "--quiet", temp_dir],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return CheckResult(
                    tool="black",
                    passed=True,
                    severity="warning",
                    detail="Formatting is correct",
                )
            else:
                # Black lists files that would be reformatted
                issues = [
                    self._strip_temp_path(line.strip(), temp_dir)
                    for line in result.stderr.strip().split("\n")
                    if line.strip() and "would reformat" in line.lower()
                ]
                if not issues:
                    issues = ["Some files would be reformatted"]

                return CheckResult(
                    tool="black",
                    passed=False,
                    severity="warning",
                    issues=issues,
                    detail=f"{len(issues)} file(s) need reformatting",
                )

        except subprocess.TimeoutExpired:
            return CheckResult(
                tool="black",
                passed=False,
                severity="warning",
                issues=["Black timed out after 30 seconds"],
                detail="Timeout",
            )
        except Exception as e:
            logger.warning("black_check_error", error=str(e))
            return None

    # ──────────────────────────────────────────
    # Check 4: Mypy Type Check
    # ──────────────────────────────────────────
    def _check_mypy(self, temp_dir: str) -> Optional[CheckResult]:
        """
        Run `mypy` on the temp directory.

        Type checking. Non-blocking (warning only) because LLM-generated
        code may not have full type annotations.
        """
        if not self._tool_available("mypy"):
            logger.debug("mypy_not_available")
            return None

        try:
            result = subprocess.run(
                [
                    "mypy",
                    temp_dir,
                    "--ignore-missing-imports",
                    "--no-error-summary",
                    "--no-color-output",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return CheckResult(
                    tool="mypy",
                    passed=True,
                    severity="warning",
                    detail="No type errors found",
                )
            else:
                issues = [
                    self._strip_temp_path(line.strip(), temp_dir)
                    for line in result.stdout.strip().split("\n")
                    if line.strip() and ": error:" in line
                ]
                return CheckResult(
                    tool="mypy",
                    passed=False,
                    severity="warning",
                    issues=issues[:15],
                    detail=f"Found {len(issues)} type error(s)",
                )

        except subprocess.TimeoutExpired:
            return CheckResult(
                tool="mypy",
                passed=False,
                severity="warning",
                issues=["Mypy timed out after 60 seconds"],
                detail="Timeout",
            )
        except Exception as e:
            logger.warning("mypy_check_error", error=str(e))
            return None

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────
    def _tool_available(self, tool_name: str) -> bool:
        """Check if a CLI tool is installed and available on PATH."""
        return shutil.which(tool_name) is not None

    def _strip_temp_path(self, text: str, temp_dir: str) -> str:
        """Remove the temp directory prefix from output for cleaner display."""
        return text.replace(temp_dir + os.sep, "").replace(temp_dir + "/", "")

    def _build_report(
        self,
        results: List[CheckResult],
        override_summary: str = "",
    ) -> Dict[str, Any]:
        """
        Build the final quality report from individual check results.

        A report "passes" only if no blocking tools (severity=error) failed.
        """
        if not results:
            return {
                "passed": True,
                "total_checks": 0,
                "passed_checks": 0,
                "failed_checks": 0,
                "blocking_failures": 0,
                "checks": [],
                "summary": override_summary or "No checks performed",
            }

        checks = [r.to_dict() for r in results]
        passed_checks = sum(1 for r in results if r.passed)
        failed_checks = sum(1 for r in results if not r.passed)
        blocking_failures = sum(
            1 for r in results if not r.passed and r.severity == "error"
        )

        overall_passed = blocking_failures == 0

        if override_summary:
            summary = override_summary
        elif overall_passed and failed_checks == 0:
            summary = f"All {len(results)} checks passed"
        elif overall_passed and failed_checks > 0:
            summary = (
                f"{passed_checks}/{len(results)} checks passed "
                f"({failed_checks} non-blocking warnings)"
            )
        else:
            summary = (
                f"BLOCKED: {blocking_failures} critical issue(s) found "
                f"({passed_checks}/{len(results)} checks passed)"
            )

        report = {
            "passed": overall_passed,
            "total_checks": len(results),
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "blocking_failures": blocking_failures,
            "checks": checks,
            "summary": summary,
        }

        logger.info(
            "code_check_complete",
            passed=overall_passed,
            total=len(results),
            blocking=blocking_failures,
        )

        return report
