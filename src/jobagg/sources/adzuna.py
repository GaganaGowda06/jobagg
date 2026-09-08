"""Adzuna job search client."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobagg.config import get_settings
from jobagg.filtering import DEFAULT_EXCLUDE_WORDS, _title_excluded

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"


def _normalize_job(job: dict) -> dict:
    """Convert Adzuna's raw job dict into our common job shape."""
    predicted_raw = job.get("salary_is_predicted")
    return {
        "source": "adzuna",
        "id": job.get("id"),
        "title": job.get("title"),
        "company": (job.get("company") or {}).get("display_name"),
        "location": (job.get("location") or {}).get("display_name"),
        "description": job.get("description"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_is_predicted": str(predicted_raw) == "1" if predicted_raw is not None else None,
        "contract_type": job.get("contract_type"),
        "contract_time": job.get("contract_time"),
        "category": (job.get("category") or {}).get("label"),
        "created": job.get("created"),
        "url": job.get("redirect_url"),
    }


_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def search(
    what: str,
    where: str = "",
    results_per_page: int = 20,
    exclude_words: tuple[str, ...] = DEFAULT_EXCLUDE_WORDS,
) -> dict:
    settings = get_settings()
    params = {
        "app_id": settings.adzuna_app_id.get_secret_value(),
        "app_key": settings.adzuna_app_key.get_secret_value(),
        "what": what,
        "where": where,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    logger.info(
        "Adzuna search: what=%r where=%r results_per_page=%d", what, where, results_per_page
    )

    response = _session.get(BASE_URL, params=params)
    response.raise_for_status()
    data = response.json()

    raw_count = len(data.get("results", []))
    if exclude_words:
        data["results"] = [
            job for job in data["results"] if not _title_excluded(job["title"], exclude_words)
        ]
    data["results"] = [_normalize_job(job) for job in data["results"]]
    logger.info(
        "Adzuna returned %d total matches, %d fetched, %d after title filter",
        data.get("count", 0),
        raw_count,
        len(data["results"]),
    )

    return data
