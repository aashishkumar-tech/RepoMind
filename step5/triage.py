"""
step5/triage.py — AI-Powered Failure Triage Engine

HOW IT WORKS:
─────────────
Uses Groq LLM (Llama 3.1 70B) to classify CI failures.

Input:  Log excerpt (from Step 2)
Output: { failure_type, confidence, summary }

FAILURE TYPES:
    - dependency_error     → missing package/module
    - syntax_error         → code syntax issue
    - test_failure         → unit/integration test failed
    - type_error           → type mismatch
    - import_error         → module import failed
    - configuration_error  → config/env issue
    - build_error          → compilation/build failed
    - timeout_error        → operation timed out
    - permission_error     → access denied
    - unknown              → could not classify

GROQ API:
    - Free tier: 30 req/min, 14,400 req/day
    - Model: openai/gpt-oss-120b (fast, accurate)
    - Structured output via JSON mode

COMMUNICATION:
─────────────
Worker (step2/worker.py) calls:
    triage = TriageEngine().classify(excerpt, repo)
The result goes into:
    - PipelineContext.triage
    - artifacts.json → triage section
    - timeline.json → step 5 entry
Then passed to Step 6 (Planner) for fix plan generation.
"""

import json
from typing import Dict, Any, Optional

from groq import Groq

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step5.triage")

# ──────────────────────────────────────────────
# Triage prompt template
# ──────────────────────────────────────────────
TRIAGE_SYSTEM_PROMPT = """You are a CI/CD failure triage expert.
Analyze the CI log excerpt and classify the failure.

You MUST respond with valid JSON only. No markdown, no explanation outside JSON.

Response format:
{
    "failure_type": "one of: dependency_error, syntax_error, test_failure, type_error, import_error, configuration_error, build_error, timeout_error, permission_error, unknown",
    "confidence": 0.0 to 1.0,
    "summary": "One-line description of the root cause",
    "affected_file": "path/to/file if identifiable, else null",
    "affected_package": "package name if relevant, else null",
    "suggested_fix_category": "brief category of fix needed"
}"""

TRIAGE_USER_PROMPT = """Analyze this CI failure log excerpt from repository '{repo}':

```
{excerpt}
```

Classify the failure type, confidence level, and provide a one-line root cause summary.
Respond with JSON only."""


class TriageEngine:
    """
    Classifies CI failures using Groq LLM.

    Falls back to heuristic classification if LLM is unavailable.
    """

    # Valid failure types (for validation)
    VALID_TYPES = {
        "dependency_error",
        "syntax_error",
        "test_failure",
        "type_error",
        "import_error",
        "configuration_error",
        "build_error",
        "timeout_error",
        "permission_error",
        "unknown",
    }

    def __init__(self):
        self._client = None
        if settings.GROQ_API_KEY:
            self._client = Groq(api_key=settings.GROQ_API_KEY)

    def classify(self, excerpt: str, repo: str) -> Dict[str, Any]:
        """
        Classify a CI failure from its log excerpt.

        Args:
            excerpt: The cleaned log excerpt from Step 2
            repo: Repository full name (e.g. "user/mlproject")

        Returns:
            Dict with: failure_type, confidence, summary, etc.
        """
        # Try LLM classification first
        if self._client:
            try:
                result = self._llm_classify(excerpt, repo)
                if result:
                    return result
            except Exception as e:
                logger.warning("llm_triage_failed", error=str(e))

        # Fallback to heuristic
        logger.info("using_heuristic_triage")
        return self._heuristic_classify(excerpt)

    def _llm_classify(self, excerpt: str, repo: str) -> Optional[Dict[str, Any]]:
        """
        Use Groq LLM to classify the failure.

        Sends the excerpt to Llama 3.1 70B with a structured prompt.
        Parses the JSON response and validates it.
        """
        # Truncate excerpt to fit context window (keep most relevant end)
        max_chars = 6000
        if len(excerpt) > max_chars:
            excerpt = "... (truncated) ...\n" + excerpt[-max_chars:]

        user_prompt = TRIAGE_USER_PROMPT.format(repo=repo, excerpt=excerpt)

        logger.info("llm_triage_start", repo=repo, excerpt_length=len(excerpt))

        response = self._client.chat.completions.create(
            model="openai/gpt-oss-120b",  # Updated model for better performance
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content.strip()
        logger.debug("llm_triage_raw", response=raw_text)

        result = json.loads(raw_text)

        # Validate failure type
        if result.get("failure_type") not in self.VALID_TYPES:
            result["failure_type"] = "unknown"

        # Validate confidence range
        confidence = result.get("confidence", 0.5)
        result["confidence"] = max(0.0, min(1.0, float(confidence)))

        logger.info(
            "llm_triage_complete",
            failure_type=result["failure_type"],
            confidence=result["confidence"],
        )
        return result

    def _heuristic_classify(self, excerpt: str) -> Dict[str, Any]:
        """
        Fallback heuristic classification using keyword matching.

        Less accurate than LLM, but works without API access.
        Returns lower confidence scores.
        """
        lower = excerpt.lower()

        # Check patterns in priority order
        patterns = [
            ("dependency_error", [
                "cannot find module", "module not found", "no matching version",
                "missing dependency", "npm err!", "pip install", "package not found",
                "modulenotfounderror", "enoent",
            ]),
            ("import_error", [
                "importerror", "import error", "cannot import", "no module named",
                "modulenotfounderror",
            ]),
            ("syntax_error", [
                "syntaxerror", "syntax error", "unexpected token",
                "parsing error", "invalid syntax",
            ]),
            ("test_failure", [
                "test failed", "tests failed", "assertion", "assertionerror",
                "expected", "actual", "fail", "pytest", "jest",
            ]),
            ("type_error", [
                "typeerror", "type error", "type mismatch",
                "is not assignable", "incompatible types",
            ]),
            ("configuration_error", [
                "configuration", "config error", "environment variable",
                "missing env", ".env", "secrets",
            ]),
            ("build_error", [
                "build failed", "compilation error", "compile error",
                "build error", "webpack", "tsc",
            ]),
            ("timeout_error", [
                "timeout", "timed out", "deadline exceeded",
            ]),
            ("permission_error", [
                "permission denied", "access denied", "eacces",
                "forbidden", "unauthorized",
            ]),
        ]

        for failure_type, keywords in patterns:
            matches = sum(1 for kw in keywords if kw in lower)
            if matches > 0:
                confidence = min(0.7, 0.3 + (matches * 0.1))
                return {
                    "failure_type": failure_type,
                    "confidence": round(confidence, 2),
                    "summary": f"Heuristic: detected {failure_type} ({matches} keyword matches)",
                    "affected_file": None,
                    "affected_package": None,
                    "suggested_fix_category": failure_type,
                }

        return {
            "failure_type": "unknown",
            "confidence": 0.1,
            "summary": "Could not classify failure from log excerpt",
            "affected_file": None,
            "affected_package": None,
            "suggested_fix_category": "manual_review",
        }
