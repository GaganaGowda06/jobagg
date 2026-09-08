"""Greenhouse job board client.

Unlike Adzuna/Reed, Greenhouse has no keyword search - each company's board
is fetched in full via its own board token, one company at a time.
"""

import logging
import re
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

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _clean_html(raw: str | None) -> str | None:
    """Greenhouse returns job descriptions as HTML, escaped as JSON string
    content (e.g. "&lt;p&gt;" for a literal "<p>" tag). Unescape to get real
    HTML, then strip tags to get plain text for the classifier."""
    if not raw:
        return None
    unescaped = unescape(raw)
    text = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_job(job: dict) -> dict:
    """Convert Greenhouse's raw job dict into our common job shape."""
    job_id = job.get("id")
    company = job.get("company_name")
    departments = job.get("departments") or []
    category = departments[0].get("name") if departments else None
    return {
        "source": "greenhouse",
        "id": str(job_id) if job_id is not None else None,
        "title": job.get("title"),
        "company": company.strip() if company else None,
        "location": (job.get("location") or {}).get("name"),
        "description": _clean_html(job.get("content")),
        "salary_min": None,  # not exposed by this endpoint
        "salary_max": None,
        "salary_is_predicted": None,
        "contract_type": None,  # not exposed by this endpoint
        "contract_time": None,
        "category": category,
        "created": job.get("first_published"),
        "url": job.get("absolute_url"),
    }


def fetch_jobs(
    board_token: str,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
    include_words: tuple[str, ...] = DEFAULT_INCLUDE_WORDS,
    false_positive_phrases: tuple[str, ...] = DEFAULT_FALSE_POSITIVE_PHRASES,
) -> list[dict]:
    """Fetch currently open, data/AI-relevant jobs for one company's board.

    No keyword search at this level, so client-side filtering does the work
    the search API would normally do: include_words keeps only titles that
    look data/AI-relevant, false_positive_phrases then drops titles that
    matched an include word for the wrong reason (e.g. "Data Center
    Technician" matching "data"), and exclude_words drops the senior ones
    from what's left - same exclude-words logic already used for Adzuna/Reed.
    """
    logger.info("Greenhouse fetch: board_token=%r", board_token)
    response = _session.get(
        f"{BASE_URL}/{board_token}/jobs",
        params={"content": "true"},
    )
    response.raise_for_status()
    data = response.json()

    raw_jobs = data.get("jobs", [])
    total = len(raw_jobs)
    if include_words:
        raw_jobs = [
            job
            for job in raw_jobs
            if _title_relevant(job["title"], include_words, false_positive_phrases)
        ]
    if exclude_words:
        raw_jobs = [job for job in raw_jobs if not _title_excluded(job["title"], exclude_words)]
    jobs = [_normalize_job(job) for job in raw_jobs]
    logger.info(
        "Greenhouse board %r: %d total, %d after filtering",
        board_token,
        total,
        len(jobs),
    )
    return jobs


def fetch_batch(board_tokens: list[str]) -> list[dict]:
    """Fetch and aggregate jobs across many companies' Greenhouse boards.

    Catches RequestException broadly (bad status codes, DNS failures,
    timeouts, connection errors) rather than just HTTPError - one company's
    network problem, of any kind, shouldn't take down the rest of a
    100+ company batch. A real bug in this code (e.g. a KeyError from an
    unexpected response shape) is deliberately NOT caught here and will
    still surface loudly - only request-level failures are swallowed.
    """
    all_jobs = []
    for token in board_tokens:
        try:
            jobs = fetch_jobs(token)
        except requests.exceptions.RequestException as e:
            logger.warning("Greenhouse board %r skipped (%s)", token, type(e).__name__)
            continue
        all_jobs.extend(jobs)
    return all_jobs
