"""
step3/rag_metrics.py — RAG Evaluation Metrics

HOW IT WORKS:
─────────────
Evaluates the quality of our RAG (Retrieval-Augmented Generation) pipeline
by measuring retrieval and generation quality at every inference call.

WHY WE NEED THIS:
    RAG systems can silently degrade:
    - Embeddings might drift (new failure types not well represented)
    - Retrieved context might be irrelevant (high similarity but wrong domain)
    - LLM might ignore retrieved context (RAG adds no value)
    - Vector DB index might go stale (no recent incidents indexed)
    Without metrics, we can't tell if RAG is helping or hurting triage accuracy.

METRICS COMPUTED:
─────────────────
1. RETRIEVAL METRICS (Step 3 → Qdrant search quality):
    - hit_rate            → Did we find ANY results above threshold?
    - mean_similarity     → Average cosine similarity of top-K results
    - max_similarity      → Best match score (proxy for "exact match found")
    - min_similarity      → Worst match in top-K (quality floor)
    - similarity_spread   → max - min (diversity of results)
    - result_count        → How many results returned vs requested
    - retrieval_latency   → Time to embed query + search Qdrant (ms)
    - score_distribution  → Histogram buckets of similarity scores
    - filter_match_rate   → % of results matching repo/type filters
    - stale_ratio         → % of results older than N days

2. CONTEXT QUALITY METRICS (Are retrieved docs useful?):
    - context_relevance   → Cosine sim between query and each retrieved doc
    - failure_type_match  → Do retrieved incidents share the same failure_type?
    - context_diversity   → Unique failure_types in retrieved set
    - context_freshness   → Avg age of retrieved incidents (days)
    - duplicate_ratio     → % of results from same event_id (redundancy)

3. GENERATION IMPACT METRICS (Did RAG help the LLM?):
    - confidence_delta    → Triage confidence WITH vs WITHOUT RAG context
    - answer_grounding    → Does triage output reference retrieved evidence?
    - rag_utilization     → Did the LLM actually use the retrieved context?
    - hallucination_flag  → Triage mentions facts not in excerpt or context

4. END-TO-END METRICS (Pipeline-level RAG health):
    - rag_latency_pct     → RAG time as % of total pipeline time
    - index_freshness     → Time since last Qdrant upsert
    - collection_size     → Total vectors in Qdrant collection
    - embedding_dim_check → Verify stored dim matches current model

USAGE:
    from step3.rag_metrics import RAGEvaluator
    evaluator = RAGEvaluator()

    # After retrieval
    retrieval_metrics = evaluator.evaluate_retrieval(
        query_text="ModuleNotFoundError: No module named 'flask'",
        results=[...],          # SearchResult objects
        top_k_requested=5,
        latency_ms=45.2,
    )

    # After triage (with RAG context)
    generation_metrics = evaluator.evaluate_generation_impact(
        query_text="ModuleNotFoundError...",
        retrieved_contexts=[...],
        triage_result={"failure_type": "dependency_error", "confidence": 0.92},
    )

    # Full pipeline evaluation
    full_report = evaluator.full_evaluation(
        query_text=excerpt,
        results=similar_incidents,
        triage_result=triage,
        top_k_requested=3,
        retrieval_latency_ms=45.2,
        pipeline_latency_ms=1200.0,
    )

COMMUNICATION:
─────────────
Called by:
    step4/nodes.py      → evidence_node evaluates retrieval quality
    step4/graph.py      → run_pipeline logs full RAG evaluation
    step2/worker.py     → worker logs RAG metrics to timeline/S3
    monitoring/         → dashboard reads these metrics for display
"""

import time
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from shared.logger import get_logger

logger = get_logger("step3.rag_metrics")


class RAGEvaluator:
    """
    Evaluates RAG pipeline quality with retrieval, context,
    generation impact, and end-to-end metrics.
    """

    # ──────────────────────────────────────────────
    # Configurable thresholds
    # ──────────────────────────────────────────────
    HIGH_SIMILARITY_THRESHOLD = 0.75    # "strong match" above this
    LOW_SIMILARITY_THRESHOLD = 0.40     # "weak match" below this
    STALE_DAYS_THRESHOLD = 30           # incidents older than this = stale
    MIN_USEFUL_RESULTS = 1              # at least 1 result for "hit"

    def evaluate_retrieval(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
        top_k_requested: int = 5,
        latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Evaluate retrieval quality from Qdrant search results.

        Args:
            query_text: The original query/excerpt text
            results: List of search result dicts (with "score", "event_id", etc.)
            top_k_requested: How many results were requested
            latency_ms: Time taken for embed + search (milliseconds)

        Returns:
            Dict of retrieval quality metrics
        """
        scores = [r.get("score", 0.0) for r in results]
        result_count = len(results)

        # Core similarity metrics
        mean_sim = sum(scores) / len(scores) if scores else 0.0
        max_sim = max(scores) if scores else 0.0
        min_sim = min(scores) if scores else 0.0
        spread = max_sim - min_sim

        # Score distribution buckets
        buckets = {"high": 0, "medium": 0, "low": 0}
        for s in scores:
            if s >= self.HIGH_SIMILARITY_THRESHOLD:
                buckets["high"] += 1
            elif s >= self.LOW_SIMILARITY_THRESHOLD:
                buckets["medium"] += 1
            else:
                buckets["low"] += 1

        # Hit rate
        hit_rate = 1.0 if result_count >= self.MIN_USEFUL_RESULTS else 0.0

        # Recall proxy (how many of requested top_k were returned)
        recall_at_k = result_count / top_k_requested if top_k_requested > 0 else 0.0

        # MRR (Mean Reciprocal Rank) — position of first strong match
        mrr = 0.0
        for i, s in enumerate(scores):
            if s >= self.HIGH_SIMILARITY_THRESHOLD:
                mrr = 1.0 / (i + 1)
                break

        # Stale ratio
        stale_count = 0
        now = datetime.now(timezone.utc)
        for r in results:
            ts = r.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_days = (now - dt).days
                    if age_days > self.STALE_DAYS_THRESHOLD:
                        stale_count += 1
                except (ValueError, TypeError):
                    pass
        stale_ratio = stale_count / result_count if result_count > 0 else 0.0

        metrics = {
            "hit_rate": hit_rate,
            "result_count": result_count,
            "top_k_requested": top_k_requested,
            "recall_at_k": round(recall_at_k, 4),
            "mrr": round(mrr, 4),
            "mean_similarity": round(mean_sim, 4),
            "max_similarity": round(max_sim, 4),
            "min_similarity": round(min_sim, 4),
            "similarity_spread": round(spread, 4),
            "score_distribution": buckets,
            "stale_ratio": round(stale_ratio, 4),
            "retrieval_latency_ms": round(latency_ms, 2),
        }

        logger.info("retrieval_metrics", **metrics)
        return metrics

    def evaluate_context_quality(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
        expected_failure_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate the quality/relevance of retrieved context documents.

        Args:
            query_text: The original query/excerpt
            results: Search results with metadata
            expected_failure_type: If known, the correct failure type

        Returns:
            Dict of context quality metrics
        """
        result_count = len(results)
        if result_count == 0:
            return {
                "context_relevance_avg": 0.0,
                "failure_type_match_rate": 0.0,
                "context_diversity": 0,
                "unique_failure_types": [],
                "unique_repos": 0,
                "duplicate_ratio": 0.0,
                "context_freshness_avg_days": 0.0,
            }

        # Failure type match rate
        failure_types = [r.get("failure_type", "unknown") for r in results]
        unique_types = list(set(failure_types))

        type_match_rate = 0.0
        if expected_failure_type:
            matches = sum(1 for ft in failure_types if ft == expected_failure_type)
            type_match_rate = matches / result_count

        # Diversity (unique failure types)
        diversity = len(unique_types)

        # Unique repos
        repos = set(r.get("repo", "") for r in results)
        unique_repos = len(repos)

        # Duplicate detection (same event_id appearing multiple times)
        event_ids = [r.get("event_id", "") for r in results]
        unique_events = len(set(event_ids))
        duplicate_ratio = 1.0 - (unique_events / result_count) if result_count > 0 else 0.0

        # Context freshness
        ages = []
        now = datetime.now(timezone.utc)
        for r in results:
            ts = r.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ages.append((now - dt).days)
                except (ValueError, TypeError):
                    pass
        avg_age = sum(ages) / len(ages) if ages else 0.0

        # Context relevance (use similarity scores as proxy)
        scores = [r.get("score", 0.0) for r in results]
        relevance_avg = sum(scores) / len(scores) if scores else 0.0

        metrics = {
            "context_relevance_avg": round(relevance_avg, 4),
            "failure_type_match_rate": round(type_match_rate, 4),
            "context_diversity": diversity,
            "unique_failure_types": unique_types,
            "unique_repos": unique_repos,
            "duplicate_ratio": round(duplicate_ratio, 4),
            "context_freshness_avg_days": round(avg_age, 1),
        }

        logger.info("context_quality_metrics", **metrics)
        return metrics

    def evaluate_generation_impact(
        self,
        query_text: str,
        retrieved_contexts: List[Dict[str, Any]],
        triage_result: Dict[str, Any],
        triage_without_rag: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate whether RAG actually improved the LLM's triage output.

        Measures if retrieved context was utilized and beneficial.

        Args:
            query_text: The original excerpt
            retrieved_contexts: What was retrieved from Qdrant
            triage_result: The final triage output (WITH RAG context)
            triage_without_rag: Optional — triage output WITHOUT RAG (for A/B)

        Returns:
            Dict of generation impact metrics
        """
        # Confidence analysis
        rag_confidence = triage_result.get("confidence", 0.0)

        # Confidence delta (if we have a no-RAG baseline)
        confidence_delta = 0.0
        if triage_without_rag:
            no_rag_confidence = triage_without_rag.get("confidence", 0.0)
            confidence_delta = rag_confidence - no_rag_confidence

        # RAG utilization — check if triage references failure types from context
        context_types = set(r.get("failure_type", "") for r in retrieved_contexts)
        triage_type = triage_result.get("failure_type", "")
        type_from_context = triage_type in context_types if context_types else False

        # Answer grounding — check if triage summary references context evidence
        triage_summary = triage_result.get("summary", "").lower()
        context_previews = [r.get("text_preview", "").lower() for r in retrieved_contexts]

        grounding_signals = 0
        for preview in context_previews:
            # Check if key terms from context appear in triage summary
            if preview:
                preview_words = set(preview.split()[:20])  # first 20 words
                summary_words = set(triage_summary.split())
                overlap = len(preview_words & summary_words)
                if overlap >= 3:
                    grounding_signals += 1

        grounding_rate = grounding_signals / len(retrieved_contexts) if retrieved_contexts else 0.0

        # RAG value score (composite: did retrieval improve outcome?)
        rag_value_score = self._compute_rag_value_score(
            hit_rate=1.0 if retrieved_contexts else 0.0,
            confidence=rag_confidence,
            confidence_delta=confidence_delta,
            type_from_context=type_from_context,
            grounding_rate=grounding_rate,
        )

        metrics = {
            "rag_confidence": round(rag_confidence, 4),
            "confidence_delta": round(confidence_delta, 4),
            "type_aligned_with_context": type_from_context,
            "grounding_rate": round(grounding_rate, 4),
            "grounding_signals": grounding_signals,
            "context_count": len(retrieved_contexts),
            "rag_value_score": round(rag_value_score, 4),
        }

        logger.info("generation_impact_metrics", **metrics)
        return metrics

    def full_evaluation(
        self,
        query_text: str,
        results: List[Dict[str, Any]],
        triage_result: Dict[str, Any],
        top_k_requested: int = 5,
        retrieval_latency_ms: float = 0.0,
        pipeline_latency_ms: float = 0.0,
        triage_without_rag: Optional[Dict[str, Any]] = None,
        expected_failure_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run ALL RAG evaluation metrics and return a unified report.

        This is the single-call entry point for full RAG evaluation.

        Args:
            query_text: The CI failure excerpt
            results: Qdrant search results
            triage_result: Final triage output
            top_k_requested: Number of results requested
            retrieval_latency_ms: Retrieval time in ms
            pipeline_latency_ms: Total pipeline time in ms
            triage_without_rag: Optional baseline (no RAG) for A/B
            expected_failure_type: Ground truth if known

        Returns:
            Complete RAG evaluation report with all metric categories
        """
        # 1. Retrieval metrics
        retrieval = self.evaluate_retrieval(
            query_text=query_text,
            results=results,
            top_k_requested=top_k_requested,
            latency_ms=retrieval_latency_ms,
        )

        # 2. Context quality
        context = self.evaluate_context_quality(
            query_text=query_text,
            results=results,
            expected_failure_type=expected_failure_type,
        )

        # 3. Generation impact
        generation = self.evaluate_generation_impact(
            query_text=query_text,
            retrieved_contexts=results,
            triage_result=triage_result,
            triage_without_rag=triage_without_rag,
        )

        # 4. End-to-end metrics
        rag_latency_pct = 0.0
        if pipeline_latency_ms > 0:
            rag_latency_pct = (retrieval_latency_ms / pipeline_latency_ms) * 100

        e2e = {
            "rag_latency_pct": round(rag_latency_pct, 2),
            "pipeline_latency_ms": round(pipeline_latency_ms, 2),
            "retrieval_latency_ms": round(retrieval_latency_ms, 2),
        }

        # 5. Overall RAG health grade
        grade = self._compute_rag_grade(retrieval, context, generation)

        report = {
            "retrieval": retrieval,
            "context_quality": context,
            "generation_impact": generation,
            "end_to_end": e2e,
            "grade": grade,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "rag_full_evaluation",
            grade=grade["letter"],
            score=grade["score"],
            hit_rate=retrieval["hit_rate"],
            mean_sim=retrieval["mean_similarity"],
            rag_value=generation["rag_value_score"],
        )

        return report

    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────

    def _compute_rag_value_score(
        self,
        hit_rate: float,
        confidence: float,
        confidence_delta: float,
        type_from_context: bool,
        grounding_rate: float,
    ) -> float:
        """
        Compute a composite RAG value score (0.0 to 1.0).

        Weights:
            - 25%  hit_rate (did we find anything?)
            - 25%  confidence (how confident is the triage?)
            - 20%  confidence_delta (did RAG improve confidence?)
            - 15%  type_alignment (does triage match context types?)
            - 15%  grounding (does triage reference context?)
        """
        # Normalize confidence_delta to 0-1 range (clamp -0.5 to 0.5 → 0 to 1)
        delta_norm = max(0.0, min(1.0, (confidence_delta + 0.5)))

        score = (
            0.25 * hit_rate
            + 0.25 * confidence
            + 0.20 * delta_norm
            + 0.15 * (1.0 if type_from_context else 0.0)
            + 0.15 * grounding_rate
        )
        return max(0.0, min(1.0, score))

    def _compute_rag_grade(
        self,
        retrieval: Dict[str, Any],
        context: Dict[str, Any],
        generation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compute an overall letter grade for RAG quality.

        A (0.85+)  → Excellent: strong matches, high confidence, context used
        B (0.70+)  → Good: decent retrieval, reasonable confidence
        C (0.55+)  → Fair: some results found, moderate quality
        D (0.40+)  → Poor: weak matches, low confidence
        F (<0.40)  → Failing: RAG not adding value

        Returns:
            Dict with letter grade, numeric score, and breakdown
        """
        # Weighted components
        retrieval_score = (
            0.3 * retrieval.get("hit_rate", 0)
            + 0.3 * retrieval.get("mean_similarity", 0)
            + 0.2 * retrieval.get("recall_at_k", 0)
            + 0.2 * retrieval.get("mrr", 0)
        )

        context_score = (
            0.4 * context.get("context_relevance_avg", 0)
            + 0.3 * context.get("failure_type_match_rate", 0)
            + 0.2 * (1.0 - context.get("duplicate_ratio", 0))
            + 0.1 * min(1.0, context.get("context_diversity", 0) / 3.0)
        )

        generation_score = generation.get("rag_value_score", 0)

        # Overall: 40% retrieval, 30% context, 30% generation
        overall = (
            0.40 * retrieval_score
            + 0.30 * context_score
            + 0.30 * generation_score
        )

        # Letter grade
        if overall >= 0.85:
            letter = "A"
        elif overall >= 0.70:
            letter = "B"
        elif overall >= 0.55:
            letter = "C"
        elif overall >= 0.40:
            letter = "D"
        else:
            letter = "F"

        return {
            "letter": letter,
            "score": round(overall, 4),
            "retrieval_score": round(retrieval_score, 4),
            "context_score": round(context_score, 4),
            "generation_score": round(generation_score, 4),
        }


# ──────────────────────────────────────────────
# Convenience function for pipeline integration
# ──────────────────────────────────────────────
def evaluate_rag(
    query_text: str,
    results: List[Dict[str, Any]],
    triage_result: Dict[str, Any],
    top_k_requested: int = 3,
    retrieval_latency_ms: float = 0.0,
    pipeline_latency_ms: float = 0.0,
) -> Dict[str, Any]:
    """
    Convenience function — runs full RAG evaluation in one call.

    Designed to be called directly from step4/nodes.py or step2/worker.py:

        from step3.rag_metrics import evaluate_rag
        rag_report = evaluate_rag(
            query_text=excerpt,
            results=similar_incidents,
            triage_result=triage,
            retrieval_latency_ms=evidence_time,
            pipeline_latency_ms=total_time,
        )
    """
    evaluator = RAGEvaluator()
    return evaluator.full_evaluation(
        query_text=query_text,
        results=results,
        triage_result=triage_result,
        top_k_requested=top_k_requested,
        retrieval_latency_ms=retrieval_latency_ms,
        pipeline_latency_ms=pipeline_latency_ms,
    )
