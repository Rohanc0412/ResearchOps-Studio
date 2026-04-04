from nodes.retriever import _normalize_intent


def test_normalize_intent_section_prefix_passes_through():
    assert _normalize_intent("section:intro") == "section:intro"
    assert _normalize_intent("section:methods") == "section:methods"
    assert _normalize_intent("section:background_and_context") == "section:background and context"


def test_normalize_intent_existing_intents_unchanged():
    assert _normalize_intent("survey") == "survey"
    assert _normalize_intent("methods") == "methods"
    assert _normalize_intent("failure mode") == "failure modes"


def test_normalize_intent_unknown_returns_none():
    assert _normalize_intent("garbage") is None
    assert _normalize_intent("") is None
