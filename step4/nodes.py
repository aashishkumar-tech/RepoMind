"""
step4/nodes.py — LangGraph Node Functions

HOW IT WORKS:
─────────────
Each function here is a "node" in the LangGraph directed graph.
A node receives the current pipeline state and returns a partial update.

NODE PATTERN:
    def my_node(state: PipelineState) -> dict:
        # Read from state
        data = state["some_field"]
        # Do work
        result = process(data)
        # Return partial update (LangGraph merges it into state)
        return {"result_field": result}

NODES IN THIS PIPELINE:
    1. evidence_node   → Retrieves similar past incidents from Qdrant
    2. triage_node     → Classifies the failure type using LLM
    3. planner_node    → Generates a fix plan / selects playbook
    4. policy_node     → Evaluates policy rules (allow/deny)

IMPORTANT:
    - Nodes are STATELESS functions (no self, no side effects beyond returns)
    - Each node is independently testable
    - Nodes communicate ONLY through the shared state dict
    - If a node fails, it sets state["error"] and state["status"] = "failed"

COMMUNICATION FLOW (through state):
    evidence_node: reads excerpt → writes similar_incidents
    triage_node:   reads excerpt, similar_incidents → writes triage
    planner_node:  reads excerpt, triage → writes plan_summary
    policy_node:   reads triage, plan_summary → writes policy, status
"""

from typing import Dict, Any

from shared.logger import get_logger

logger = get_logger("step4.nodes")


# ──────────────────────────────────────────────
# Node 1: Evidence Retrieval (Step 3)
# ──────────────────────────────────────────────
def evidence_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve similar past failures from Qdrant for RAG context.

    Reads: state["excerpt"], state["repo"]
    Writes: state["similar_incidents"], state["_rag_retrieval_ms"]

    If Qdrant is unavailable, returns empty list (non-fatal).
    Records retrieval latency for RAG evaluation metrics.
    """
    import time as _time

    excerpt = state.get("excerpt", "")
    repo = state.get("repo", "")
    event_id = state.get("event_id", "")

    logger.info("evidence_node_start", event_id=event_id)

    retrieval_start = _time.perf_counter()
    try:
        from step3.retriever import Retriever
        retriever = Retriever()
        similar = retriever.search_similar_failures(
            excerpt=excerpt,
            repo=repo,
            top_k=3,
        )
        retrieval_ms = (_time.perf_counter() - retrieval_start) * 1000

        # Evaluate retrieval quality
        try:
            from step3.rag_metrics import RAGEvaluator
            evaluator = RAGEvaluator()
            retrieval_metrics = evaluator.evaluate_retrieval(
                query_text=excerpt,
                results=similar,
                top_k_requested=3,
                latency_ms=retrieval_ms,
            )
            context_metrics = evaluator.evaluate_context_quality(
                query_text=excerpt,
                results=similar,
            )
            logger.info(
                "rag_retrieval_evaluated",
                event_id=event_id,
                hit_rate=retrieval_metrics["hit_rate"],
                mean_sim=retrieval_metrics["mean_similarity"],
                mrr=retrieval_metrics["mrr"],
                diversity=context_metrics["context_diversity"],
            )
        except Exception as me:
            logger.debug("rag_metrics_skipped", reason=str(me))
            retrieval_metrics = {}
            context_metrics = {}

        logger.info(
            "evidence_node_complete",
            event_id=event_id,
            matches=len(similar),
            retrieval_ms=round(retrieval_ms, 2),
        )
        return {
            "similar_incidents": similar,
            "_rag_retrieval_ms": retrieval_ms,
            "_rag_retrieval_metrics": retrieval_metrics,
            "_rag_context_metrics": context_metrics,
        }

    except Exception as e:
        retrieval_ms = (_time.perf_counter() - retrieval_start) * 1000
        logger.warning("evidence_node_failed", event_id=event_id, error=str(e))
        # Non-fatal: proceed without RAG context
        return {
            "similar_incidents": [],
            "_rag_retrieval_ms": retrieval_ms,
            "_rag_retrieval_metrics": {},
            "_rag_context_metrics": {},
        }


# ──────────────────────────────────────────────
# Node 2: Triage (Step 5)
# ──────────────────────────────────────────────
def triage_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify the CI failure using LLM + past incident context.

    Reads: state["excerpt"], state["repo"], state["similar_incidents"]
    Writes: state["triage"], state["_rag_generation_metrics"]

    If triage fails completely, sets status to "failed".
    Evaluates RAG generation impact after classification.
    """
    excerpt = state.get("excerpt", "")
    repo = state.get("repo", "")
    event_id = state.get("event_id", "")
    similar_incidents = state.get("similar_incidents", [])

    logger.info("triage_node_start", event_id=event_id)

    try:
        from step5.triage import TriageEngine
        engine = TriageEngine()
        triage = engine.classify(excerpt, repo)

        # Evaluate RAG generation impact (did retrieval help triage?)
        rag_generation_metrics = {}
        try:
            from step3.rag_metrics import RAGEvaluator
            evaluator = RAGEvaluator()
            rag_generation_metrics = evaluator.evaluate_generation_impact(
                query_text=excerpt,
                retrieved_contexts=similar_incidents,
                triage_result=triage,
            )
            logger.info(
                "rag_generation_evaluated",
                event_id=event_id,
                rag_value=rag_generation_metrics.get("rag_value_score", 0),
                grounding_rate=rag_generation_metrics.get("grounding_rate", 0),
                type_aligned=rag_generation_metrics.get("type_aligned_with_context", False),
            )
        except Exception as me:
            logger.debug("rag_generation_metrics_skipped", reason=str(me))

        logger.info(
            "triage_node_complete",
            event_id=event_id,
            failure_type=triage.get("failure_type"),
            confidence=triage.get("confidence"),
        )
        return {
            "triage": triage,
            "_rag_generation_metrics": rag_generation_metrics,
        }

    except Exception as e:
        logger.error("triage_node_failed", event_id=event_id, error=str(e))
        return {
            "triage": {
                "failure_type": "unknown",
                "confidence": 0.0,
                "summary": f"Triage failed: {str(e)}",
            },
            "error": f"Triage failed: {str(e)}",
            "status": "failed",
        }


# ──────────────────────────────────────────────
# Node 3: Plan Generation (Step 6)
# ──────────────────────────────────────────────
def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a fix plan based on triage results.

    Reads: state["triage"], state["excerpt"], state["repo"]
    Writes: state["plan_summary"]

    Selects a playbook and generates actions.
    """
    triage = state.get("triage", {})
    excerpt = state.get("excerpt", "")
    repo = state.get("repo", "")
    event_id = state.get("event_id", "")

    logger.info("planner_node_start", event_id=event_id)

    try:
        from step6.planner import Planner
        planner = Planner()
        plan = planner.generate_plan(triage, excerpt, repo)

        logger.info(
            "planner_node_complete",
            event_id=event_id,
            playbook_id=plan.get("playbook_id"),
        )
        return {"plan_summary": plan}

    except Exception as e:
        logger.error("planner_node_failed", event_id=event_id, error=str(e))
        return {
            "plan_summary": {
                "playbook_id": "unknown",
                "actions": [],
                "error": str(e),
            },
            "error": f"Planning failed: {str(e)}",
            "status": "failed",
        }


# ──────────────────────────────────────────────
# Node 4: Policy Evaluation (Step 7)
# ──────────────────────────────────────────────
def policy_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate safety policy — decide whether auto-fix is allowed.

    Reads: state["triage"], state["plan_summary"], state["repo"]
    Writes: state["policy"], state["status"]

    Sets status to "denied" if policy blocks the fix.
    """
    triage = state.get("triage", {})
    plan = state.get("plan_summary", {})
    repo = state.get("repo", "")
    event_id = state.get("event_id", "")

    logger.info("policy_node_start", event_id=event_id)

    try:
        from step7.policy import PolicyEngine
        engine = PolicyEngine()
        policy = engine.evaluate(triage, plan, repo)

        status = "denied" if policy.get("decision") == "deny" else "running"

        logger.info(
            "policy_node_complete",
            event_id=event_id,
            decision=policy.get("decision"),
            reason=policy.get("reason"),
        )
        return {"policy": policy, "status": status}

    except Exception as e:
        logger.error("policy_node_failed", event_id=event_id, error=str(e))
        # Fail closed — deny if policy engine errors
        return {
            "policy": {
                "decision": "deny",
                "reason": f"Policy engine error: {str(e)}",
                "rules_triggered": ["error_fallback"],
            },
            "error": f"Policy failed: {str(e)}",
            "status": "denied",
        }
