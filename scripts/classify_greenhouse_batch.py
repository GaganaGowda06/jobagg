"""Fetch Greenhouse jobs, store them in jobagg.db, and classify the unclassified
ones through the cascade (local triage -> Gemini -> OpenRouter fallback).

Storage is the SQLite database (see jobagg.db module): jobs are upserted on
every run (refreshing last_seen and backfilling full fields), and verdicts
follow the success-beats-error semantics. Resume is automatic - anything
already successfully classified is skipped.

Not part of the pytest suite - real network calls, real API cost.
"""

import time

from jobagg.classifier import DailyQuotaExhaustedError, classify_job_cascade, get_gemini_client
from jobagg.db import classified_keys, connect, save_classification, upsert_jobs
from jobagg.dedup import content_key, group_by_key
from jobagg.sources.greenhouse import fetch_batch

BOARD_TOKENS = [
    "monzo",
    "gocardless",
    "truelayer",
    "tide",
    "capitalontap",
    "cleoai",
    "griffin",
    "modulrfinance",
    "mangopay",
    "blockchain",
    "fireblocks",
    "robinhood",
    "wayve",
    "isomorphiclabs",
    "graphcore",
    "polyai",
    "synthesia",
    "featurespace",
    "darktracelimited",
    "snyk",
    "scaleai",
    "lightningai",
    "togetherai",
    "thinkingmachines",
    "gleanwork",
    "xai",
    "waymo",
    "datadog",
    "roku",
    "nexxen",
    "indexexchange",
    "tripadvisor",
    "wpp",
    "dunnhumby",
    "shifttechnology",
    "schonfeld",
    "wheely",
    "shift4",
    "nmi",
    "lhvuk",
    "moniepoint",
    "policyexpert",
]
RATE_LIMIT_DELAY = 4.5


def main() -> None:
    conn = connect()
    print(f"Fetching from {len(BOARD_TOKENS)} companies...")
    jobs = fetch_batch(BOARD_TOKENS)
    new = upsert_jobs(conn, jobs)
    print(f"{len(jobs)} jobs fetched ({new} new).\n")

    done = classified_keys(conn)
    remaining = [j for j in jobs if (j["source"], j["id"]) not in done]

    if not remaining:
        print("All fetched jobs already classified.")
        return

    print(f"{len(jobs) - len(remaining)} already classified, {len(remaining)} to go.\n")

    # Dedup: identical content (company+title+description) gets classified
    # once; the verdict is copied to every other posting in the group.
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
