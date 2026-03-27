"""
step4/graph.py — LangGraph Pipeline Graph Definition

HOW IT WORKS:
─────────────
Defines the directed graph that orchestrates Steps 3→5→6→7.

    ┌──────────────┐
    │  START        │
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ evidence     │  ← Step 3: Retrieve similar past failures from Qdrant
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ triage       │  ← Step 5: Classify the failure with LLM
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ planner      │  ← Step 6: Generate fix plan / select playbook
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ policy       │  ← Step 7: Evaluate safety rules (allow/deny)
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │  END         │
    └──────────────┘

CONDITIONAL EDGES:
    After policy_node:
        if decision == "deny" → END (pipeline stops, no PR)
        if decision == "allow" → END (worker handles PR creation in Step 8)

    The graph returns the final state. The caller (worker.py) reads
    state["policy"]["decision"] and decides whether to proceed to Step 8.

WHY LANGGRAPH (NOT JUST SEQUENTIAL CALLS):
    - Visual graph for debugging and monitoring
    - Built-in state management and checkpointing
    - Easy to add parallel nodes, conditional branches, loops
    - Ready for Beta/GA expansion (human-in-the-loop, retries)

ALPHA SIMPLIFICATION:
    In Alpha, the graph is linear (no branching except policy deny).
    In Beta/GA, we'll add:
        - Parallel evidence retrieval
        - Human approval nodes
        - Retry loops
        - Verification feedback loops

USAGE:
    from step4.graph import run_pipeline
    result = run_pipeline(event_id, repo, excerpt, ...)
    if result["policy"]["decision"] == "allow":
        # proceed to Step 8 PR creation

COMMUNICATION:
─────────────
Worker (step2/worker.py) can call run_pipeline() as an alternative to
sequential step calls. Both approaches produce the same result.
"""

from typing import Dict, Any, Optional

from shared.logger import get_logger

logger = get_logger("step4.graph")


def _build_graph():
    """
    Build the LangGraph StateGraph.

    Imports LangGraph lazily — only when the graph is actually used.
    This avoids import errors when LangGraph isn't installed (e.g. in tests).
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.warning("langgraph_not_installed", msg="Falling back to sequential execution")
        return None

    from step4.models import PipelineState
    from step4.nodes import evidence_node, triage_node, planner_node, policy_node

    # ── Define the graph ──
    graph = StateGraph(PipelineState)

    # ── Add nodes ──
    graph.add_node("evidence", evidence_node)
    graph.add_node("triage", triage_node)
    graph.add_node("planner", planner_node)
    graph.add_node("policy", policy_node)

    # ── Define edges (linear flow) ──
    graph.set_entry_point("evidence")
    graph.add_edge("evidence", "triage")
    graph.add_edge("triage", "planner")
    graph.add_edge("planner", "policy")
    graph.add_edge("policy", END)

    # ── Compile ──
    compiled = graph.compile()
    logger.info("langgraph_compiled", nodes=["evidence", "triage", "planner", "policy"])
    return compiled


# Module-level compiled graph (lazy)
_compiled_graph = None


def get_graph():
    """Get or create the compiled graph (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


def run_pipeline(
    event_id: str,
    repo: str,
    workflow_run_id: int,
    run_url: str,
    excerpt: str,
    head_branch: str = "",
    head_sha: str = "",
) -> Dict[str, Any]:
    """
    Run the full LangGraph pipeline for a CI failure event.

    This is the main entry point for the LangGraph orchestration.
    If LangGraph is not installed, falls back to sequential execution.

    Args:
        event_id: Unique event identifier
        repo: Full repo name
        workflow_run_id: GitHub workflow run ID
        run_url: URL to the GitHub Actions run
        excerpt: Log excerpt from Step 2
        head_branch: Branch that triggered the run
        head_sha: Commit SHA

    Returns:
        Final pipeline state dict with triage, plan, policy results
    """
    initial_state = {
        "event_id": event_id,
        "repo": repo,
        "workflow_run_id": workflow_run_id,
        "run_url": run_url,
        "excerpt": excerpt,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "similar_incidents": [],
        "triage": {},
        "plan_summary": {},
        "policy": {},
        "pr": {},
        "error": "",
        "status": "running",
    }

    import time as _time
    pipeline_start = _time.perf_counter()

    graph = get_graph()

    if graph is not None:
        # ── LangGraph execution ──
        logger.info("pipeline_start_langgraph", event_id=event_id)
        try:
            final_state = graph.invoke(initial_state)
            pipeline_ms = (_time.perf_counter() - pipeline_start) * 1000
            final_state = dict(final_state)

            # Run full RAG evaluation
            final_state = _attach_rag_report(final_state, excerpt, pipeline_ms)

            logger.info(
                "pipeline_complete_langgraph",
                event_id=event_id,
                status=final_state.get("status"),
                pipeline_ms=round(pipeline_ms, 2),
            )
            return final_state
        except Exception as e:
            logger.error("pipeline_langgraph_error", event_id=event_id, error=str(e))
            # Fall through to sequential
            initial_state["error"] = str(e)

    # ── Fallback: Sequential execution ──
    logger.info("pipeline_start_sequential", event_id=event_id)
    result = _run_sequential(initial_state)

    pipeline_ms = (_time.perf_counter() - pipeline_start) * 1000
    result = _attach_rag_report(result, excerpt, pipeline_ms)

    return result


def _attach_rag_report(
    state: Dict[str, Any],
    excerpt: str,
    pipeline_ms: float,
) -> Dict[str, Any]:
    """
    Run full RAG evaluation and attach the report to pipeline state.

    Combines retrieval + context + generation metrics from nodes
    with end-to-end timing to produce a unified RAG quality report.
    """
    try:
        from step3.rag_metrics import evaluate_rag

        similar = state.get("similar_incidents", [])
        triage = state.get("triage", {})
        retrieval_ms = state.get("_rag_retrieval_ms", 0.0)

        rag_report = evaluate_rag(
            query_text=excerpt,
            results=similar,
            triage_result=triage,
            top_k_requested=3,
            retrieval_latency_ms=retrieval_ms,
            pipeline_latency_ms=pipeline_ms,
        )

        state["rag_evaluation"] = rag_report

        logger.info(
            "rag_report_attached",
            event_id=state.get("event_id", ""),
            grade=rag_report.get("grade", {}).get("letter", "?"),
            score=rag_report.get("grade", {}).get("score", 0),
        )
    except Exception as e:
        logger.debug("rag_report_skipped", reason=str(e))
        state["rag_evaluation"] = {}

    return state


def _run_sequential(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fallback: run nodes sequentially without LangGraph.

    Same logic, same nodes, same state — just called in order.
    Used when LangGraph isn't installed or fails.
    """
    from step4.nodes import evidence_node, triage_node, planner_node, policy_node

    event_id = state.get("event_id", "")

    # Node 1: Evidence
    try:
        update = evidence_node(state)
        state.update(update)
    except Exception as e:
        logger.warning("sequential_evidence_failed", event_id=event_id, error=str(e))
        state["similar_incidents"] = []

    # Node 2: Triage
    try:
        update = triage_node(state)
        state.update(update)
    except Exception as e:
        logger.error("sequential_triage_failed", event_id=event_id, error=str(e))
        state["status"] = "failed"
        state["error"] = str(e)
        return state

    # Node 3: Planner
    try:
        update = planner_node(state)
        state.update(update)
    except Exception as e:
        logger.error("sequential_planner_failed", event_id=event_id, error=str(e))
        state["status"] = "failed"
        state["error"] = str(e)
        return state

    # Node 4: Policy
    try:
        update = policy_node(state)
        state.update(update)
    except Exception as e:
        logger.error("sequential_policy_failed", event_id=event_id, error=str(e))
        state["status"] = "denied"
        state["error"] = str(e)

    if state.get("status") not in ("failed", "denied"):
        state["status"] = "completed"

    logger.info("pipeline_complete_sequential", event_id=event_id, status=state["status"])
    return state
