"""Deterministic UK-viability check on a job's structured location field.

This is the lesson of prompt v4, measured and reverted: geography is a
lookup, not a judgment call. Asking the LLM to judge UK eligibility dropped
qualifies recall on the eval set (it could not reliably recognize smaller
UK towns), so location lives here - in plain, testable code - and the
classifier judges seniority only.

Policy:
- Unknown/empty location -> viable (never reject on missing data; most
  job-board sources are UK-filtered at the API anyway).
- Any UK signal (country, nation, or a UK city/town common in tech hiring)
  -> viable, including multi-location strings that list a UK office.
- Bare "remote" with no other country -> viable.
- "Remote, <country>" or any location with no UK signal -> not viable.
"""

import re

_UK_TOKENS = (
    "united kingdom",
    "uk",
    "u.k.",
    "gb",
    "great britain",
    "britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
    "london",
    "manchester",
    "birmingham",
    "edinburgh",
    "glasgow",
    "cambridge",
    "oxford",
    "bristol",
    "leeds",
    "cardiff",
    "belfast",
    "newcastle",
    "sheffield",
    "liverpool",
    "nottingham",
    "reading",
    "milton keynes",
    "brighton",
)

_TOKEN_PATTERN = re.compile(r"\b(" + "|".join(re.escape(t) for t in _UK_TOKENS) + r")\b")


def is_uk_viable(location: str | None) -> bool:
    """True if a UK-based person could plausibly work this job, judged from
    the structured location string alone."""
    if not location or not location.strip():
        return True
    text = location.lower()
    if _TOKEN_PATTERN.search(text):
        return True
    # bare remote (no country qualifier) is workable from anywhere
    return bool(re.fullmatch(r"\s*remote\s*", text))
