"""Search Reed for junior data/ML/AI roles, enrich each NEW job with its
FULL description, store in jobagg.db, and classify through the cascade.

Reed's search endpoint truncates descriptions at ~450 characters - the
measured cause of reed being the weakest source in every eval slice. Each
new job gets one extra details call for the full text (~3000+ chars)
BEFORE dedup and classification; already-classified jobs are never
re-fetched. A failed details call falls back to the truncated text.

Not part of the pytest suite - real network calls, real API cost.
"""

import time

from jobagg.classifier import DailyQuotaExhaustedError, classify_job_cascade, get_gemini_client
from jobagg.db import classified_keys, connect, save_classification, upsert_jobs
from jobagg.dedup import content_key, group_by_key
from jobagg.sources.reed import fetch_full_description, search

QUERIES = [
    "graduate data scientist",
    "junior data scientist",
    "graduate data analyst",
    "junior data analyst",
    "graduate data engineer",
    "machine learning graduate",
]
RESULTS_PER_QUERY = 50
RATE_LIMIT_DELAY = 4.5


def main() -> None:
    conn = connect()
    jobs, seen = [], set()
    for query in QUERIES:
        data = search(query, results_to_take=RESULTS_PER_QUERY)
        for job in data["results"]:
            key = (job["source"], job["id"])
            if key not in seen:
                seen.add(key)
                jobs.append(job)
    print(f"{len(jobs)} jobs fetched across {len(QUERIES)} queries.")

    done = classified_keys(conn)
    remaining = [j for j in jobs if (j["source"], j["id"]) not in done]

    # Full-description enrichment: one details call per NEW job only.
    enriched = 0
    for job in remaining:
        full = fetch_full_description(job["id"])
        if full and len(full) > len(job.get("description") or ""):
            job["description"] = full
            enriched += 1
    print(f"{enriched} of {len(remaining)} new job(s) enriched with full descriptions.")

    new = upsert_jobs(conn, jobs)
    print(f"({new} new job rows.)\n")

    if not remaining:
        print("All fetched jobs already classified.")
        return

    print(f"{len(jobs) - len(remaining)} already classified, {len(remaining)} to go.\n")

    groups = list(group_by_key(remaining, content_key).values())
    dupes = len(remaining) - len(groups)
    if dupes:
        print(
            f"{dupes} duplicate posting(s) share content with another - "
            f"{len(groups)} classifications needed instead of {len(remaining)}.\n"
        )

    client = get_gemini_client()
    for i, group in enumerate(groups, 1):
        rep = group[0]
        try:
            result = classify_job_cascade(rep, client)
            predicted, reason = result.classification, result.reason
        except DailyQuotaExhaustedError:
            print(
                f"\nDaily Gemini quota exhausted after {i - 1} of {len(groups)} - "
                "stopping cleanly. Progress is saved; rerun this script after the "
                "quota resets (~08:00 Dublin) to finish the rest."
            )
            break
        except Exception as e:
            predicted, reason = None, f"ERROR: {type(e).__name__}: {e}"

        save_classification(conn, rep["source"], rep["id"], predicted, reason)
        print(f"[{i}/{len(groups)}] {predicted or 'ERROR':15} [{rep['company']}] {rep['title']}")
        if predicted is not None:
            for copy in group[1:]:
                save_classification(
                    conn, copy["source"], copy["id"], predicted, f"[dedup-copy] {reason}"
                )
                print(f"        = duplicate: [{copy['company']}] {copy['title']}")

        if i < len(groups):
            time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. {len(classified_keys(conn))} classified jobs in the database.")


if __name__ == "__main__":
    main()
