"""
tests/test_policy.py — Unit tests for policy evaluation
"""

from step7.policy import PolicyEngine


class TestPolicyEngine:
    def setup_method(self):
        # Use default rules (no yaml file)
        self.engine = PolicyEngine(policy_path="nonexistent.yaml")

    def test_allow_low_risk_dependency(self):
        triage = {"failure_type": "dependency_error", "confidence": 0.85}
        plan = {"risk_level": "low"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "allow"

    def test_deny_high_risk(self):
        triage = {"failure_type": "dependency_error", "confidence": 0.9}
        plan = {"risk_level": "high"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "deny"

    def test_deny_low_confidence(self):
        triage = {"failure_type": "dependency_error", "confidence": 0.3}
        plan = {"risk_level": "low"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        # Low confidence should not match the allow rule
        assert result["decision"] == "deny"

    def test_deny_unknown_type(self):
        triage = {"failure_type": "unknown", "confidence": 0.5}
        plan = {"risk_level": "medium"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "deny"

    def test_result_structure(self):
        triage = {"failure_type": "test_failure", "confidence": 0.5}
        plan = {"risk_level": "medium"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert "decision" in result
        assert "reason" in result
        assert "rules_triggered" in result
        assert isinstance(result["rules_triggered"], list)

    def test_allow_import_error(self):
        triage = {"failure_type": "import_error", "confidence": 0.9}
        plan = {"risk_level": "low"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "allow"

    def test_allow_syntax_high_confidence(self):
        triage = {"failure_type": "syntax_error", "confidence": 0.95}
        plan = {"risk_level": "low"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "allow"

    def test_deny_syntax_low_confidence(self):
        triage = {"failure_type": "syntax_error", "confidence": 0.5}
        plan = {"risk_level": "low"}
        result = self.engine.evaluate(triage, plan, "user/repo")
        assert result["decision"] == "deny"
