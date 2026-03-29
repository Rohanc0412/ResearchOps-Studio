import sys
import os
import threading
import time
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_mcp_queries_fire_in_parallel():
    """
    With 4 plan entries and RETRIEVER_MCP_PARALLEL_QUERIES=4,
    all 4 searches should overlap in time (not run serially).
    """
    call_times: list[float] = []
    call_lock = threading.Lock()

    def fake_search(query, max_results):
        with call_lock:
            call_times.append(time.monotonic())
        time.sleep(0.05)  # simulate network latency
        return []

    from dataclasses import dataclass

    @dataclass
    class FakePlan:
        query: str
        intent: str

    plans = [FakePlan(query=f"q{i}", intent="survey") for i in range(4)]
    mock_connector = mock.MagicMock()
    mock_connector.search.side_effect = lambda query, max_results: fake_search(query, max_results)
    mock_connector.sources = ["openalex"]

    import services.orchestrator.nodes.retriever as ret

    start = time.monotonic()
    with mock.patch.dict(os.environ, {"RETRIEVER_MCP_PARALLEL_QUERIES": "4"}):
        results = ret._parallel_mcp_search(plans, mock_connector, mcp_max_per_source=5)
    elapsed = time.monotonic() - start

    # Parallelism check: all calls should start before the first one finished (50ms sleep)
    call_times.sort()
    assert call_times[-1] - call_times[0] < 0.05, (
        f"Calls did not start concurrently: spread={call_times[-1]-call_times[0]:.3f}s"
    )
    # Generous upper-bound: 4 serial calls would take 0.2s, parallel should be much less
    assert elapsed < 0.40, f"Queries took too long: elapsed={elapsed:.3f}s"
    assert mock_connector.search.call_count == 4


def test_mcp_search_results_combined_correctly():
    """All sources from all queries are returned."""
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class FakePlan:
        query: str
        intent: str

    from libs.connectors.base import RetrievedSource, CanonicalIdentifier, SourceType

    def make_source(title, connector="openalex"):
        return RetrievedSource(
            canonical_id=CanonicalIdentifier(openalex_id=title),
            title=title,
            authors=[],
            year=2024,
            source_type=SourceType.PAPER,
            abstract=None,
            full_text=None,
            url=None,
            pdf_url=None,
            connector=connector,
            retrieved_at=datetime.now(timezone.utc),
        )

    import services.orchestrator.nodes.retriever as ret

    plans = [FakePlan(query="q1", intent="survey"), FakePlan(query="q2", intent="methods")]
    mock_connector = mock.MagicMock()
    mock_connector.search.side_effect = [
        [make_source("paper-A"), make_source("paper-B")],
        [make_source("paper-C")],
    ]

    results = ret._parallel_mcp_search(plans, mock_connector, mcp_max_per_source=5)
    titles = {s.title for s in results}
    assert titles == {"paper-A", "paper-B", "paper-C"}


def test_mcp_search_sets_intent_metadata():
    """Intent and query metadata is set on each returned source's extra_metadata."""
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class FakePlan:
        query: str
        intent: str

    from libs.connectors.base import RetrievedSource, CanonicalIdentifier, SourceType

    def make_source(title):
        return RetrievedSource(
            canonical_id=CanonicalIdentifier(openalex_id=title),
            title=title, authors=[], year=2024,
            source_type=SourceType.PAPER, abstract=None, full_text=None,
            url=None, pdf_url=None, connector="openalex",
            retrieved_at=datetime.now(timezone.utc),
            extra_metadata={"existing_key": "value"},
        )

    import services.orchestrator.nodes.retriever as ret

    plan = FakePlan(query="neural nets", intent="methods")
    mock_connector = mock.MagicMock()
    mock_connector.search.return_value = [make_source("paper-X")]

    results = ret._parallel_mcp_search([plan], mock_connector, mcp_max_per_source=5)

    assert len(results) == 1
    meta = results[0].extra_metadata
    assert meta["intent"] == "methods"
    assert meta["query"] == "neural nets"
    assert meta["existing_key"] == "value"  # original metadata preserved
