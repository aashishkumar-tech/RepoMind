"""
step6/planner.py — Fix Plan Generator

HOW IT WORKS:
─────────────
Uses Groq LLM to generate a concrete fix plan based on:
    1. Triage result (what type of failure)
    2. Log excerpt (error context)
    3. Repository context

Output (stored in artifacts.json):
    {
        "playbook_id": "fix_dependency_error",
        "actions": ["update requirements.txt", "add missing import"],
        "files_to_modify": ["requirements.txt"],
        "risk_level": "low",
        "description": "Add missing 'requests' package"
    }

PLAN TYPES:
    - Dependency fix → add/update package
    - Import fix → add missing import statement
    - Syntax fix → correct syntax error
    - Config fix → update configuration
    - Custom → LLM-generated fix steps

COMMUNICATION:
─────────────
Worker calls: Planner().generate_plan(triage, excerpt, repo)
The plan is then passed to Step 7 (Policy) for approval.
If approved, Step 8 (PR Creator) executes the plan.
"""

import json
from typing import Dict, Any, Optional

from groq import Groq

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step6.planner")

# ──────────────────────────────────────────────
# Plan generation prompt
# ──────────────────────────────────────────────
PLAN_SYSTEM_PROMPT = """You are a CI/CD fix planning expert.
Given a failure triage result and log excerpt, generate a concrete fix plan.

You MUST respond with valid JSON only. No markdown, no explanation outside JSON.

Response format:
{
    "playbook_id": "fix_<type>_error",
    "description": "One-line description of the fix",
    "actions": ["step 1", "step 2", ...],
    "files_to_modify": ["path/to/file1", "path/to/file2"],
    "code_changes": [
        {
            "file": "path/to/file",
            "action": "create|modify|delete",
            "description": "what to change",
            "old_content": "line to find (if modifying)",
            "new_content": "replacement line"
        }
    ],
    "risk_level": "low|medium|high",
    "requires_test": true,
    "rollback_steps": ["how to undo if fix breaks something"]
}

RULES:
- Always prefer minimal, safe changes
- Never modify more than 3 files unless absolutely necessary
- Set risk_level based on scope: low=1 file, medium=2-3 files, high=4+ files
- code_changes must be specific enough to apply automatically
"""

PLAN_USER_PROMPT = """Repository: {repo}

Triage Result:
- Failure Type: {failure_type}
- Confidence: {confidence}
- Summary: {summary}
- Affected File: {affected_file}
- Affected Package: {affected_package}

Log Excerpt:
```
{excerpt}
```

Generate a specific, actionable fix plan. Respond with JSON only."""


class Planner:
    """Generates fix plans using Groq LLM."""

    def __init__(self):
        self._client = None
        if settings.GROQ_API_KEY:
            self._client = Groq(api_key=settings.GROQ_API_KEY)

    def generate_plan(
        self,
        triage: Dict[str, Any],
        excerpt: str,
        repo: str,
    ) -> Dict[str, Any]:
        """
        Generate a fix plan from triage results.

        Args:
            triage: Output from TriageEngine.classify()
            excerpt: The log excerpt
            repo: Repository full name

        Returns:
            Plan dict with playbook_id, actions, files_to_modify, etc.
        """
        # Try LLM planning
        if self._client:
            try:
                result = self._llm_plan(triage, excerpt, repo)
                if result:
                    return result
            except Exception as e:
                logger.warning("llm_plan_failed", error=str(e))

        # Fallback to template-based planning
        return self._template_plan(triage)

    def _llm_plan(
        self,
        triage: Dict[str, Any],
        excerpt: str,
        repo: str,
    ) -> Optional[Dict[str, Any]]:
        """Use Groq LLM to generate a fix plan."""
        # Truncate excerpt
        max_chars = 4000
        if len(excerpt) > max_chars:
            excerpt = "... (truncated) ...\n" + excerpt[-max_chars:]

        user_prompt = PLAN_USER_PROMPT.format(
            repo=repo,
            failure_type=triage.get("failure_type", "unknown"),
            confidence=triage.get("confidence", 0),
            summary=triage.get("summary", ""),
            affected_file=triage.get("affected_file", "unknown"),
            affected_package=triage.get("affected_package", "unknown"),
            excerpt=excerpt,
        )

        logger.info("llm_plan_start", repo=repo)

        response = self._client.chat.completions.create(
            model="openai/gpt-oss-120b",  # Use the same model as in triage.py
            messages=[
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Validate required fields
        result.setdefault("playbook_id", f"fix_{triage.get('failure_type', 'unknown')}")
        result.setdefault("actions", [])
        result.setdefault("files_to_modify", [])
        result.setdefault("risk_level", "medium")
        result.setdefault("code_changes", [])

        logger.info(
            "llm_plan_complete",
            playbook_id=result["playbook_id"],
            num_actions=len(result["actions"]),
            risk_level=result["risk_level"],
        )
        return result

    def _template_plan(self, triage: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback: generate a plan from templates based on failure type.
        Less specific, but works without LLM.
        """
        failure_type = triage.get("failure_type", "unknown")
        templates = {
            "dependency_error": {
                "playbook_id": "fix_dependency_error",
                "description": "Add missing dependency",
                "actions": [
                    "Identify missing package from error message",
                    "Add package to requirements.txt / package.json",
                    "Commit changes",
                ],
                "risk_level": "low",
            },
            "import_error": {
                "playbook_id": "fix_import_error",
                "description": "Fix import statement",
                "actions": [
                    "Identify correct module path",
                    "Update import statement",
                    "Commit changes",
                ],
                "risk_level": "low",
            },
            "syntax_error": {
                "playbook_id": "fix_syntax_error",
                "description": "Fix syntax error",
                "actions": [
                    "Identify syntax issue from error traceback",
                    "Fix the syntax in the affected file",
                    "Commit changes",
                ],
                "risk_level": "medium",
            },
            "test_failure": {
                "playbook_id": "fix_test_failure",
                "description": "Fix failing test",
                "actions": [
                    "Analyze test failure output",
                    "Determine if test or code needs updating",
                    "Apply fix",
                ],
                "risk_level": "medium",
            },
            "configuration_error": {
                "playbook_id": "fix_configuration_error",
                "description": "Fix configuration issue",
                "actions": [
                    "Identify misconfigured setting",
                    "Update configuration file",
                    "Commit changes",
                ],
                "risk_level": "medium",
            },
        }

        plan = templates.get(failure_type, {
            "playbook_id": f"fix_{failure_type}",
            "description": f"Fix {failure_type}",
            "actions": ["Manual investigation required"],
            "risk_level": "high",
        })

        plan["files_to_modify"] = []
        plan["code_changes"] = []
        return plan
