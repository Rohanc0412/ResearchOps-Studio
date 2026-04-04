from unittest.mock import MagicMock

import pytest
from core.claim_verifier import ClaimVerifier


@pytest.fixture
def mock_llm_client():
    return MagicMock()


def _make_verifier(llm_client, llm_response: str):
    verifier = ClaimVerifier(llm_client=llm_client)
    llm_client.generate.return_value = llm_response
    return verifier


def test_verify_returns_verdict_per_claim(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "supported", "citations": ["s1"], "notes": ""}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Drug X improves outcomes."],
        snippets=[{"id": "s1", "text": "Drug X significantly improves patient outcomes."}],
    )
    assert len(results) == 1
    assert results[0]["verdict"] == "supported"
    assert results[0]["claim_index"] == 0


def test_verify_filters_invalid_verdicts(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "hallucinated", "citations": [], "notes": ""}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Some claim."],
        snippets=[],
    )
    # "hallucinated" is not in ALLOWED_VERDICTS → defaults to "unsupported"
    assert results[0]["verdict"] == "unsupported"


def test_verify_returns_unsupported_on_llm_failure(mock_llm_client):
    mock_llm_client.generate.side_effect = Exception("LLM unavailable")
    verifier = ClaimVerifier(llm_client=mock_llm_client)
    results = verifier.verify(
        claims=["Claim A.", "Claim B."],
        snippets=[],
    )
    assert len(results) == 2
    assert all(r["verdict"] == "unsupported" for r in results)


def test_verify_returns_one_result_per_claim(mock_llm_client):
    llm_response = '{"verdicts": [{"claim_index": 0, "verdict": "supported", "citations": [], "notes": ""}, {"claim_index": 1, "verdict": "contradicted", "citations": ["s1"], "notes": "Direct contradiction"}]}'
    verifier = _make_verifier(mock_llm_client, llm_response)
    results = verifier.verify(
        claims=["Claim A.", "Claim B."],
        snippets=[{"id": "s1", "text": "Evidence text."}],
    )
    assert len(results) == 2
    assert results[1]["verdict"] == "contradicted"
