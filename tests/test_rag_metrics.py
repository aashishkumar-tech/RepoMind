"""
tests/test_rag_metrics.py — Unit tests for RAG Evaluation Metrics

Tests all four metric categories:
    1. Retrieval metrics (similarity, hit rate, MRR, staleness)
    2. Context quality metrics (relevance, diversity, freshness)
    3. Generation impact metrics (confidence delta, grounding, RAG value)
    4. Full evaluation report (grade, composite scores)
"""

import pytest
from datetime import datetime, timezone, timedelta

from step3.rag_metrics import RAGEvaluator, evaluate_rag


# ──────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────
def _make_result(score=0.8, failure_type="dependency_error", repo="user/repo",
                 event_id="evt-001", text_preview="ModuleNotFoundError flask",
                 timestamp=None):
    """Create a mock search result dict."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "score": score,
        "event_id": event_id,
        "repo": repo,
        "embedding_type": "excerpt",
        "failure_type": failure_type,
        "confidence": 0.85,
        "text_preview": text_preview,
        "timestamp": timestamp,
    }


def _make_results_set():
    """Create a diverse set of results for testing."""
    now = datetime.now(timezone.utc)
    return [
        _make_result(score=0.92, failure_type="dependency_error", event_id="evt-001",
                     text_preview="ModuleNotFoundError No module named flask",
                     timestamp=(now - timedelta(days=2)).isoformat()),
        _make_result(score=0.78, failure_type="dependency_error", event_id="evt-002",
                     text_preview="pip install failed package not found numpy",
                     timestamp=(now - timedelta(days=5)).isoformat()),
        _make_result(score=0.65, failure_type="import_error", event_id="evt-003",
                     text_preview="ImportError cannot import name utils",
                     timestamp=(now - timedelta(days=10)).isoformat()),
    ]


def _make_triage():
    """Create a mock triage result."""
    return {
        "failure_type": "dependency_error",
        "confidence": 0.92,
        "summary": "Missing flask module dependency not found in requirements",
        "affected_package": "flask",
    }


# ──────────────────────────────────────────────
# Retrieval Metrics Tests
# ──────────────────────────────────────────────
class TestRetrievalMetrics:
    """Test retrieval quality evaluation."""

    def setup_method(self):
        self.evaluator = RAGEvaluator()

    def test_basic_retrieval_metrics(self):
        """Should compute all core retrieval metrics."""
        results = _make_results_set()
        metrics = self.evaluator.evaluate_retrieval(
            query_text="ModuleNotFoundError: No module named 'flask'",
            results=results,
            top_k_requested=5,
            latency_ms=42.5,
        )

        assert metrics["hit_rate"] == 1.0
        assert metrics["result_count"] == 3
        assert metrics["top_k_requested"] == 5
        assert 0 < metrics["recall_at_k"] <= 1.0
        assert 0 < metrics["mean_similarity"] <= 1.0
        assert metrics["max_similarity"] == 0.92
        assert metrics["min_similarity"] == 0.65
        assert metrics["similarity_spread"] > 0
        assert metrics["retrieval_latency_ms"] == 42.5

    def test_empty_results(self):
        """Empty results should yield zero metrics."""
        metrics = self.evaluator.evaluate_retrieval(
            query_text="some query",
            results=[],
            top_k_requested=5,
        )

        assert metrics["hit_rate"] == 0.0
        assert metrics["result_count"] == 0
        assert metrics["mean_similarity"] == 0.0
        assert metrics["max_similarity"] == 0.0
        assert metrics["mrr"] == 0.0

    def test_mrr_with_strong_match(self):
        """MRR should reflect position of first strong match."""
        results = [
            _make_result(score=0.5),   # below threshold
            _make_result(score=0.8),   # above threshold (rank 2)
            _make_result(score=0.9),
        ]
        metrics = self.evaluator.evaluate_retrieval(
            query_text="test", results=results, top_k_requested=3,
        )
        assert metrics["mrr"] == 0.5  # 1/2 (second position)

    def test_mrr_with_top_match(self):
        """MRR = 1.0 when first result is strong."""
        results = [_make_result(score=0.85)]
        metrics = self.evaluator.evaluate_retrieval(
            query_text="test", results=results, top_k_requested=3,
        )
        assert metrics["mrr"] == 1.0

    def test_score_distribution_buckets(self):
        """Should correctly bucket scores into high/medium/low."""
        results = [
            _make_result(score=0.90),  # high
            _make_result(score=0.80),  # high
            _make_result(score=0.50),  # medium
            _make_result(score=0.30),  # low
        ]
        metrics = self.evaluator.evaluate_retrieval(
            query_text="test", results=results, top_k_requested=5,
        )
        assert metrics["score_distribution"]["high"] == 2
        assert metrics["score_distribution"]["medium"] == 1
        assert metrics["score_distribution"]["low"] == 1

    def test_stale_results(self):
        """Should detect stale results (>30 days old)."""
        now = datetime.now(timezone.utc)
        results = [
            _make_result(score=0.8, timestamp=(now - timedelta(days=5)).isoformat()),
            _make_result(score=0.7, timestamp=(now - timedelta(days=45)).isoformat()),
            _make_result(score=0.6, timestamp=(now - timedelta(days=60)).isoformat()),
        ]
        metrics = self.evaluator.evaluate_retrieval(
            query_text="test", results=results, top_k_requested=3,
        )
        # 2 out of 3 are stale (>30 days)
        assert abs(metrics["stale_ratio"] - 0.6667) < 0.01

    def test_recall_at_k(self):
        """Recall should be result_count / top_k_requested."""
        results = [_make_result(score=0.8), _make_result(score=0.7)]
        metrics = self.evaluator.evaluate_retrieval(
            query_text="test", results=results, top_k_requested=5,
        )
        assert metrics["recall_at_k"] == 0.4  # 2/5


# ──────────────────────────────────────────────
# Context Quality Tests
# ──────────────────────────────────────────────
class TestContextQuality:
    """Test context quality evaluation."""

    def setup_method(self):
        self.evaluator = RAGEvaluator()

    def test_basic_context_metrics(self):
        """Should compute diversity, freshness, duplicates."""
        results = _make_results_set()
        metrics = self.evaluator.evaluate_context_quality(
            query_text="ModuleNotFoundError",
            results=results,
        )

        assert metrics["context_diversity"] == 2  # dependency_error + import_error
        assert "dependency_error" in metrics["unique_failure_types"]
        assert "import_error" in metrics["unique_failure_types"]
        assert metrics["duplicate_ratio"] == 0.0  # all unique event IDs
        assert metrics["context_relevance_avg"] > 0

    def test_failure_type_match_rate(self):
        """Should compute match rate against expected type."""
        results = [
            _make_result(failure_type="dependency_error"),
            _make_result(failure_type="dependency_error"),
            _make_result(failure_type="import_error"),
        ]
        metrics = self.evaluator.evaluate_context_quality(
            query_text="test",
            results=results,
            expected_failure_type="dependency_error",
        )
        assert abs(metrics["failure_type_match_rate"] - 0.6667) < 0.01

    def test_duplicate_detection(self):
        """Should detect duplicate event IDs."""
        results = [
            _make_result(event_id="evt-001"),
            _make_result(event_id="evt-001"),  # duplicate
            _make_result(event_id="evt-002"),
        ]
        metrics = self.evaluator.evaluate_context_quality(
            query_text="test", results=results,
        )
        assert abs(metrics["duplicate_ratio"] - 0.3333) < 0.01

    def test_empty_context(self):
        """Empty results should return zero metrics."""
        metrics = self.evaluator.evaluate_context_quality(
            query_text="test", results=[],
        )
        assert metrics["context_diversity"] == 0
        assert metrics["context_relevance_avg"] == 0.0
        assert metrics["duplicate_ratio"] == 0.0

    def test_unique_repos_count(self):
        """Should count unique repositories."""
        results = [
            _make_result(repo="user/repo-a"),
            _make_result(repo="user/repo-b"),
            _make_result(repo="user/repo-a"),
        ]
        metrics = self.evaluator.evaluate_context_quality(
            query_text="test", results=results,
        )
        assert metrics["unique_repos"] == 2


# ──────────────────────────────────────────────
# Generation Impact Tests
# ──────────────────────────────────────────────
class TestGenerationImpact:
    """Test generation impact evaluation."""

    def setup_method(self):
        self.evaluator = RAGEvaluator()

    def test_basic_generation_metrics(self):
        """Should compute confidence and grounding metrics."""
        results = _make_results_set()
        triage = _make_triage()

        metrics = self.evaluator.evaluate_generation_impact(
            query_text="ModuleNotFoundError: No module named 'flask'",
            retrieved_contexts=results,
            triage_result=triage,
        )

        assert metrics["rag_confidence"] == 0.92
        assert metrics["context_count"] == 3
        assert "rag_value_score" in metrics
        assert 0 <= metrics["rag_value_score"] <= 1.0

    def test_type_alignment(self):
        """Should detect when triage type matches context types."""
        results = [_make_result(failure_type="dependency_error")]
        triage = {"failure_type": "dependency_error", "confidence": 0.9, "summary": "dep error"}

        metrics = self.evaluator.evaluate_generation_impact(
            query_text="test",
            retrieved_contexts=results,
            triage_result=triage,
        )
        assert metrics["type_aligned_with_context"] is True

    def test_type_misalignment(self):
        """Should detect when triage type does NOT match context."""
        results = [_make_result(failure_type="syntax_error")]
        triage = {"failure_type": "dependency_error", "confidence": 0.9, "summary": "dep error"}

        metrics = self.evaluator.evaluate_generation_impact(
            query_text="test",
            retrieved_contexts=results,
            triage_result=triage,
        )
        assert metrics["type_aligned_with_context"] is False

    def test_confidence_delta_with_baseline(self):
        """Should compute confidence improvement from RAG."""
        results = [_make_result(score=0.8)]
        triage_with_rag = {"failure_type": "dependency_error", "confidence": 0.92, "summary": "test"}
        triage_without_rag = {"failure_type": "dependency_error", "confidence": 0.65, "summary": "test"}

        metrics = self.evaluator.evaluate_generation_impact(
            query_text="test",
            retrieved_contexts=results,
            triage_result=triage_with_rag,
            triage_without_rag=triage_without_rag,
        )
        assert metrics["confidence_delta"] == pytest.approx(0.27, abs=0.01)

    def test_no_context_low_value(self):
        """With no retrieved context, RAG value should be low."""
        triage = {"failure_type": "unknown", "confidence": 0.3, "summary": "unknown error"}

        metrics = self.evaluator.evaluate_generation_impact(
            query_text="some error",
            retrieved_contexts=[],
            triage_result=triage,
        )
        assert metrics["rag_value_score"] < 0.5
        assert metrics["context_count"] == 0

    def test_rag_value_score_range(self):
        """RAG value score should always be 0-1."""
        for _ in range(10):
            import random
            results = [_make_result(score=random.uniform(0.1, 1.0)) for _ in range(3)]
            triage = {"failure_type": "test_failure", "confidence": random.uniform(0, 1), "summary": "test"}

            metrics = self.evaluator.evaluate_generation_impact(
                query_text="test",
                retrieved_contexts=results,
                triage_result=triage,
            )
            assert 0.0 <= metrics["rag_value_score"] <= 1.0


# ──────────────────────────────────────────────
# Full Evaluation Tests
# ──────────────────────────────────────────────
class TestFullEvaluation:
    """Test the complete RAG evaluation report."""

    def setup_method(self):
        self.evaluator = RAGEvaluator()

    def test_full_report_structure(self):
        """Full report should have all four sections + grade."""
        results = _make_results_set()
        triage = _make_triage()

        report = self.evaluator.full_evaluation(
            query_text="ModuleNotFoundError: No module named 'flask'",
            results=results,
            triage_result=triage,
            top_k_requested=3,
            retrieval_latency_ms=45.0,
            pipeline_latency_ms=1200.0,
        )

        assert "retrieval" in report
        assert "context_quality" in report
        assert "generation_impact" in report
        assert "end_to_end" in report
        assert "grade" in report
        assert "timestamp" in report

    def test_grade_has_letter_and_score(self):
        """Grade should have letter (A-F) and numeric score."""
        results = _make_results_set()
        triage = _make_triage()

        report = self.evaluator.full_evaluation(
            query_text="test", results=results, triage_result=triage,
        )

        assert report["grade"]["letter"] in ("A", "B", "C", "D", "F")
        assert 0 <= report["grade"]["score"] <= 1.0
        assert "retrieval_score" in report["grade"]
        assert "context_score" in report["grade"]
        assert "generation_score" in report["grade"]

    def test_high_quality_gets_good_grade(self):
        """Strong retrieval + high confidence should get A or B."""
        results = [
            _make_result(score=0.95, failure_type="dependency_error"),
            _make_result(score=0.88, failure_type="dependency_error"),
            _make_result(score=0.82, failure_type="dependency_error"),
        ]
        triage = {
            "failure_type": "dependency_error",
            "confidence": 0.95,
            "summary": "ModuleNotFoundError flask dependency not found module",
        }

        report = self.evaluator.full_evaluation(
            query_text="ModuleNotFoundError flask",
            results=results,
            triage_result=triage,
            top_k_requested=3,
        )
        assert report["grade"]["letter"] in ("A", "B")

    def test_empty_results_gets_poor_grade(self):
        """No retrieval results should get D or F."""
        triage = {"failure_type": "unknown", "confidence": 0.2, "summary": "unknown"}

        report = self.evaluator.full_evaluation(
            query_text="some error",
            results=[],
            triage_result=triage,
            top_k_requested=5,
        )
        assert report["grade"]["letter"] in ("D", "F")

    def test_rag_latency_percentage(self):
        """RAG latency should be correctly computed as % of pipeline."""
        results = [_make_result(score=0.8)]
        triage = _make_triage()

        report = self.evaluator.full_evaluation(
            query_text="test", results=results, triage_result=triage,
            retrieval_latency_ms=120.0, pipeline_latency_ms=1200.0,
        )
        assert report["end_to_end"]["rag_latency_pct"] == 10.0

    def test_zero_pipeline_latency(self):
        """Zero pipeline time should not cause division by zero."""
        report = self.evaluator.full_evaluation(
            query_text="test", results=[], triage_result={},
            pipeline_latency_ms=0.0,
        )
        assert report["end_to_end"]["rag_latency_pct"] == 0.0


# ──────────────────────────────────────────────
# Convenience Function Tests
# ──────────────────────────────────────────────
class TestConvenienceFunction:
    """Test the evaluate_rag() shorthand."""

    def test_evaluate_rag_returns_report(self):
        """evaluate_rag() should return a full report dict."""
        results = _make_results_set()
        triage = _make_triage()

        report = evaluate_rag(
            query_text="ModuleNotFoundError",
            results=results,
            triage_result=triage,
            top_k_requested=3,
            retrieval_latency_ms=50.0,
            pipeline_latency_ms=1000.0,
        )

        assert "retrieval" in report
        assert "grade" in report
        assert report["grade"]["letter"] in ("A", "B", "C", "D", "F")

    def test_evaluate_rag_with_empty_inputs(self):
        """Should handle empty inputs gracefully."""
        report = evaluate_rag(
            query_text="",
            results=[],
            triage_result={},
        )

        assert report["retrieval"]["hit_rate"] == 0.0
        assert report["grade"]["letter"] in ("D", "F")
