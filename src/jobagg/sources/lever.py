"""Lever job board client.

Like Greenhouse, Lever has no keyword search - each company's postings are
fetched in full via its own site slug, one company at a time. Unlike
Greenhouse, postings don't include the company name (the URL already
identifies it), and the substantive job content is often split across
descriptionPlain and a separate "lists" array of labeled sections
(requirements, benefits, salary), not contained in one field.
"""

import logging
import re
from datetime import UTC, datetime
from html import unescape

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobagg.filtering import (
    DEFAULT_EXCLUDE_WORDS,
    DEFAULT_FALSE_POSITIVE_PHRASES,
    DEFAULT_INCLUDE_WORDS,
    _title_excluded,
    _title_relevant,
)

logger = logging.getLogger(__name__)

GLOBAL_BASE_URL = "https://api.lever.co/v0/postings"
EU_BASE_URL = "https://api.eu.lever.co/v0/postings"

_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _clean_html(raw: str | None) -> str | None:
    """Strip HTML tags from a lists[].content entry down to plain text.
    Unlike Greenhouse's content field, Lever's isn't double-escaped, but
    running unescape() first is still correct and handles any entities
    (&amp;, &nbsp;) that appear inside otherwise-plain HTML."""
    if not raw:
        return None
    unescaped = unescape(raw)
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


def _build_description(posting: dict) -> str | None:
    """Lever splits job content between descriptionPlain (often just a
    generic company intro) and a "lists" array of labeled sections that
    frequently hold the actual requirements, responsibilities, and salary -
    using descriptionPlain alone can mean missing most of the real content."""
    parts = []
    opening = posting.get("descriptionPlain") or posting.get("openingPlain")
    if opening:
        parts.append(opening.strip())
    for item in posting.get("lists") or []:
        heading = (item.get("text") or "").strip()
        body = _clean_html(item.get("content"))
        section = f"{heading}\n{body}" if heading and body else heading or body
        if section:
            parts.append(section)
    return "\n\n".join(parts) if parts else None


def _normalize_job(posting: dict, company: str) -> dict:
    """Convert Lever's raw posting dict into our common job shape.

    company is passed in explicitly, not read from the posting - Lever's
    API doesn't include it, since the site slug in the URL already
    identifies which company you're asking about.
    """
    categories = posting.get("categories") or {}
    created_ms = posting.get("createdAt")
    created = (
        datetime.fromtimestamp(created_ms / 1000, tz=UTC).isoformat()
        if created_ms is not None
        else None
    )
    return {
        "source": "lever",
        "id": posting.get("id"),
        "title": posting.get("text"),
        "company": company,
        "location": categories.get("location"),
        "description": _build_description(posting),
        "salary_min": None,  # inconsistent across postings, not handled yet
        "salary_max": None,
        "salary_is_predicted": None,
        "contract_type": categories.get("commitment"),
        "contract_time": None,
        "category": categories.get("department"),
        "created": created,
        "url": posting.get("hostedUrl"),
    }


def _fetch_postings(site_slug: str) -> list[dict]:
    """Fetch the raw postings list, trying the global host first and
    falling back to the EU host on a 404 - Lever's own docs confirm both
    hosts genuinely exist, unlike the EU-host guess that broke Greenhouse.
    Any connection-level failure (not just a bad status code) on one host
    still lets the other be tried, and a real failure on both surfaces
    clearly rather than crashing on an unhandled exception type."""
    last_error: Exception | None = None
    for base_url in (GLOBAL_BASE_URL, EU_BASE_URL):
        try:
            response = _session.get(f"{base_url}/{site_slug}", params={"mode": "json"})
        except requests.exceptions.RequestException as e:
            last_error = e
            continue
        if response.status_code != 404:
            response.raise_for_status()
            return response.json()
        last_error = requests.exceptions.HTTPError(f"404 from {base_url}")
    if last_error is not None:
        raise last_error
    return []


def fetch_jobs(
    site_slug: str,
    company: str | None = None,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
    include_words: tuple[str, ...] = DEFAULT_INCLUDE_WORDS,
    false_positive_phrases: tuple[str, ...] = DEFAULT_FALSE_POSITIVE_PHRASES,
) -> list[dict]:
    """Fetch currently open, data/AI-relevant jobs for one company's Lever
    site. company defaults to a title-cased version of the slug if not
    given explicitly - imperfect for slugs like "gocardless", but callers
    can pass the real name when it matters."""
    display_company = company or site_slug.replace("-", " ").title()
    logger.info("Lever fetch: site_slug=%r", site_slug)
    postings = _fetch_postings(site_slug)

    total = len(postings)
    if include_words:
        postings = [
            p for p in postings if _title_relevant(p["text"], include_words, false_positive_phrases)
        ]
    if exclude_words:
        postings = [p for p in postings if not _title_excluded(p["text"], exclude_words)]
    jobs = [_normalize_job(p, display_company) for p in postings]
    logger.info("Lever site %r: %d total, %d after filtering", site_slug, total, len(jobs))
    return jobs


def fetch_batch(site_slugs: list[str]) -> list[dict]:
    """Fetch and aggregate jobs across many companies' Lever sites.

    Same RequestException-broad handling as Greenhouse's fetch_batch - one
    company's failure, of any kind, shouldn't take down the rest.
    """
    all_jobs = []
    for slug in site_slugs:
        try:
            jobs = fetch_jobs(slug)
        except requests.exceptions.RequestException as e:
            logger.warning("Lever site %r skipped (%s)", slug, type(e).__name__)
            continue
        all_jobs.extend(jobs)
    return all_jobs
