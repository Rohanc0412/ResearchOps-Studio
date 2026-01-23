from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class IntentDecision:
    mode: Literal["chat", "offer_pipeline"]
    confidence: float
    reason: str
    suggested_question: str | None = None


def classify_chat_intent(message: str) -> IntentDecision:
    text = (message or "").strip().lower()
    if not text:
        return IntentDecision(mode="chat", confidence=0.0, reason="empty_message")

    score = 0.0
    reasons: list[str] = []

    def bump(amount: float, reason: str) -> None:
        nonlocal score
        score += amount
        reasons.append(reason)

    if _contains_any(text, ["cite", "citation", "references", "sources", "evidence", "grounded"]):
        bump(0.45, "citations")
    if _contains_any(
        text,
        [
            "literature review",
            "systematic review",
            "survey",
            "state of the art",
            "sota",
            "meta analysis",
            "meta-analysis",
        ],
    ):
        bump(0.4, "review_request")
    if _contains_any(
        text,
        [
            "latest research",
            "recent papers",
            "recent studies",
            "compare papers",
            "benchmark",
            "peer reviewed",
            "peer-reviewed",
        ],
    ):
        bump(0.35, "recent_research")
    if _contains_any(text, ["report", "whitepaper", "multi section", "multi-section", "full report"]):
        bump(0.25, "report_request")
    if _contains_any(text, ["openalex", "arxiv", "papers", "studies"]):
        bump(0.2, "research_sources")
    if len(text.split()) > 120:
        bump(0.2, "long_request")

    if _contains_any(
        text,
        [
            "define",
            "what is",
            "explain",
            "rewrite",
            "summarize",
            "fix",
            "debug",
            "typo",
            "format",
        ],
    ):
        score -= 0.2

    score = max(0.0, min(1.0, score))
    if score >= 0.75:
        return IntentDecision(
            mode="offer_pipeline",
            confidence=score,
            reason=", ".join(sorted(set(reasons))) if reasons else "research_request",
            suggested_question=message.strip(),
        )

    return IntentDecision(
        mode="chat",
        confidence=1.0 - score,
        reason="quick_chat",
        suggested_question=message.strip(),
    )


def parse_consent_reply(
    user_message: str, pending_prompt: str | None = None
) -> Literal["yes", "no", "ambiguous", "new_topic"]:
    raw = (user_message or "").strip()
    if not raw:
        return "ambiguous"

    action = _action_token(raw)
    if action == "run_pipeline":
        return "yes"
    if action == "quick_answer":
        return "no"

    text = raw.lower()

    if _contains_any(
        text,
        [
            "yes",
            "yeah",
            "yep",
            "do it",
            "run it",
            "proceed",
            "start research",
            "start the research",
            "go ahead",
        ],
    ):
        return "yes"

    if _contains_any(
        text,
        [
            "no",
            "nope",
            "nah",
            "quick answer",
            "skip",
            "not now",
            "don't",
            "do not",
        ],
    ):
        return "no"

    if _looks_like_new_topic(text, pending_prompt):
        return "new_topic"

    if _contains_any(text, ["ok", "okay", "sure", "maybe", "alright"]):
        return "ambiguous"

    return "ambiguous"


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _action_token(text: str) -> str | None:
    if not text.startswith("__ACTION__:"):
        return None
    _, _, token = text.partition(":")
    token = token.strip().lower()
    return token or None


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _looks_like_new_topic(message: str, pending_prompt: str | None) -> bool:
    if not pending_prompt:
        return False
    msg_tokens = _tokenize(message)
    if not msg_tokens:
        return False
    prompt_tokens = _tokenize(pending_prompt)
    overlap = len(msg_tokens & prompt_tokens) / max(len(msg_tokens), 1)
    question_words = ("what", "why", "how", "when", "who", "which", "where", "can you", "could you")
    looks_like_question = "?" in message or message.strip().startswith(question_words)
    if overlap < 0.2 and (looks_like_question or len(msg_tokens) >= 6):
        return True
    return False
