"""
LangGraph workflow definition for the orchestrator.

Defines the StateGraph with all nodes and conditional edges.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from researchops_core.orchestrator.state import EvaluatorDecision, OrchestratorState
from researchops_orchestrator.nodes import (
    claim_extractor_node,
    citation_validator_node,
    evaluator_node,
    exporter_node,
    fact_checker_node,
    outliner_node,
    question_generator_node,
    repair_agent_node,
    retriever_node,
    source_vetter_node,
    writer_node,
)


def create_orchestrator_graph(session: Session) -> StateGraph:
    """
    Create the orchestrator StateGraph.

    Graph structure:
    1. QuestionGenerator
    2. Retriever
    3. SourceVetter
    4. Outliner
    5. Writer
    6. ClaimExtractor
    7. CitationValidator
    8. FactChecker
    9. Evaluator -> (STOP_SUCCESS -> Exporter -> END)
                  -> (CONTINUE_REPAIR -> RepairAgent -> ClaimExtractor)
                  -> (CONTINUE_RETRIEVE -> Retriever)
                  -> (CONTINUE_REWRITE -> Writer)

    Args:
        session: Database session to pass to all nodes

    Returns:
        Compiled StateGraph
    """
    # Create graph
    workflow = StateGraph(OrchestratorState)

    # Wrap nodes to inject session
    def wrap_node(node_func):
        """Wrapper to inject session into node."""

        def wrapped(state: OrchestratorState) -> dict[str, Any]:
            """Wrapped node function."""
            result_state = node_func(state, session)
            # Increment iteration count after each cycle
            return result_state.dict()

        return wrapped

    # Add nodes
    workflow.add_node("question_generator", wrap_node(question_generator_node))
    workflow.add_node("retriever", wrap_node(retriever_node))
    workflow.add_node("source_vetter", wrap_node(source_vetter_node))
    workflow.add_node("outliner", wrap_node(outliner_node))
    workflow.add_node("writer", wrap_node(writer_node))
    workflow.add_node("claim_extractor", wrap_node(claim_extractor_node))
    workflow.add_node("citation_validator", wrap_node(citation_validator_node))
    workflow.add_node("fact_checker", wrap_node(fact_checker_node))
    workflow.add_node("evaluator", wrap_node(evaluator_node))
    workflow.add_node("repair_agent", wrap_node(repair_agent_node))
    workflow.add_node("exporter", wrap_node(exporter_node))

    # Set entry point
    workflow.set_entry_point("question_generator")

    # Linear flow: question_generator -> retriever -> source_vetter -> outliner -> writer
    workflow.add_edge("question_generator", "retriever")
    workflow.add_edge("retriever", "source_vetter")
    workflow.add_edge("source_vetter", "outliner")
    workflow.add_edge("outliner", "writer")

    # Validation pipeline: writer -> claim_extractor -> citation_validator -> fact_checker -> evaluator
    workflow.add_edge("writer", "claim_extractor")
    workflow.add_edge("claim_extractor", "citation_validator")
    workflow.add_edge("citation_validator", "fact_checker")
    workflow.add_edge("fact_checker", "evaluator")

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

    # Repair loop: repair_agent -> claim_extractor (re-validate)
    workflow.add_edge("repair_agent", "claim_extractor")

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
