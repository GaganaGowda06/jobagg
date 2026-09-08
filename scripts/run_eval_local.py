"""Run the LOCAL Ollama classifier over every labeled eval job and save
results to eval_results_local.json. Zero API quota, zero cost - this
measures the local model's standalone accuracy, which decides where a
cascade can trust it.

Same save-as-you-go resume pattern as run_eval.py; no rate-limit pacing
because everything runs on this machine. Requires `ollama serve` running
with the model pulled.

Not part of the pytest suite.
"""

import json
from pathlib import Path

from jobagg.classifier import classify_job_local

EVAL_SET_PATH = Path("eval_set.json")
RESULTS_PATH = Path("eval_results_local.json")


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

    for i, job in enumerate(remaining, 1):
        key = (job["source"], job["id"])
        try:
            classification = classify_job_local(job)
            predicted = classification.classification
            reason = classification.reason
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

    print(f"\nDone. {len(results_by_key)} total results in {RESULTS_PATH}.")


if __name__ == "__main__":
    run_eval()
