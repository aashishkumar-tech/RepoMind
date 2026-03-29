"""
step7/policy.py — Policy Evaluation Engine

HOW IT WORKS:
─────────────
Decides whether the auto-fix should be APPLIED or DENIED.

This is the SAFETY GATE of the pipeline. Even if the LLM generates
a perfect fix, the policy engine can block it based on rules.

EVALUATION FLOW:
    1. Load policy rules (from policy/default.yaml or hardcoded defaults)
    2. Match rules against: triage result + plan summary
    3. First matching rule wins (ordered evaluation)
    4. Return: { decision: "allow"|"deny", reason, rules_triggered }

POLICY RULES CONTROL:
    - Which failure types can be auto-fixed
    - Maximum risk level allowed
    - Minimum confidence threshold
    - Which repos are allowed
    - Rate limiting (max fixes per day)

DEFAULT POLICY (CONSERVATIVE):
    - Allow: dependency_error, import_error (low risk, high confidence)
    - Deny: everything else
    - This is the ALPHA policy. User can customize via policy/default.yaml

COMMUNICATION:
─────────────
Worker calls: PolicyEngine().evaluate(triage, plan, repo)
If "allow" → proceed to Step 8 (PR creation)
If "deny"  → stop pipeline, send notification
"""

from typing import Dict, Any, List
from pathlib import Path

import yaml

from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step7.policy")


# ──────────────────────────────────────────────
# Default policy rules (hardcoded fallback)
# ──────────────────────────────────────────────
DEFAULT_RULES = [
    {
        "id": "allow_low_risk_dependency_fix",
        "description": "Allow auto-fix for low-risk dependency errors with high confidence",
        "when": {
            "failure_types": ["dependency_error"],
            "max_risk_level": "low",
            "min_confidence": 0.7,
        },
        "decision": "allow",
    },
    {
        "id": "allow_import_fix",
        "description": "Allow auto-fix for import errors with high confidence",
        "when": {
            "failure_types": ["import_error"],
            "max_risk_level": "low",
            "min_confidence": 0.8,
        },
        "decision": "allow",
    },
    {
        "id": "allow_syntax_fix",
        "description": "Allow auto-fix for syntax errors with very high confidence",
        "when": {
            "failure_types": ["syntax_error"],
            "max_risk_level": "low",
            "min_confidence": 0.9,
        },
        "decision": "allow",
    },
    {
        "id": "deny_high_risk",
        "description": "Deny all high-risk fixes",
        "when": {
            "min_risk_level": "high",
        },
        "decision": "deny",
    },
    {
        "id": "default_deny",
        "description": "Default: deny if no rule matches (safety fallback)",
        "when": {},
        "decision": "deny",
    },
]

RISK_LEVELS = {"low": 1, "medium": 2, "high": 3}


class PolicyEngine:
    """
    Evaluates pipeline actions against safety policy rules.

    Rules are evaluated in order. First matching rule wins.
    Default policy is conservative (deny unless explicitly allowed).
    """

    def __init__(self, policy_path: str = None):
        self._rules = self._load_rules(policy_path)

    def _load_rules(self, policy_path: str = None) -> List[Dict[str, Any]]:
        """
        Load policy rules from YAML file, or use defaults.

        Priority:
            1. Explicit policy_path argument
            2. policy/default.yaml in project root
            3. Hardcoded DEFAULT_RULES
        """
        if policy_path:
            path = Path(policy_path)
        else:
            path = Path(__file__).resolve().parent.parent / "policy" / "default.yaml"

        if path.exists():
            try:
                with open(path, "r") as f:
                    data = yaml.safe_load(f)
                rules = data.get("rules", DEFAULT_RULES)
                logger.info("policy_loaded", source=str(path), num_rules=len(rules))
                return rules
            except Exception as e:
                logger.warning("policy_load_failed", error=str(e))

        logger.info("using_default_policy", num_rules=len(DEFAULT_RULES))
        return DEFAULT_RULES

    def evaluate(
        self,
        triage: Dict[str, Any],
        plan: Dict[str, Any],
        repo: str,
    ) -> Dict[str, Any]:
        """
        Evaluate the proposed fix against policy rules.

        Args:
            triage: Triage result from Step 5
            plan: Plan from Step 6
            repo: Repository full name

        Returns:
            {
                "decision": "allow" | "deny",
                "reason": "Human-readable explanation",
                "rules_triggered": ["rule_id_1", ...]
            }
        """
        failure_type = triage.get("failure_type", "unknown")
        confidence = triage.get("confidence", 0)
        risk_level = plan.get("risk_level", "high")

        logger.info(
            "policy_evaluating",
            repo=repo,
            failure_type=failure_type,
            confidence=confidence,
            risk_level=risk_level,
        )

        triggered_rules = []

        for rule in self._rules:
            if self._rule_matches(rule, failure_type, confidence, risk_level, repo):
                decision = rule.get("decision", "deny")
                reason = rule.get("description", "No reason provided")
                triggered_rules.append(rule["id"])

                result = {
                    "decision": decision,
                    "reason": reason,
                    "rules_triggered": triggered_rules,
                }

                logger.info(
                    "policy_decision",
                    decision=decision,
                    rule=rule["id"],
                    reason=reason,
                )
                return result

        # Should never reach here (default_deny catches all), but just in case
        return {
            "decision": "deny",
            "reason": "No matching policy rule (implicit deny)",
            "rules_triggered": [],
        }

    def _rule_matches(
        self,
        rule: Dict[str, Any],
        failure_type: str,
        confidence: float,
        risk_level: str,
        repo: str,
    ) -> bool:
        """
        Check if a rule matches the current context.

        All conditions in 'when' must be satisfied (AND logic).
        An empty 'when' matches everything (used for default_deny).
        """
        when = rule.get("when", {})

        # If 'when' is empty, rule matches everything
        if not when:
            return True

        # Check failure_types (if specified)
        allowed_types = when.get("failure_types")
        if allowed_types and failure_type not in allowed_types:
            return False

        # Check confidence threshold (if specified)
        min_confidence = when.get("min_confidence")
        if min_confidence is not None and confidence < min_confidence:
            return False

        # Check max risk level (if specified)
        max_risk = when.get("max_risk_level")
        if max_risk:
            if RISK_LEVELS.get(risk_level, 3) > RISK_LEVELS.get(max_risk, 1):
                return False

        # Check min risk level (for deny rules)
        min_risk = when.get("min_risk_level")
        if min_risk:
            if RISK_LEVELS.get(risk_level, 1) < RISK_LEVELS.get(min_risk, 3):
                return False

        # Check repo restrictions (if specified)
        allowed_repos = when.get("repos")
        if allowed_repos and repo not in allowed_repos:
            return False

        return True
