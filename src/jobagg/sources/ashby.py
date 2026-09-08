"""Ashby job board client.

Like Greenhouse and Lever, Ashby has no keyword search - each company's
board is fetched in full via its own board name, one company at a time.
Unlike either of those, Ashby gives clean plain-text descriptions natively
(no HTML unescaping or lists-concatenation needed), but doesn't include the
company name in each posting - same as Lever, the caller supplies it.
"""

import logging

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

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _normalize_job(job: dict, company: str) -> dict:
    """Convert Ashby's raw job dict into our common job shape."""
    title = (job.get("title") or "").strip() or None
    return {
        "source": "ashby",
        "id": job.get("id"),
        "title": title,
        "company": company,
        "location": job.get("location"),
        "description": job.get("descriptionPlain"),
        "salary_min": None,  # compensation shape not yet confirmed against a populated example
        "salary_max": None,
        "salary_is_predicted": None,
        "contract_type": None,  # Ashby doesn't separate permanent/contract from full/part time
        "contract_time": job.get("employmentType"),
        "category": job.get("department"),
        "created": job.get("publishedAt"),
        "url": job.get("jobUrl"),
    }


def fetch_jobs(
    board_name: str,
    company: str | None = None,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
    include_words: tuple[str, ...] = DEFAULT_INCLUDE_WORDS,
    false_positive_phrases: tuple[str, ...] = DEFAULT_FALSE_POSITIVE_PHRASES,
) -> list[dict]:
    """Fetch currently open, data/AI-relevant jobs for one company's Ashby
    board. company defaults to a title-cased version of board_name if not
    given explicitly, same fallback as Lever's fetch_jobs.
    """
    display_company = company or board_name.replace("-", " ").title()
    logger.info("Ashby fetch: board_name=%r", board_name)
    response = _session.get(
        f"{BASE_URL}/{board_name}",
        params={"includeCompensation": "true"},
    )
    response.raise_for_status()
    data = response.json()

    # isListed defensively checked even though the endpoint is documented as
    # "all currently published postings" - costs nothing if it's always true.
    raw_jobs = [j for j in data.get("jobs", []) if j.get("isListed", True)]
    total = len(raw_jobs)
    if include_words:
        raw_jobs = [
            j
            for j in raw_jobs
            if _title_relevant(j["title"], include_words, false_positive_phrases)
        ]
    if exclude_words:
        raw_jobs = [j for j in raw_jobs if not _title_excluded(j["title"], exclude_words)]
    jobs = [_normalize_job(j, display_company) for j in raw_jobs]
    logger.info(
        "Ashby board %r: %d total, %d after filtering",
        board_name,
        total,
        len(jobs),
    )
    return jobs


def fetch_batch(board_names: list[str]) -> list[dict]:
    """Fetch and aggregate jobs across many companies' Ashby boards.

    Same RequestException-broad handling as Greenhouse/Lever's fetch_batch -
    one company's failure, of any kind, shouldn't take down the rest.
    """
    all_jobs = []
    for name in board_names:
        try:
            jobs = fetch_jobs(name)
        except requests.exceptions.RequestException as e:
            logger.warning("Ashby board %r skipped (%s)", name, type(e).__name__)
            continue
        all_jobs.extend(jobs)
    return all_jobs
