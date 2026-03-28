import sys
import os
import threading
import time
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_section_searches_run_in_parallel():
    """_parallel_search_sections runs search_snippets for all sections concurrently."""
    call_times: list[float] = []
    call_lock = threading.Lock()

    def fake_search_snippets(**kwargs):
        with call_lock:
            call_times.append(time.monotonic())
        time.sleep(0.10)  # simulate pgvector query latency
        return []

    import services.orchestrator.nodes.evidence_packer as ep

    fake_engine = mock.MagicMock()
    fake_session_instance = mock.MagicMock()
    # Make Session(engine) work as a context manager
    fake_session_ctx = mock.MagicMock()
    fake_session_ctx.__enter__ = mock.Mock(return_value=fake_session_instance)
    fake_session_ctx.__exit__ = mock.Mock(return_value=False)

    section_queries = [(f"s{i}", [0.1 * i] * 10) for i in range(4)]

    with mock.patch("services.orchestrator.nodes.evidence_packer.search_snippets", side_effect=fake_search_snippets):
        with mock.patch("services.orchestrator.nodes.evidence_packer.Session", return_value=fake_session_ctx):
            with mock.patch.dict(os.environ, {"EVIDENCE_PACK_PARALLEL_SECTIONS": "4"}):
                start = time.monotonic()
                results = ep._parallel_search_sections(
                    section_queries=section_queries,
                    engine=fake_engine,
                    tenant_id="t1",
                    embedding_model="test-model",
                    source_ids=["s1"],
                    search_limit=60,
                    min_similarity=0.35,
                    min_required=5,
                )
                elapsed = time.monotonic() - start

    # Parallelism check: total elapsed is far less than sequential would take (4 * 0.10 = 0.40s)
    # All 4 calls must start within 1.5× the sleep window (well under sequential spread of 0.30s)
    call_times.sort()
    assert call_times[-1] - call_times[0] < 0.15, (
        f"Calls did not start concurrently: spread={call_times[-1]-call_times[0]:.3f}s"
    )
    assert elapsed < 0.70, f"Sections took too long: elapsed={elapsed:.3f}s"
    assert len(results) == 4
    assert all(section_id in results for section_id, _ in section_queries)
