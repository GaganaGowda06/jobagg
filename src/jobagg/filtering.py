"""Shared title-filtering logic used across job sources."""

import re

DEFAULT_EXCLUDE_WORDS = ("senior", "lead", "principal", "director", "staff", "head")

DEFAULT_INCLUDE_WORDS = (
    "data",
    "scientist",
    "analyst",
    "analytics",
    "machine learning",
    "ai",
    "ml",
)

# "ai" and "ml" get a negative lookbehind for a preceding "." - short words
# that also happen to be common startup/product TLDs (Gitar.ai, some.ml)
# would otherwise match a domain-style brand name that has nothing to do
# with the role. Every other include word keeps the plain \b...\b pattern.
_DOT_SENSITIVE_WORDS = {"ai", "ml"}

DEFAULT_FALSE_POSITIVE_PHRASES = (
    "data center",
    "data centers",
    "data centre",
    "data centres",
    "data entry",
    "tutor",
    "success manager",
)


def _word_pattern(word: str) -> str:
    if word in _DOT_SENSITIVE_WORDS:
        return rf"(?<!\.)\b{re.escape(word)}\b"
    return rf"\b{re.escape(word)}\b"


def _title_excluded(title: str, exclude_words: tuple[str, ...]) -> bool:
    """True if any exclude word appears as a whole word in the title."""
    lowered = title.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in exclude_words)


def _title_relevant(
    title: str,
    include_words: tuple[str, ...],
    false_positive_phrases: tuple[str, ...] = (),
) -> bool:
    """True if any include word/phrase appears as a whole word in the title,
    unless the title also matches a known false-positive phrase (e.g. "Data
    Center Technician" contains "data" but isn't a data role)."""
    lowered = title.lower()
    if any(re.search(rf"\b{re.escape(phrase)}\b", lowered) for phrase in false_positive_phrases):
        return False
    return any(re.search(_word_pattern(word), lowered) for word in include_words)
