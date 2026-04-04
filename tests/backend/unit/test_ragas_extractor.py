from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.ragas_extractor import RagasExtractor


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    return client


@pytest.mark.asyncio
async def test_extract_returns_list_of_strings(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(return_value=[
        "AI is used in healthcare.",
        "Machine learning improves diagnosis accuracy.",
    ])):
        claims = await extractor.extract("AI is widely used in healthcare for diagnosis.", ["snippet 1"])
    assert isinstance(claims, list)
    assert all(isinstance(c, str) for c in claims)
    assert len(claims) == 2


@pytest.mark.asyncio
async def test_extract_returns_empty_on_llm_failure(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(side_effect=Exception("LLM error"))):
        claims = await extractor.extract("Some section text.", ["snippet"])
    assert claims == []


@pytest.mark.asyncio
async def test_extract_deduplicates_claims(mock_llm_client):
    extractor = RagasExtractor(llm_client=mock_llm_client)
    with patch.object(extractor, "_call_ragas", new=AsyncMock(return_value=[
        "AI is used in healthcare.",
        "AI is used in healthcare.",
        "Machine learning improves diagnosis.",
    ])):
        claims = await extractor.extract("...", ["snippet"])
    assert len(claims) == 2
