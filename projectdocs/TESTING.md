# 🧪 Testing Guide — RepoMind CI Auto-Fix Agent

## 1. Test Strategy

### 1.1 Testing Pyramid

```
         ┌──────────┐
         │  E2E     │  ← test_local_pipeline.py (pipeline simulation)
        ┌┴──────────┴┐
        │ Integration │  ← test_webhook.py (FastAPI TestClient)
       ┌┴────────────┴┐
       │  Unit Tests   │  ← test_signature, test_sanitizer, etc.
       └──────────────┘
```

### 1.2 Test Principles

- **No external dependencies:** All tests run offline with mocks
- **Fast execution:** No LLM calls, no network, no AWS in unit tests
- **Deterministic:** Same input → same output, every time
- **Comprehensive:** Cover happy paths, edge cases, error handling

---

## 2. Test Suite Overview

| Test File | Module Under Test | Tests | Description |
|-----------|------------------|-------|-------------|
| `test_signature.py` | `step1/signature.py` | 6 | HMAC-SHA256 webhook validation |
| `test_event_id.py` | `shared/event_id.py` | 7 | Event ID generation & parsing |
| `test_sanitizer.py` | `step2/sanitizer.py` | 8 | Secret redaction patterns |
| `test_excerpt.py` | `step2/excerpt.py` | 7 | Log excerpt generation |
| `test_triage.py` | `step5/triage.py` | 8 | Failure classification |
| `test_policy.py` | `step7/policy.py` | 8 | Policy rule evaluation |
| `test_webhook.py` | `step1/webhook_handler.py` | 3 | HTTP endpoint testing |
| `test_step3.py` | `step3/` | 6 | Embedder, Indexer, Retriever (mocked) |
| `test_step4.py` | `step4/` | 8 | LangGraph nodes & graph (mocked) |
| `test_rag_metrics.py` | `step3/rag_metrics.py` | 21 | RAG evaluation metrics (retrieval, context, generation, grading) |
| `test_step9.py` | `step9/code_checker.py` | 12 | Code quality gate checks |
| `test_step10.py` | `step10/` | 15 | Verifier + rollback (mocked) |
| `test_step11.py` | `step11/` | 14 | Metrics + kill switch (mocked) |
| **Total** | | **123** | |

---

## 3. Running Tests

### 3.1 Run All Tests

```bash
pytest tests/ -v
```

### 3.2 Run a Specific Test File

```bash
pytest tests/test_signature.py -v
pytest tests/test_triage.py -v
pytest tests/test_step3.py -v
```

### 3.3 Run a Specific Test

```bash
pytest tests/test_sanitizer.py::TestSanitizer::test_aws_access_key -v
```

### 3.4 Run with Coverage Report

```bash
# Terminal report
pytest tests/ --cov=. --cov-report=term-missing

# HTML report
pytest tests/ --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

### 3.5 Run with Verbose Output

```bash
pytest tests/ -v -s --tb=long
```

### 3.6 Run Only Failed Tests (Re-run)

```bash
pytest tests/ --lf    # Last failed
pytest tests/ --ff    # Failed first, then rest
```

---

## 4. Test Details

### 4.1 `test_signature.py` — Webhook Validation

| Test | Description |
|------|-------------|
| `test_valid_signature` | Valid HMAC-SHA256 returns True |
| `test_invalid_signature` | Wrong signature returns False |
| `test_empty_payload` | Empty body handled correctly |
| `test_missing_prefix` | Missing `sha256=` prefix fails |
| `test_tampered_payload` | Modified payload fails validation |
| `test_different_secret` | Wrong secret key fails |

### 4.2 `test_event_id.py` — Event ID Generation

| Test | Description |
|------|-------------|
| `test_format` | Matches `evt-<slug>-<id>-<ts>` pattern |
| `test_uniqueness` | Different inputs → different IDs |
| `test_slug_extraction` | `owner/repo` → `owner-repo` |
| `test_special_characters` | Handles dots, underscores, etc. |
| `test_long_repo_names` | Truncation works correctly |
| `test_deterministic` | Same input → same output |
| `test_sortable` | Later timestamps sort after earlier |

### 4.3 `test_sanitizer.py` — Secret Redaction

| Test | Description |
|------|-------------|
| `test_aws_access_key` | `AKIA...` → `[REDACTED:aws_access_key]` |
| `test_github_token` | `ghp_...` → `[REDACTED:github_token]` |
| `test_bearer_token` | `Bearer xxx` → `[REDACTED:bearer_token]` |
| `test_password_field` | `password=xxx` → `[REDACTED:password_field]` |
| `test_email_address` | Email → `[REDACTED:email_address]` |
| `test_private_ip` | `192.168.x.x` → `[REDACTED:private_ip]` |
| `test_connection_string` | `postgres://...` → `[REDACTED:connection_string]` |
| `test_no_false_positives` | Normal text unchanged |

### 4.4 `test_triage.py` — Failure Classification

| Test | Description |
|------|-------------|
| `test_keyword_dependency` | `Cannot find module` → dependency_error |
| `test_keyword_import` | `ModuleNotFoundError` → import_error |
| `test_keyword_syntax` | `SyntaxError` → syntax_error |
| `test_keyword_test` | `FAILED tests/` → test_failure |
| `test_unknown_fallback` | Unrecognizable → unknown |
| `test_confidence_range` | Confidence 0.0–1.0 |
| `test_output_structure` | Has required fields |
| `test_empty_excerpt` | Handles empty input |

### 4.5 `test_policy.py` — Policy Evaluation

| Test | Description |
|------|-------------|
| `test_allow_low_risk` | Low risk + high confidence → allow |
| `test_deny_high_risk` | High risk → deny |
| `test_deny_low_confidence` | Low confidence → deny |
| `test_default_deny` | Unknown type → deny (fail-closed) |
| `test_rule_priority` | First matching rule wins |
| `test_missing_fields` | Handles incomplete input |
| `test_custom_rules` | Custom YAML rules evaluated |
| `test_output_structure` | Has decision + reason fields |

### 4.6 `test_step3.py` — Vector DB (Mocked)

| Test | Description |
|------|-------------|
| `test_embedder_output_dim` | Output is 384-dimensional |
| `test_embedder_batch` | Batch embedding works |
| `test_indexer_create_collection` | Qdrant collection created |
| `test_indexer_upsert` | Points upserted correctly |
| `test_retriever_search` | Search returns results |
| `test_retriever_filters` | Filter by repo/type works |

### 4.7 `test_step4.py` — LangGraph (Mocked)

| Test | Description |
|------|-------------|
| `test_evidence_node` | Returns evidence in state |
| `test_triage_node` | Returns triage in state |
| `test_planner_node` | Returns plan in state |
| `test_policy_node` | Returns policy in state |
| `test_graph_build` | Graph compiles without error |
| `test_sequential_fallback` | Sequential execution works |
| `test_error_handling` | Errors recorded in state |
| `test_full_pipeline` | All nodes execute in order |

### 4.8 `test_rag_metrics.py` — RAG Evaluation Metrics

| Test | Description |
|------|-------------|
| `test_basic_retrieval_metrics` | Similarity scores computed correctly |
| `test_empty_results` | Empty search results handled gracefully |
| `test_mrr_with_strong_match` | Mean Reciprocal Rank with strong match |
| `test_mrr_with_top_match` | MRR when best result is rank 1 |
| `test_score_distribution_buckets` | Similarity histogram bucketing |
| `test_stale_results` | Stale ratio for old results |
| `test_recall_at_k` | Recall@K computation |
| `test_basic_context_metrics` | Context relevance & diversity |
| `test_failure_type_match_rate` | Filter match accuracy |
| `test_duplicate_detection` | Duplicate result detection |
| `test_empty_context` | No context handled gracefully |
| `test_unique_repos_count` | Unique repo diversity count |
| `test_basic_generation_metrics` | Generation quality scores |
| `test_type_alignment` | Triage type matches retrieved type |
| `test_type_misalignment` | Triage type differs from retrieved |
| `test_confidence_delta_with_baseline` | RAG confidence boost measurement |
| `test_no_context_low_value` | No RAG context → low value score |
| `test_rag_value_score_range` | RAG value score stays in 0–1 |
| `test_full_report_structure` | Complete report has all sections |
| `test_grade_has_letter_and_score` | Grade includes letter + numeric score |
| `test_high_quality_gets_good_grade` | High-quality RAG gets A/B grade |

### 4.9 `test_step10.py` — Verifier + Rollback (Mocked)

| Test | Description |
|------|-------------|
| `test_verification_result_defaults` | Default dataclass values correct |
| `test_verification_result_to_dict` | Serialization to dict |
| `test_verification_result_failed_with_rollback` | Failed result includes rollback data |
| `test_rollback_result_defaults` | Default dataclass values correct |
| `test_rollback_result_to_dict` | Serialization to dict |
| `test_rollback_result_skipped` | Skipped status with reason |
| `test_verify_ci_passed` | CI success → verified status, no rollback |
| `test_verify_ci_failed_triggers_rollback` | CI failure → rollback triggered |
| `test_verify_not_fix_branch` | Non-fix/* branch → skipped |
| `test_verify_cancelled` | CI cancelled → treated as failure |
| `test_verify_rollback_blocked_by_killswitch` | Kill switch blocks rollback |
| `test_extract_event_id_from_branch` | Parse event ID from branch name |
| `test_anti_flapping` | Same event not rolled back twice |
| `test_rate_limit_exceeded` | Max rollbacks/hour enforced |
| `test_rollback_error_handling` | GitHub API errors handled gracefully |

### 4.10 `test_step11.py` — Observability + Kill Switch (Mocked)

| Test | Description |
|------|-------------|
| `test_metrics_noop_when_disabled` | NoOp metrics when METRICS_ENABLED=false |
| `test_metrics_labels` | Counter/histogram labels applied correctly |
| `test_all_metrics_exist` | All 7 counters + 1 histogram + 2 gauges present |
| `test_push_disabled` | Push skipped when no Pushgateway URL |
| `test_push_success` | Metrics pushed to Pushgateway |
| `test_push_failure_non_fatal` | Pushgateway error doesn't crash pipeline |
| `test_killswitch_dev_mode` | Kill switch always OFF in development |
| `test_killswitch_prod_off` | SSM returns "false" → pipeline runs |
| `test_killswitch_prod_on` | SSM returns "true" → pipeline halted |
| `test_killswitch_fail_safe` | SSM unreachable → assume ON (halt) |
| `test_killswitch_cache` | Repeated calls use cached value (30s TTL) |
| `test_killswitch_clear_cache` | Cache cleared for testing |
| `test_decorator_allows` | `@require_kill_switch_off` allows when OFF |
| `test_decorator_blocks` | `@require_kill_switch_off` blocks when ON |

---

## 5. Writing New Tests

### 5.1 Test File Template

```python
"""
tests/test_new_module.py — Tests for step_x/new_module.py
"""

import pytest
from unittest.mock import patch, MagicMock


class TestNewModule:
    """Tests for NewModule class."""

    def test_happy_path(self):
        """Test normal operation."""
        # Arrange
        input_data = "..."
        
        # Act
        result = function_under_test(input_data)
        
        # Assert
        assert result is not None
        assert result["key"] == "expected_value"

    def test_edge_case(self):
        """Test boundary condition."""
        pass

    def test_error_handling(self):
        """Test error is handled gracefully."""
        with pytest.raises(ValueError):
            function_under_test(None)
```

### 5.2 Mocking External Services

```python
# Mock Groq LLM
@patch("step5.triage.Groq")
def test_with_mock_llm(self, mock_groq):
    mock_groq.return_value.chat.completions.create.return_value = ...

# Mock S3
@patch("shared.storage.boto3")
def test_with_mock_s3(self, mock_boto3):
    mock_boto3.client.return_value.put_object.return_value = {}

# Mock GitHub
@patch("shared.github_auth.Github")
def test_with_mock_github(self, mock_github):
    mock_github.return_value.get_repo.return_value = MagicMock()
```

---

## 6. Pipeline Simulation Test

The `test_local_pipeline.py` file runs a full pipeline simulation:

```bash
python test_local_pipeline.py
```

**What it tests:**
- Excerpt generation from real-looking CI logs
- Triage classification (keyword fallback)
- Plan generation (template fallback)
- Policy evaluation

**No external dependencies:** Runs entirely offline.

---

## 7. CI Integration (Planned)

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install dependencies
        run: uv pip install --system -r requirements.txt
      - run: pytest tests/ -v --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v4
```
