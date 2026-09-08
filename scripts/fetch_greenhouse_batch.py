"""Run the classifier over jobs fetched from the Greenhouse batch and save
results. Same save-as-you-go, resume-on-rerun pattern as run_eval.py - a
job is only "done" once it has a successful (non-error) result, and a retry
overwrites its old entry instead of appending a duplicate.

Not part of the pytest suite - real network calls (Greenhouse + Gemini),
real API cost.
"""

import json
import time
from pathlib import Path

from jobagg.classifier import DailyQuotaExhaustedError, classify_job, get_gemini_client
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
RESULTS_PATH = Path("greenhouse_classified.json")
RATE_LIMIT_DELAY = 4.5


def _load_results() -> dict[tuple[str, str], dict]:
    """Load existing results keyed by (source, id), collapsing any
    duplicates left over from before this used the overwrite pattern - a
    successful entry always wins over an error for the same job."""
    if not RESULTS_PATH.exists():
        return {}
    results_by_key: dict[tuple[str, str], dict] = {}
    for r in json.loads(RESULTS_PATH.read_text()):
        key = (r["source"], r["id"])
        existing = results_by_key.get(key)
        if existing is None or (existing["predicted"] is None and r["predicted"] is not None):
            results_by_key[key] = r
    return results_by_key


def main() -> None:
    print(f"Fetching from {len(BOARD_TOKENS)} companies...")
    jobs = fetch_batch(BOARD_TOKENS)
    print(f"{len(jobs)} jobs fetched.\n")

    results_by_key = _load_results()
    succeeded = {k for k, r in results_by_key.items() if r["predicted"] is not None}
    remaining = [j for j in jobs if (j["source"], j["id"]) not in succeeded]

    if not remaining:
        print("All fetched jobs already classified.")
        return

    print(f"{len(jobs) - len(remaining)} already classified, {len(remaining)} to go.\n")

    client = get_gemini_client()
    for i, job in enumerate(remaining, 1):
        key = (job["source"], job["id"])
        try:
            result = classify_job(job, client)
            predicted, reason = result.classification, result.reason
        except DailyQuotaExhaustedError:
            print(
                f"\nDaily Gemini quota exhausted after {i - 1} of {len(remaining)} - "
                "stopping cleanly. Progress is saved; rerun this script after the "
                "quota resets (~08:00 Dublin) to finish the rest."
            )
            break
        except Exception as e:
            predicted, reason = None, f"ERROR: {type(e).__name__}: {e}"

        results_by_key[key] = {
            "source": job["source"],
            "id": job["id"],
            "company": job["company"],
            "title": job["title"],
            "url": job.get("url"),
            "predicted": predicted,
            "reason": reason,
        }
        RESULTS_PATH.write_text(json.dumps(list(results_by_key.values()), indent=2))
        print(f"[{i}/{len(remaining)}] {predicted or 'ERROR':15} [{job['company']}] {job['title']}")

        if i < len(remaining):
            time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. {len(results_by_key)} total results in {RESULTS_PATH}.")


if __name__ == "__main__":
    main()
