"""Exact-hash deduplication of job listings.

Cross-posted jobs (the same role listed once per location, or the same role
on multiple sources) waste classifier quota: each copy costs an API call for
the same verdict. This module provides content keys for grouping such copies
so only one representative per group needs classifying.

Two keys with different strictness:
- content_key: normalized company + title + description. Catches exact
  reposts (byte-identical content after whitespace/case normalization).
- title_key: normalized company + title only. Catches per-location reposts
  whose descriptions differ slightly - at the risk of over-merging genuinely
  different roles that share a title. Measure before trusting it.
"""

import hashlib
import re


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _digest(*parts: str) -> str:
    joined = "|".join(_normalize(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def content_key(job: dict) -> str:
    """Strict key: same company, title, AND description text."""
    return _digest(job.get("company", ""), job.get("title", ""), job.get("description", ""))


def title_key(job: dict) -> str:
    """Loose key: same company and title, regardless of description."""
    return _digest(job.get("company", ""), job.get("title", ""))


def group_by_key(jobs: list[dict], key_fn) -> dict[str, list[dict]]:
    """Group jobs by a key function, preserving within-group order."""
    groups: dict[str, list[dict]] = {}
    for job in jobs:
        groups.setdefault(key_fn(job), []).append(job)
    return groups
