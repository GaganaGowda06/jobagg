"""One-off integration check: verifies Adzuna + Reed + storage dedup actually
works end-to-end against real, live API data - not just the hand-crafted
dicts in test_storage.py's unit tests.

Fetches the same query from both sources twice, saving into a throwaway DB
(not jobagg.db) each time. The real check is the second run: if dedup works,
it should insert 0 new rows and leave the total count unchanged, even though
it's the exact same live search results running through save_jobs() again.

Not part of the pytest suite - real network calls.
"""

from pathlib import Path

from jobagg.sources.adzuna import search as adzuna_search
from jobagg.sources.reed import search as reed_search
from jobagg.storage import count_jobs, save_jobs

DB_PATH = Path("dedup_check.db")
QUERY = "data scientist"


def _fetch_combined() -> list[dict]:
    adzuna_data = adzuna_search(QUERY, results_per_page=10)
    reed_data = reed_search(QUERY, results_to_take=10)
    return adzuna_data["results"] + reed_data["results"]


def main() -> None:
    DB_PATH.unlink(missing_ok=True)  # start clean each time this script runs

    jobs = _fetch_combined()
    adzuna_count = sum(1 for j in jobs if j["source"] == "adzuna")
    reed_count = sum(1 for j in jobs if j["source"] == "reed")
    print(f"Fetched {len(jobs)} jobs ({adzuna_count} adzuna, {reed_count} reed)")

    new_first = save_jobs(jobs, db_path=DB_PATH)
    total_first = count_jobs(db_path=DB_PATH)
    print(f"Run 1: {new_first} new, {total_first} total in storage")

    # Same query again - same live results, modulo any listing that genuinely
    # changed or expired between the two calls - saved into the same DB.
    jobs_again = _fetch_combined()
    new_second = save_jobs(jobs_again, db_path=DB_PATH)
    total_second = count_jobs(db_path=DB_PATH)
    print(f"Run 2: {new_second} new, {total_second} total in storage")

    if new_second == 0 and total_second == total_first:
        print("\nDedup confirmed: identical second fetch inserted nothing new.")
    else:
        print(
            f"\nUnexpected: run 2 added {new_second} new job(s) "
            f"(total {total_first} -> {total_second}). Could be a genuinely new "
            "listing that appeared between the two calls, or a real dedup "
            "problem - worth checking which before assuming either."
        )


if __name__ == "__main__":
    main()
