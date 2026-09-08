"""Run classify_job over every labeled job in the eval set and save results.

Saves after every single job, same as label_eval_set.py - a 130-call run is
long enough (and costs enough) that a crash or a persistent API hiccup partway
through shouldn't mean starting over. Rerunning this script retries only jobs
that don't yet have a successful (non-error) result - an errored job is not
treated as done, so a rerun after a quota reset will actually retry it instead
of silently skipping it forever.

Paced at RATE_LIMIT_DELAY seconds between calls to stay under the free tier's
per-minute cap. That's separate from the per-day cap - pacing can't do
anything about RPD, only waiting for the daily reset can.

Not part of the pytest suite - real network calls, real API cost.
"""

import json
import sys
import time
from pathlib import Path

from jobagg.classifier import DailyQuotaExhaustedError, classify_job, get_gemini_client

# optional args: eval set path, results path - defaults preserve the
# original truncated-source eval exactly as before.
EVAL_SET_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval_set.json")
RESULTS_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("eval_results.json")
RATE_LIMIT_DELAY = 4.5


def run_eval() -> None:
    jobs = json.loads(EVAL_SET_PATH.read_text())
    labeled = [j for j in jobs if j.get("label")]

    existing = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else []
    results_by_key = {(r["source"], r["id"]): r for r in existing}

    succeeded = {k for k, r in results_by_key.items() if r["predicted"] is not None}
    remaining = [j for j in labeled if (j["source"], j["id"]) not in succeeded]

    if not remaining:
        print(f"All {len(labeled)} labeled jobs already have a successful result.")
        return

    print(f"{len(labeled) - len(remaining)} already succeeded, {len(remaining)} to go.\n")

    client = get_gemini_client()
    for i, job in enumerate(remaining, 1):
        key = (job["source"], job["id"])
        try:
            classification = classify_job(job, client)
            predicted = classification.classification
            reason = classification.reason
        except DailyQuotaExhaustedError:
            print(
                f"\nDaily Gemini quota exhausted after {i - 1} of {len(remaining)} - "
                "stopping cleanly. Progress is saved; rerun this script after the "
                "quota resets (~08:00 Dublin) to finish the rest."
            )
            break
        except Exception as e:
            predicted = None
            reason = f"ERROR: {type(e).__name__}: {e}"

        results_by_key[key] = {
            "source": job["source"],
            "id": job["id"],
            "title": job.get("title"),
            "true_label": job["label"],
            "predicted": predicted,
            "reason": reason,
        }
        RESULTS_PATH.write_text(json.dumps(list(results_by_key.values()), indent=2))

        status = "match" if predicted == job["label"] else "MISS"
        print(f"[{i}/{len(remaining)}] {status:5} {(job.get('title') or '')[:55]}")

        if i < len(remaining):
            time.sleep(RATE_LIMIT_DELAY)

    print(f"\nDone. {len(results_by_key)} total results in {RESULTS_PATH}.")


if __name__ == "__main__":
    run_eval()
