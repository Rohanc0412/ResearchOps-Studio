"""
Exporter node - produces final artifacts.

Generates 3 artifacts:
1. literature_map.json - Structured source metadata
2. report.md - Final report with resolved citations
3. experiment_plan.md - Suggested next steps
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import OrchestratorState


@instrument_node("export")
def exporter_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Export final artifacts.

    Produces:
    1. literature_map.json - Source metadata for citation graph
    2. report.md - Final markdown report with resolved citations
    3. experiment_plan.md - Recommended next steps

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with artifacts
    """
    # Artifact 1: Literature Map
    literature_map = _generate_literature_map(state)

    # Artifact 2: Final Report
    final_report = _generate_final_report(state)

    # Artifact 3: Experiment Plan
    experiment_plan = _generate_experiment_plan(state)

    # Store artifacts
    state.artifacts = {
        "literature_map.json": json.dumps(literature_map, indent=2),
        "report.md": final_report,
        "experiment_plan.md": experiment_plan,
    }

    return state


def _generate_literature_map(state: OrchestratorState) -> dict:
    """
    Generate structured literature map.

    Args:
        state: Current state

    Returns:
        Dictionary with source metadata
    """
    sources = state.vetted_sources

    literature_map = {
        "query": state.user_query,
        "total_sources": len(sources),
        "sources": [],
    }

    for source in sources:
        source_dict = {
            "source_id": str(source.source_id),
            "canonical_id": source.canonical_id,
            "title": source.title,
            "authors": source.authors,
            "year": source.year,
            "url": source.url,
            "pdf_url": source.pdf_url,
            "connector": source.connector,
            "quality_score": source.quality_score,
        }
        literature_map["sources"].append(source_dict)

    return literature_map


def _generate_final_report(state: OrchestratorState) -> str:
    """
    Generate final markdown report with resolved citations.

    Converts [CITE:snippet_id] to proper markdown footnotes.

    Args:
        state: Current state

    Returns:
        Final report markdown
    """
    draft = state.draft_text
    evidence_snippets = state.evidence_snippets
    vetted_sources = state.vetted_sources

    # Build citation map (snippet_id -> source)
    citation_map = {}
    for snippet in evidence_snippets:
        source = next((s for s in vetted_sources if s.source_id == snippet.source_id), None)
        if source:
            citation_map[str(snippet.snippet_id)] = source

    # Replace citations with footnotes
    citation_counter = 0
    citation_ids_used = {}
    footnotes = []

    def replace_citation(match):
        nonlocal citation_counter
        snippet_id = match.group(1)

        # Check if we've seen this citation before
        if snippet_id in citation_ids_used:
            footnote_num = citation_ids_used[snippet_id]
        else:
            citation_counter += 1
            footnote_num = citation_counter
            citation_ids_used[snippet_id] = footnote_num

            # Add footnote
            source = citation_map.get(snippet_id)
            if source:
                authors_str = ", ".join(source.authors[:3]) if source.authors else "Unknown"
                if source.authors and len(source.authors) > 3:
                    authors_str += " et al."

                footnote = f"[^{footnote_num}]: {authors_str}. {source.title}. {source.year or 'n.d.'}."
                if source.url:
                    footnote += f" [{source.url}]({source.url})"
                footnotes.append(footnote)

        return f"[^{footnote_num}]"

    # Replace all citations
    import re

    final_text = re.sub(r"\[CITE:([a-f0-9-]+)\]", replace_citation, draft)

    # Append footnotes
    if footnotes:
        final_text += "\n\n---\n\n## References\n\n"
        final_text += "\n\n".join(footnotes)

    return final_text


def _generate_experiment_plan(state: OrchestratorState) -> str:
    """
    Generate experiment plan with suggested next steps.

    Args:
        state: Current state

    Returns:
        Experiment plan markdown
    """
    user_query = state.user_query

    plan = f"""# Experiment Plan: {user_query}

## Objective

Based on the literature review, this plan outlines recommended next steps for advancing research in {user_query}.

## Proposed Experiments

### Experiment 1: Baseline Implementation

**Goal:** Implement a baseline system using established methods from the literature.

**Steps:**
1. Select the most widely-cited approach from the literature review
2. Implement the baseline with standard parameters
3. Evaluate on standard benchmarks
4. Document results and limitations

**Expected Outcome:** Establish a performance baseline for comparison.

### Experiment 2: Novel Approach

**Goal:** Explore a novel technique identified from recent papers.

**Steps:**
1. Identify promising recent innovations from the literature
2. Design an experiment combining multiple techniques
3. Implement and test the novel approach
4. Compare against baseline

**Expected Outcome:** Determine if novel approaches improve over baseline.

### Experiment 3: Ablation Study

**Goal:** Understand which components contribute most to performance.

**Steps:**
1. Identify key components of the best-performing approach
2. Systematically remove each component
3. Measure impact on performance
4. Identify critical vs. optional components

**Expected Outcome:** Clear understanding of what drives performance.

## Evaluation Metrics

Based on the literature, key metrics to track:
- Primary: [Domain-specific metric]
- Secondary: Computational efficiency, scalability
- Qualitative: Ease of use, interpretability

## Resources Required

- Compute: [Estimate based on literature]
- Data: Public datasets identified in literature
- Time: 4-6 weeks for all three experiments

## Success Criteria

- Baseline matches reported performance in literature
- Novel approach shows statistically significant improvement
- Ablation study identifies 2-3 critical components

## Next Steps

1. Set up development environment
2. Gather required datasets
3. Implement baseline (Week 1-2)
4. Run Experiment 1 (Week 3)
5. Develop and test novel approach (Week 4-5)
6. Conduct ablation study (Week 6)
7. Write up results and submit findings

---

*Generated by ResearchOps Studio based on literature analysis*
"""

    return plan
