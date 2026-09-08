"""Fetch candidate job listings from Adzuna and Reed for hand-labeling.

Deliberately fetches WITHOUT the senior-title filter, so obviously-senior
jobs stay in as clear negative examples for the eval set.
"""

import json
from pathlib import Path

from jobagg.sources.adzuna import search as adzuna_search
from jobagg.sources.reed import search as reed_search

OUTPUT_PATH = Path("eval_set.json")

QUERIES = ["data scientist", "data analyst"]
LOCATIONS = ["", "london"]


def fetch_candidates() -> None:
    existing = []
    if OUTPUT_PATH.exists():
        existing = json.loads(OUTPUT_PATH.read_text())
    seen = {(job["source"], job["id"]) for job in existing}
    jobs = list(existing)

    for query in QUERIES:
        for location in LOCATIONS:
            adzuna_data = adzuna_search(
                query, where=location, results_per_page=20, exclude_words=()
            )
            reed_data = reed_search(
                query, location_name=location, results_to_take=20, exclude_words=()
            )
            for job in adzuna_data["results"] + reed_data["results"]:
                key = (job["source"], job["id"])
                if key not in seen:
                    seen.add(key)
                    job["label"] = None
                    jobs.append(job)

    OUTPUT_PATH.write_text(json.dumps(jobs, indent=2))
    new_count = len(jobs) - len(existing)
    print(f"Added {new_count} new candidates. Total pool: {len(jobs)} ({OUTPUT_PATH})")


if __name__ == "__main__":
    fetch_candidates()
