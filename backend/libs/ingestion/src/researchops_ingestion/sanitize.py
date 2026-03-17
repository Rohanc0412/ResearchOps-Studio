"""
Text sanitization with prompt injection defense.

This module provides:
- HTML tag removal with BeautifulSoup
- Control character removal
- Unicode normalization
- Prompt injection risk detection
"""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

from bs4 import BeautifulSoup


class SanitizationResult(TypedDict):
    """Result of text sanitization."""

    text: str
    """Sanitized text with HTML and control chars removed."""

    risk_flags: dict[str, bool]
    """Detected risks: prompt_injection, excessive_repetition, etc."""


# Prompt injection patterns (fail-closed: flag suspicious patterns)
_INJECTION_PATTERNS = [
    # Direct instruction attempts
    re.compile(r"ignore (previous|all|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard (previous|all|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"forget (previous|all|above|prior) (instructions?|prompts?|rules?)", re.IGNORECASE),
    # System prompt leakage attempts
    re.compile(r"(show|print|display|reveal|output) (your|the) (system |initial )?(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"what (is|are) your (system |initial )?(prompt|instructions?)", re.IGNORECASE),
    # Role manipulation
    re.compile(r"you are now (a |an )?[a-z]+", re.IGNORECASE),
    re.compile(r"act as (a |an )?[a-z]+", re.IGNORECASE),
    re.compile(r"(pretend|behave) (to be|like) (a |an )?[a-z]+", re.IGNORECASE),
    # Common delimiters used in prompt injection
    re.compile(r"<\|.*?\|>", re.IGNORECASE),
    re.compile(r"\[\[.*?\]\]", re.IGNORECASE),
    # Suspicious instruction markers
    re.compile(r"^(system|user|assistant|bot|ai):", re.IGNORECASE | re.MULTILINE),
]


def _remove_html(text: str) -> str:
    """Remove HTML tags using BeautifulSoup."""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text()


def _remove_control_chars(text: str) -> str:
    """Remove control characters except newlines, tabs, and carriage returns."""
    # Keep \n, \t, \r
    return "".join(ch for ch in text if ch in ("\n", "\t", "\r") or not unicodedata.category(ch).startswith("C"))


def _normalize_whitespace(text: str) -> str:
    """Normalize excessive whitespace."""
    # Replace multiple spaces with single space (but preserve newlines)
    text = re.sub(r"[ \t]+", " ", text)
    # Replace more than 2 consecutive newlines with 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_prompt_injection(text: str) -> bool:
    """Detect potential prompt injection attempts."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _detect_excessive_repetition(text: str) -> bool:
    """Detect excessive character or phrase repetition (often used in attacks)."""
    # Check for same character repeated >50 times
    if re.search(r"(.)\1{50,}", text):
        return True
    # Check for same word repeated >20 times
    if re.search(r"\b(\w+)\b(\s+\1\b){20,}", text, re.IGNORECASE):
        return True
    return False


def sanitize_text(raw_text: str) -> SanitizationResult:
    """
    Sanitize text by removing HTML, control chars, normalizing whitespace,
    and detecting prompt injection risks.

    Args:
        raw_text: Raw text from connector (may contain HTML, control chars, etc.)

    Returns:
        SanitizationResult with cleaned text and risk flags

    Example:
        >>> result = sanitize_text("<p>Hello world!</p>\\x00\\x01")
        >>> result["text"]
        'Hello world!'
        >>> result["risk_flags"]["prompt_injection"]
        False
    """
    # Step 1: Remove HTML
    text = _remove_html(raw_text)

    # Step 2: Remove control characters
    text = _remove_control_chars(text)

    # Step 3: Normalize Unicode (NFC = canonical composition)
    text = unicodedata.normalize("NFC", text)

    # Step 4: Normalize whitespace
    text = _normalize_whitespace(text)

    # Step 5: Detect risks (before text is stored)
    risk_flags = {
        "prompt_injection": _detect_prompt_injection(text),
        "excessive_repetition": _detect_excessive_repetition(text),
    }

    return SanitizationResult(text=text, risk_flags=risk_flags)
