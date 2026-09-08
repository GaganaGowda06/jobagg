"""Reed job search client."""

import logging
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobagg.config import get_settings
from jobagg.filtering import DEFAULT_EXCLUDE_WORDS, _title_excluded

logger = logging.getLogger(__name__)

BASE_URL = "https://www.reed.co.uk/api/1.0/search"


def _parse_reed_date(date_str: str | None) -> str | None:
    """Reed sends dates as DD/MM/YYYY; convert to ISO format (YYYY-MM-DD)
    so dates are comparable across sources."""
    if not date_str:
        return None
    return datetime.strptime(date_str, "%d/%m/%Y").date().isoformat()


def _normalize_job(job: dict) -> dict:
    """Convert Reed's raw job dict into our common job shape."""
    company = job.get("employerName")
    job_id = job.get("jobId")
    return {
        "source": "reed",
        "id": str(job_id) if job_id is not None else None,
        "title": job.get("jobTitle"),
        "company": company.strip() if company else None,
        "location": job.get("locationName"),
        "description": job.get("jobDescription"),
        "salary_min": job.get("minimumSalary"),
        "salary_max": job.get("maximumSalary"),
        "salary_is_predicted": None,  # Reed doesn't provide this signal
        "contract_type": None,  # not returned by Reed's search endpoint
        "contract_time": None,
        "category": None,  # not returned by Reed's search endpoint
        "created": _parse_reed_date(job.get("date")),
        "url": job.get("jobUrl"),
    }


_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def search(
    keywords: str,
    location_name: str = "",
    results_to_take: int = 20,
    graduate: bool | None = None,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
) -> dict:
    settings = get_settings()
    params = {
        "keywords": keywords,
        "locationName": location_name,
        "resultsToTake": results_to_take,
    }
    if graduate is not None:
        params["graduate"] = "true" if graduate else "false"

    logger.info(
        "Reed search: keywords=%r location_name=%r results_to_take=%d graduate=%r",
        keywords,
        location_name,
        results_to_take,
        graduate,
    )

    response = _session.get(
        BASE_URL,
        params=params,
        auth=(settings.reed_api_key.get_secret_value(), ""),
    )
    response.raise_for_status()
    data = response.json()

    raw_count = len(data.get("results", []))
    if exclude_words:
        data["results"] = [
            job for job in data["results"] if not _title_excluded(job["jobTitle"], exclude_words)
        ]
    data["results"] = [_normalize_job(job) for job in data["results"]]
    logger.info(
        "Reed returned %d total matches, %d fetched, %d after title filter",
        data.get("totalResults", 0),
        raw_count,
        len(data["results"]),
    )

    return data
