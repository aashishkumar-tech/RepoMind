"""
step4/models.py — Pydantic State Models for LangGraph Pipeline

HOW IT WORKS:
─────────────
Defines the shared state that flows through the LangGraph graph.

LangGraph uses a "state" object that every node reads from and writes to.
Think of it as a shared blackboard — each node picks up data, does its work,
and writes results back.

STATE LIFECYCLE:
    1. Graph starts with PipelineState (excerpt, repo, event_id)
    2. evidence_node   → reads excerpt, writes similar_incidents
    3. triage_node     → reads excerpt + similar_incidents, writes triage
    4. planner_node    → reads triage + excerpt, writes plan_summary
    5. policy_node     → reads triage + plan_summary, writes policy
    6. Final state     → all fields populated, returned to caller

WHY PYDANTIC + TYPED DICT:
    LangGraph expects a TypedDict or dataclass for state.
    We use TypedDict for graph state (LangGraph requirement)
    and Pydantic for input/output validation at the edges.

COMMUNICATION:
─────────────
step4/graph.py imports PipelineState and uses it as the graph's state schema.
Each node function receives and returns partial state updates.
"""

from typing import TypedDict, Optional, Dict, Any, List

from pydantic import BaseModel


# ──────────────────────────────────────────────
# LangGraph State (TypedDict — required by LangGraph)
# ──────────────────────────────────────────────
class PipelineState(TypedDict, total=False):
    """
    The shared state object that flows through the LangGraph graph.

    Every node reads what it needs and writes its results.
    LangGraph merges partial updates automatically.

    Fields:
        event_id:           Unique event identifier
        repo:               Full repo name (e.g. "user/mlproject")
        workflow_run_id:    GitHub workflow run ID
        run_url:            URL to the GitHub Actions run
        head_branch:        Branch that triggered the run
        head_sha:           Commit SHA

        excerpt:            Log excerpt from Step 2
        similar_incidents:  Past similar failures from Qdrant (Step 3)

        triage:             Failure classification result (Step 5)
        plan_summary:       Fix plan (Step 6)
        policy:             Policy evaluation result (Step 7)
        pr:                 PR creation result (Step 8)

        error:              Error message if a node fails
        status:             Pipeline status: "running" | "completed" | "failed" | "denied"
    """
    # Input (set by caller)
    event_id: str
    repo: str
    workflow_run_id: int
    run_url: str
    head_branch: str
    head_sha: str
    excerpt: str

    # Step 3: Evidence retrieval
    similar_incidents: List[Dict[str, Any]]

    # Step 5: Triage
    triage: Dict[str, Any]

    # Step 6: Plan
    plan_summary: Dict[str, Any]

    # Step 7: Policy
    policy: Dict[str, Any]

    # Step 8: PR
    pr: Dict[str, Any]

    # Control
    error: str
    status: str


# ──────────────────────────────────────────────
# Pydantic models for input/output validation
# ──────────────────────────────────────────────
class PipelineInput(BaseModel):
    """Validated input to start the LangGraph pipeline."""
    event_id: str
    repo: str
    workflow_run_id: int
    run_url: str
    head_branch: str = ""
    head_sha: str = ""
    excerpt: str


class PipelineOutput(BaseModel):
    """Validated output from the completed pipeline."""
    event_id: str
    repo: str
    status: str
    triage: Optional[Dict[str, Any]] = None
    plan_summary: Optional[Dict[str, Any]] = None
    policy: Optional[Dict[str, Any]] = None
    pr: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
