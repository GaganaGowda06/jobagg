"""One-off check: runs classify_job against a few real labeled jobs, spread
across all three labels, and compares the model's classification to your
hand-assigned label.

Not part of the pytest suite - real network calls, real API cost. Run once,
then delete it.
"""

import json
from pathlib import Path

from jobagg.classifier import classify_job, get_gemini_client

EVAL_SET_PATH = Path("eval_set.json")
PER_LABEL = 2


def _sample_jobs(jobs: list[dict]) -> list[dict]:
    """Take up to PER_LABEL jobs from each of the three labels, not just the
    first N in file order - the eval set isn't shuffled, so file order alone
    can hand back near-duplicate postings of the same role."""
    sample = []
    for label in ("qualifies", "doesnt_qualify", "uncertain"):
        matches = [j for j in jobs if j.get("label") == label]
        sample.extend(matches[:PER_LABEL])
    return sample


def main() -> None:
    jobs = json.loads(EVAL_SET_PATH.read_text())
    sample = _sample_jobs(jobs)

    client = get_gemini_client()
    for job in sample:
        result = classify_job(job, client)
        match = "MATCH" if result.classification == job["label"] else "MISMATCH"
        print(f"[{match}] {job['title'][:60]}")
        print(f"  true label: {job['label']}")
        print(f"  model said: {result.classification} - {result.reason}")
        print()


if __name__ == "__main__":
    main()
