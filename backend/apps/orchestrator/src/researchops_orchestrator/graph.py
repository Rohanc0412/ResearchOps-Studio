"""
LangGraph workflow definition for the orchestrator.

Defines the StateGraph with all nodes and conditional edges.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from researchops_core.orchestrator.state import EvaluatorDecision, OrchestratorState
from researchops_orchestrator.nodes import (
    evidence_pack_node,
    evaluator_node,
    exporter_node,
    outliner_node,
    repair_agent_node,
    retriever_node,
    writer_node,
)


# Node display names for logging
NODE_DISPLAY_NAMES = {
    "retriever": "Retriever",
    "outliner": "Outliner",
    "evidence_pack": "Evidence Pack",
    "writer": "Writer",
    "evaluator": "Evaluator",
    "repair_agent": "Repair Agent",
    "exporter": "Exporter",
}


def create_orchestrator_graph(session: Session) -> StateGraph:
    """
    Create the orchestrator StateGraph.

    Graph structure:
    1. Retriever
    2. Outliner
    3. EvidencePack
    4. Writer
    5. Evaluator -> (STOP_SUCCESS -> Exporter -> END)
                  -> (CONTINUE_REPAIR -> RepairAgent -> Writer)
                  -> (CONTINUE_RETRIEVE -> Retriever)
                  -> (CONTINUE_REWRITE -> Writer)

    Args:
        session: Database session to pass to all nodes

    Returns:
        Compiled StateGraph
    """
    # Create graph
    workflow = StateGraph(OrchestratorState)

    # Wrap nodes to inject session and add logging
    def wrap_node(node_func):
        """Wrapper to inject session into node and log execution."""
        node_name = node_func.__name__.replace("_node", "")
        display_name = NODE_DISPLAY_NAMES.get(node_name, node_name)

        def wrapped(state: OrchestratorState) -> dict[str, Any]:
            """Wrapped node function."""
            start = time.time()
            result_state = node_func(state, session)
            elapsed = time.time() - start
            return result_state.dict()

        return wrapped

    # Add nodes
    workflow.add_node("retriever", wrap_node(retriever_node))
    workflow.add_node("outliner", wrap_node(outliner_node))
    workflow.add_node("evidence_pack", wrap_node(evidence_pack_node))
    workflow.add_node("writer", wrap_node(writer_node))
    workflow.add_node("evaluator", wrap_node(evaluator_node))
    workflow.add_node("repair_agent", wrap_node(repair_agent_node))
    workflow.add_node("exporter", wrap_node(exporter_node))

    # Set entry point
    workflow.set_entry_point("retriever")

    # Linear flow: retriever -> outliner -> evidence_pack -> writer
    workflow.add_edge("retriever", "outliner")
    workflow.add_edge("outliner", "evidence_pack")
    workflow.add_edge("evidence_pack", "writer")

    # Evaluation pipeline: writer -> evaluator
    workflow.add_edge("writer", "evaluator")

    # Conditional routing from evaluator
    def evaluator_router(state: OrchestratorState) -> str:
        """Route based on evaluator decision."""
        decision = state.evaluator_decision

        if decision == EvaluatorDecision.STOP_SUCCESS:
            return "exporter"
        elif decision == EvaluatorDecision.CONTINUE_REPAIR:
            return "repair_agent"
        elif decision == EvaluatorDecision.CONTINUE_RETRIEVE:
            return "retriever"
        elif decision == EvaluatorDecision.CONTINUE_REWRITE:
            return "writer"
        else:
            # Default: export
            return "exporter"

    workflow.add_conditional_edges(
        "evaluator",
        evaluator_router,
        {
            "exporter": "exporter",
            "repair_agent": "repair_agent",
            "retriever": "retriever",
            "writer": "writer",
        },
    )

    # Repair loop: repair_agent -> writer (re-draft)
    workflow.add_edge("repair_agent", "writer")

    # Exporter is the final node
    workflow.add_edge("exporter", END)

    # Compile graph
    compiled_graph = workflow.compile()

    return compiled_graph


def increment_iteration(state: OrchestratorState) -> OrchestratorState:
    """
    Increment iteration count.

    Called after each evaluation cycle.

    Args:
        state: Current state

    Returns:
        Updated state
    """
    state.iteration_count += 1
    return state
