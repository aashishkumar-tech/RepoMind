# 🤝 Contributing Guide — RepoMind CI Auto-Fix Agent

## 1. Getting Started

### 1.1 Prerequisites
- Python 3.10+
- uv (package manager) — [install guide](https://docs.astral.sh/uv/getting-started/installation/)
- Git
- Read the [Architecture](./ARCHITECTURE.md) and [Pipeline Workflow](./PIPELINE_WORKFLOW.md) docs

### 1.2 Setup

```bash
# Fork & clone
git clone https://github.com/your-fork/RepoMind.git
cd RepoMind

# Create virtual environment with uv
uv venv --python 3.12

# Activate
.\.venv\Scripts\Activate.ps1    # Windows
# source .venv/bin/activate     # Linux/macOS

# Install dependencies
uv pip install -r requirements.txt

# Run tests to verify
pytest tests/ -v
```

---

## 2. Project Conventions

### 2.1 Code Style

| Convention | Standard |
|-----------|----------|
| **Language** | Python 3.10+ |
| **Type Hints** | Required on all functions |
| **Docstrings** | Required on all public classes/methods |
| **Imports** | stdlib → third-party → local (separated by blank lines) |
| **Line Length** | 100 characters max |
| **Naming** | `snake_case` for functions/variables, `PascalCase` for classes |

### 2.2 Module Documentation Standard

Every module should start with a docstring explaining:
```python
"""
module/file.py — Short Description

HOW IT WORKS:
─────────────
Explanation of the module's purpose and behavior.

COMMUNICATION:
─────────────
How this module interacts with other modules.

ERROR HANDLING:
─────────────
How errors are handled.
"""
```

### 2.3 Single Responsibility

- Each step module does **ONE thing**
- Each file does **ONE thing**
- The Worker (`step2/worker.py`) is the **ONLY** module that knows the full pipeline

---

## 3. Adding a New Pipeline Step

### 3.1 Create the Module

```
step_N/
  __init__.py
  your_module.py
```

### 3.2 Implement the Interface

```python
"""
step_N/your_module.py — Description

HOW IT WORKS:
─────────────
...
"""

from shared.logger import get_logger
from shared.config import settings

logger = get_logger("step_N.your_module")


class YourModule:
    """Does one thing well."""

    def process(self, input_data: dict) -> dict:
        """
        Main entry point.
        
        Args:
            input_data: Description of input
            
        Returns:
            dict with result fields
        """
        logger.info("Processing", event_id=input_data.get("event_id"))
        # ... implementation ...
        return {"status": "success", "result": ...}
```

### 3.3 Add Tests

```python
# tests/test_step_N.py
import pytest
from step_N.your_module import YourModule


class TestYourModule:
    def test_happy_path(self):
        module = YourModule()
        result = module.process({"event_id": "test"})
        assert result["status"] == "success"

    def test_error_handling(self):
        # ...
```

### 3.4 Integrate with Worker

Update `step2/worker.py` to call your new step at the appropriate point in the pipeline.

### 3.5 Update Documentation

1. Add to `projectdocs/PIPELINE_WORKFLOW.md`
2. Add to `projectdocs/REPO_STRUCTURE.md`
3. Add to `projectdocs/LLD.md`

---

## 4. Adding a New Policy Rule

### 4.1 Edit `policy/default.yaml`

Add your rule **before** the `default_deny` rule:

```yaml
rules:
  # ... existing rules ...

  - id: your_new_rule
    description: "Clear description of what this allows/denies"
    when:
      failure_types: ["your_failure_type"]
      max_risk_level: "low"
      min_confidence: 0.8
    decision: "allow"

  - id: default_deny  # Keep this LAST
    when: {}
    decision: "deny"
```

### 4.2 Add a Test

```python
# In tests/test_policy.py
def test_your_new_rule(self):
    engine = PolicyEngine()
    result = engine.evaluate(
        triage={"failure_type": "your_type", "confidence": 0.9},
        plan={"risk_level": "low"}
    )
    assert result["decision"] == "allow"
```

---

## 5. Adding a New Sanitizer Pattern

### 5.1 Edit `step2/sanitizer.py`

Add to `DEFAULT_PATTERNS`:

```python
DEFAULT_PATTERNS = [
    # ... existing patterns ...
    ("your_pattern_name", r"your_regex_here"),
]
```

### 5.2 Add a Test

```python
# In tests/test_sanitizer.py
def test_your_pattern(self):
    sanitizer = Sanitizer()
    result = sanitizer.sanitize("text with YOUR_SECRET_VALUE here")
    assert "[REDACTED:your_pattern_name]" in result
    assert "YOUR_SECRET_VALUE" not in result
```

---

## 6. Git Workflow

### 6.1 Branch Naming

```
feature/step-9-ci-standards
bugfix/triage-confidence-validation
docs/add-deployment-guide
refactor/simplify-worker-pipeline
```

### 6.2 Commit Messages

```
feat: add Step 9 CI code standards module
fix: handle empty excerpt in triage fallback
docs: add deployment guide to projectdocs
test: add tests for policy engine edge cases
refactor: extract common LLM client into shared
```

### 6.3 Pull Request Process

1. Create a feature branch from `main`
2. Make changes following conventions
3. Add/update tests (required)
4. Run `pytest tests/ -v` (all tests must pass)
5. Update documentation if applicable
6. Submit PR with clear description
7. Address review comments
8. Squash-merge when approved

---

## 7. Testing Requirements

| Requirement | Description |
|-------------|-------------|
| All tests pass | `pytest tests/ -v` must be green |
| New code has tests | Coverage for new modules |
| No external calls | Mock all HTTP/AWS/LLM calls in tests |
| Deterministic | Same input → same output |
| Fast | Unit tests should complete in < 30 seconds |

---

## 8. Architecture Constraints

| Constraint | Rationale |
|-----------|-----------|
| No paid services | Must run on free tiers |
| Python only | Team expertise, Lambda compatibility |
| Serverless-first | AWS Lambda for all compute |
| Single responsibility | Each module does one thing |
| Fail-safe | Deny by default, save partial artifacts |
| Observable | Every step recorded in timeline |
