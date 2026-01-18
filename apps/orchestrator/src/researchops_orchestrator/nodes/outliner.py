"""
Outliner node - creates a structured outline for the report.

Generates a hierarchical outline with sections and subsections.
Each section includes guidance on required evidence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    OutlineModel,
    OutlineSection,
)


@instrument_node("outline")
def outliner_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Create a structured outline for the report.

    Strategy:
    1. Standard research report structure
    2. Introduction, Methods, Results, Discussion
    3. Customize based on available sources

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with outline
    """
    user_query = state.user_query
    vetted_sources = state.vetted_sources

    # Create sections
    sections = []

    # 1. Executive Summary
    sections.append(
        OutlineSection(
            section_id="1",
            title="Executive Summary",
            description="High-level overview of key findings and recommendations",
            required_evidence=["key findings", "main conclusions"],
        )
    )

    # 2. Introduction
    sections.append(
        OutlineSection(
            section_id="2",
            title="Introduction",
            description="Background and motivation for the research topic",
            required_evidence=[user_query, f"background {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="2.1",
            title="Problem Statement",
            description="Clear articulation of the research problem",
            required_evidence=[f"challenges {user_query}", f"open problems {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="2.2",
            title="Research Questions",
            description="Key questions this research aims to answer",
            required_evidence=[user_query],
        )
    )

    # 3. Literature Review
    sections.append(
        OutlineSection(
            section_id="3",
            title="Literature Review",
            description="Survey of existing work and state of the art",
            required_evidence=[f"literature review {user_query}", f"state of the art {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="3.1",
            title="Foundational Work",
            description="Seminal papers and early developments",
            required_evidence=[f"foundational {user_query}", f"history {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="3.2",
            title="Recent Advances",
            description="Current state of the art and recent breakthroughs",
            required_evidence=[f"recent advances {user_query}", f"latest {user_query}"],
        )
    )

    # 4. Methods and Approaches
    sections.append(
        OutlineSection(
            section_id="4",
            title="Methods and Approaches",
            description="Techniques and methodologies used in this area",
            required_evidence=[f"methods {user_query}", f"techniques {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="4.1",
            title="Common Methodologies",
            description="Widely-used approaches and best practices",
            required_evidence=[f"best practices {user_query}", f"standard methods {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="4.2",
            title="Novel Techniques",
            description="Innovative or emerging approaches",
            required_evidence=[f"novel {user_query}", f"innovative {user_query}"],
        )
    )

    # 5. Findings and Results
    sections.append(
        OutlineSection(
            section_id="5",
            title="Key Findings",
            description="Main results and insights from the literature",
            required_evidence=[f"results {user_query}", f"findings {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="5.1",
            title="Empirical Results",
            description="Experimental findings and benchmarks",
            required_evidence=[f"benchmarks {user_query}", f"evaluation {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="5.2",
            title="Theoretical Insights",
            description="Conceptual and theoretical contributions",
            required_evidence=[f"theory {user_query}", f"insights {user_query}"],
        )
    )

    # 6. Applications
    sections.append(
        OutlineSection(
            section_id="6",
            title="Applications and Use Cases",
            description="Practical applications and real-world deployments",
            required_evidence=[f"applications {user_query}", f"use cases {user_query}"],
        )
    )

    # 7. Challenges and Limitations
    sections.append(
        OutlineSection(
            section_id="7",
            title="Challenges and Limitations",
            description="Current obstacles and areas for improvement",
            required_evidence=[f"challenges {user_query}", f"limitations {user_query}"],
        )
    )

    # 8. Future Directions
    sections.append(
        OutlineSection(
            section_id="8",
            title="Future Directions",
            description="Open problems and promising research directions",
            required_evidence=[f"future work {user_query}", f"open problems {user_query}"],
        )
    )

    # 9. Conclusion
    sections.append(
        OutlineSection(
            section_id="9",
            title="Conclusion",
            description="Summary of findings and recommendations",
            required_evidence=["summary", "recommendations"],
        )
    )

    # Create outline
    outline = OutlineModel(
        sections=sections,
        total_estimated_words=3000,  # Rough estimate: ~200 words per section
    )

    # Update state
    state.outline = outline

    return state
