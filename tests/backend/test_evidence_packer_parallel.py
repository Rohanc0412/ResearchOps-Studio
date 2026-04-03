"""
Regression test: _parallel_search_sections_async runs search_snippets for all
sections concurrently via asyncio.gather, not OS threads.

Run from repo root:
    cd backend && python -m pytest ../tests/backend/test_evidence_packer_parallel.py -v
"""
import asyncio
import os
import sys
import time
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def _run_parallel_search(section_queries, call_times):
    """Helper that patches AsyncSession and search_snippets, then calls the async helper."""
    import services.orchestrator.nodes.evidence_packer as ep

    async def mock_run_sync(fn):
        # Record when this section's search starts
        call_times.append(time.monotonic())
        # Simulate pgvector query latency
        await asyncio.sleep(0.10)
        # Call fn with a fake sync session; return min_required results
        fake_session = mock.MagicMock()
        return fn(fake_session)

    mock_async_session = mock.MagicMock()
    mock_async_session.run_sync = mock_run_sync
    mock_async_session.__aenter__ = mock.AsyncMock(return_value=mock_async_session)
    mock_async_session.__aexit__ = mock.AsyncMock(return_value=False)

    fake_results = [
        {"snippet_id": f"snip{i}", "similarity": 0.9 - i * 0.1,
         "source_id": "src1", "snippet_text": "text", "char_start": 0, "char_end": 4}
        for i in range(5)
    ]

    with mock.patch(
        "services.orchestrator.nodes.evidence_packer.search_snippets",
        return_value=fake_results,
    ):
        with mock.patch(
            "services.orchestrator.nodes.evidence_packer.AsyncSession",
            return_value=mock_async_session,
        ):
            with mock.patch.dict(os.environ, {"EVIDENCE_PACK_PARALLEL_SECTIONS": "4"}):
                return await ep._parallel_search_sections_async(
                    section_queries=section_queries,
                    async_engine=mock.MagicMock(),
                    tenant_id="tenant-1",
                    embedding_model="test-model",
                    source_ids=["source-1"],
                    search_limit=60,
                    min_similarity=0.35,
                    min_required=5,
                )


def test_section_searches_run_concurrently_async():
    """_parallel_search_sections_async launches all sections concurrently."""
    section_queries = [(f"section-{i}", [[0.1 * i] * 10]) for i in range(4)]
    call_times: list[float] = []

    results = asyncio.run(_run_parallel_search(section_queries, call_times))

    # Concurrency check: all 4 sections should start within a narrow window
    # (well under the 0.10s sleep, which would be the sequential gap)
    call_times.sort()
    spread = call_times[-1] - call_times[0]
    assert spread < 0.08, (
        f"Sections did not start concurrently: spread={spread:.3f}s "
        f"(expected < 0.08s; if sequential, spread would be ~0.30s)"
    )

    # All 4 sections must be present in results
    assert len(results) == 4
    for section_id, _ in section_queries:
        assert section_id in results, f"Missing result for {section_id}"
