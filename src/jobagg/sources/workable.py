"""Workable job board client.

Same per-company full-board pattern as Greenhouse/Lever/Ashby, with one
structural difference: Workable's listing endpoint returns NO descriptions,
so each description needs a per-job details call. One company can list
100+ jobs, so titles are filtered FIRST and details are fetched only for
jobs that pass - anything else would waste a hundred requests per company.

Endpoint notes (probed live, Sep 2026):
- listing: /api/v1/widget/accounts/{slug} - includes the account display
  name, so the caller doesn't need to supply a company name.
- details: /api/v2/accounts/{slug}/jobs/{shortcode} (v1 works too; the
  /widget/ details path and v3 both 404).
- description is single-escaped HTML; requirements arrives as a separate
  HTML field and is concatenated in (the Lever lists lesson).
"""

import html
import logging
import re

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

LIST_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
DETAILS_URL = "https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"

_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _strip_html(text: str | None) -> str | None:
    """Strip tags, unescape entities, collapse whitespace."""
    if not text:
        return None
    no_tags = re.sub(r"<[^>]+>", " ", text)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip() or None


def _build_description(details: dict) -> str | None:
    """Description + requirements, both HTML-stripped. Workable keeps
    requirements in a separate field - dropping it would hide exactly the
    seniority signals the classifier needs."""
    parts = [_strip_html(details.get("description"))]
    requirements = _strip_html(details.get("requirements"))
    if requirements:
        parts.append(f"Requirements: {requirements}")
    combined = "\n\n".join(p for p in parts if p)
    return combined or None


def _build_location(listing_job: dict, details: dict) -> str | None:
    city = (listing_job.get("city") or "").strip()
    country = (listing_job.get("country") or "").strip()
    parts = [p for p in (city, country) if p]
    if parts:
        return ", ".join(parts)
    if details.get("remote"):
        return "Remote"
    return None


def _normalize_job(listing_job: dict, details: dict, company: str) -> dict:
    """Convert Workable's listing+details pair into our common job shape."""
    title = (listing_job.get("title") or "").strip() or None
    return {
        "source": "workable",
        "id": listing_job.get("shortcode"),
        "title": title,
        "company": company,
        "location": _build_location(listing_job, details),
        "description": _build_description(details),
        "salary_min": None,  # not exposed by the public widget endpoints
        "salary_max": None,
        "salary_is_predicted": None,
        "contract_type": None,
        "contract_time": listing_job.get("employment_type"),
        "category": listing_job.get("department"),
        "created": listing_job.get("published_on"),
        "url": listing_job.get("url"),
    }


def fetch_jobs(
    slug: str,
    company: str | None = None,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
    include_words: tuple[str, ...] = DEFAULT_INCLUDE_WORDS,
    false_positive_phrases: tuple[str, ...] = DEFAULT_FALSE_POSITIVE_PHRASES,
) -> list[dict]:
    """Fetch data/AI-relevant jobs for one company's Workable account.

    Titles are filtered before any details call; a details failure for one
    job skips that job only.
    """
    logger.info("Workable fetch: slug=%r", slug)
    response = _session.get(LIST_URL.format(slug=slug))
    response.raise_for_status()
    data = response.json()

    display_company = company or data.get("name") or slug.replace("-", " ").title()
    raw_jobs = data.get("jobs", [])
    total = len(raw_jobs)

    if include_words:
        raw_jobs = [
            j
            for j in raw_jobs
            if _title_relevant(j.get("title") or "", include_words, false_positive_phrases)
        ]
    if exclude_words:
        raw_jobs = [j for j in raw_jobs if not _title_excluded(j.get("title") or "", exclude_words)]

    jobs = []
    for listing_job in raw_jobs:
        shortcode = listing_job.get("shortcode")
        try:
            details_response = _session.get(DETAILS_URL.format(slug=slug, shortcode=shortcode))
            details_response.raise_for_status()
            details = details_response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Workable details for %r/%r skipped (%s)", slug, shortcode, type(e).__name__
            )
            continue
        jobs.append(_normalize_job(listing_job, details, display_company))

    logger.info("Workable account %r: %d total, %d after filtering", slug, total, len(jobs))
    return jobs


def fetch_batch(slugs: list[str]) -> list[dict]:
    """Fetch and aggregate jobs across many companies' Workable accounts.

    Same RequestException-broad handling as the other sources - one
    company's failure shouldn't take down the rest.
    """
    all_jobs = []
    for slug in slugs:
        try:
            jobs = fetch_jobs(slug)
        except requests.exceptions.RequestException as e:
            logger.warning("Workable account %r skipped (%s)", slug, type(e).__name__)
            continue
        all_jobs.extend(jobs)
    return all_jobs
