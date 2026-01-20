"""
QuestionGenerator node - generates diverse research queries.

Generates 5-20 queries based on the user's research goal.
Uses a simple rule-based approach (can be enhanced with LLM later).
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import OrchestratorState
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)


@instrument_node("question_generation")
def question_generator_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Generate diverse research queries from the user's input.

    Strategy:
    1. Use the user query as-is
    2. Generate variations (broader, narrower, related)
    3. Generate methodological queries
    4. Generate application queries

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with generated_queries populated
    """
    user_query = state.user_query
    research_goal = state.research_goal or user_query

    queries = []
    llm_queries = _generate_queries_with_llm(state)
    if llm_queries:
        queries.extend(llm_queries)
        logger.info(
            "question_generation_llm",
            extra={
                "run_id": str(state.run_id),
                "llm_provider": state.llm_provider,
                "llm_model": state.llm_model,
                "count": len(llm_queries),
            },
        )

    # 1. Original query
    queries.append(user_query)

    # 2. Broader queries
    queries.append(f"overview of {user_query}")
    queries.append(f"literature review {user_query}")
    queries.append(f"state of the art {user_query}")

    # 3. Narrower queries (extract key terms and focus on them)
    # Simple heuristic: take key nouns
    key_terms = _extract_key_terms(user_query)
    for term in key_terms[:3]:  # Top 3 terms
        queries.append(f"{term} research")
        queries.append(f"{term} methods")

    # 4. Methodological queries
    queries.append(f"methods for {user_query}")
    queries.append(f"techniques {user_query}")
    queries.append(f"approaches to {user_query}")

    # 5. Application queries
    queries.append(f"applications of {user_query}")
    queries.append(f"use cases {user_query}")

    # 6. Evaluation queries
    queries.append(f"evaluation {user_query}")
    queries.append(f"benchmarks {user_query}")

    # 7. Challenges and limitations
    queries.append(f"challenges in {user_query}")
    queries.append(f"limitations {user_query}")

    # 8. Future directions
    queries.append(f"future work {user_query}")
    queries.append(f"open problems {user_query}")

    # Deduplicate and limit to 20
    queries = list(dict.fromkeys(queries))[:20]

    # Update state
    state.generated_queries = queries
    logger.info(
        "question_generation_complete",
        extra={"run_id": str(state.run_id), "count": len(queries)},
    )

    return state


def _generate_queries_with_llm(state: OrchestratorState) -> list[str]:
    try:
        client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        logger.warning("llm_unavailable", extra={"error": str(exc)})
        return []

    if client is None:
        return []

    prompt = (
        "Generate 10-15 diverse academic search queries for the research topic below. "
        "Return one query per line, no numbering or extra text.\n\n"
        f"Topic: {state.user_query}\n"
    )
    system = "You generate concise scholarly search queries."
    try:
        response = client.generate(prompt, system=system, max_tokens=256, temperature=0.4)
    except LLMError as exc:
        logger.warning("llm_query_generation_failed", extra={"error": str(exc)})
        return []

    lines = [line.strip() for line in response.splitlines() if line.strip()]
    cleaned = []
    for line in lines:
        cleaned_line = re.sub(r"^[\W_]+", "", line).strip()
        cleaned_line = re.sub(r"^\d+[.)\s-]*", "", cleaned_line).strip()
        if cleaned_line:
            cleaned.append(cleaned_line)
    return cleaned[:20]


def _extract_key_terms(query: str) -> list[str]:
    """
    Extract key terms from query (simple heuristic).

    Filters out common words and returns remaining tokens.

    Args:
        query: User query string

    Returns:
        List of key terms
    """
    # Common stop words to filter
    stop_words = {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
        "must",
        "can",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "when",
        "where",
        "why",
        "how",
    }

    # Tokenize (simple split)
    tokens = query.lower().split()

    # Filter stop words and short tokens
    key_terms = [t for t in tokens if t not in stop_words and len(t) > 3]

    return key_terms
