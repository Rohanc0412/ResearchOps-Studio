from connectors.scientific_papers_mcp import SEARCHABLE_SOURCES


def test_core_not_in_searchable_sources():
    assert "core" not in SEARCHABLE_SOURCES


def test_expected_sources_present():
    assert set(SEARCHABLE_SOURCES) == {"openalex", "arxiv", "europepmc"}
