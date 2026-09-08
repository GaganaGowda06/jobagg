"""Interactive labeling tool for the eval set.

Saves after every single label, so you can stop anytime (x) and resume
later without losing progress.
"""

import json
from pathlib import Path

DATASET_PATH = Path("eval_set.json")

LABELS = {
    "q": "qualifies",
    "d": "doesnt_qualify",
    "u": "uncertain",
}


def label_jobs() -> None:
    jobs = json.loads(DATASET_PATH.read_text())
    unlabeled = [job for job in jobs if job["label"] is None]

    if not unlabeled:
        print("All jobs already labeled.")
        return

    print(f"{len(unlabeled)} jobs to label.")
    print("q = qualifies, d = doesn't qualify, u = uncertain, s = skip, x = stop\n")

    for i, job in enumerate(unlabeled, 1):
        print(f"--- {i}/{len(unlabeled)} ---")
        print(f"[{job['source']}] {job['title']} @ {job.get('company')}")
        print((job.get("description") or "")[:500])
        print()

        while True:
            choice = input("Label (q/d/u/s/x): ").strip().lower()
            if choice == "x":
                DATASET_PATH.write_text(json.dumps(jobs, indent=2))
                print("Stopped. Progress saved.")
                return
            if choice == "s":
                break
            if choice in LABELS:
                job["label"] = LABELS[choice]
                DATASET_PATH.write_text(json.dumps(jobs, indent=2))
                break
            print("Invalid input, try q/d/u/s/x")
        print()

    print("All jobs labeled.")


if __name__ == "__main__":
    label_jobs()
