"""Interactive labeling of ATS jobs (full descriptions) to grow the eval set.

Samples unlabeled ATS jobs from jobagg.db and asks for a hand label for
each: q = qualifies, d = doesnt_qualify, u = uncertain, s = skip, x = stop.
The model's existing verdict is deliberately NOT shown - labels must be
independent human judgment, or the eval would grade the model against
itself.

Labels append to eval_set_ats.json (the original eval_set.json stays
untouched as the frozen truncated-source set). Progress saves after every
label - stop and resume any time.

Not part of the pytest suite - interactive.
"""

import json
import random
import textwrap
from pathlib import Path

from jobagg.db import connect

OUT_PATH = Path("eval_set_ats.json")
SAMPLE_SIZE = 84
SAMPLE_SEED = 7  # fixed so reruns resume the same sample
KEYS = {"q": "qualifies", "d": "doesnt_qualify", "u": "uncertain"}


def _sample_jobs(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT j.source, j.id, j.title, j.company, j.location, j.description
        FROM jobs j
        WHERE j.source IN ('greenhouse', 'lever', 'ashby')
              AND j.description IS NOT NULL
        ORDER BY j.source, j.id
        """
    ).fetchall()
    jobs = [dict(r) for r in rows]
    random.Random(SAMPLE_SEED).shuffle(jobs)
    return jobs[:SAMPLE_SIZE]


def main() -> None:
    conn = connect()
    labeled = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else []
    done_keys = {(e["source"], e["id"]) for e in labeled}
    sample = [j for j in _sample_jobs(conn) if (j["source"], j["id"]) not in done_keys]

    if not sample:
        print(f"All sampled jobs labeled. {len(labeled)} labels in {OUT_PATH}.")
        return

    print(f"{len(labeled)} labeled so far, {len(sample)} to go.")
    print("Keys: q = qualifies, d = doesnt_qualify, u = uncertain, s = skip, x = stop\n")

    for i, job in enumerate(sample, 1):
        print("=" * 78)
        print(f"[{i}/{len(sample)}] [{job['company']}] {job['title']}  ({job['source']})")
        print("-" * 78)
        desc = (job["description"] or "")[:3000]
        print(textwrap.fill(desc, width=78))
        print("-" * 78)

        while True:
            answer = input("label (q/d/u/s/x): ").strip().lower()
            if answer in ("q", "d", "u", "s", "x"):
                break
            print("  q, d, u, s, or x only")

        if answer == "x":
            print(f"\nStopped. {len(labeled)} labels in {OUT_PATH} - rerun to continue.")
            return
        if answer == "s":
            continue

        labeled.append(
            {
                "source": job["source"],
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job.get("location"),
                "description": job["description"],
                "label": KEYS[answer],
            }
        )
        OUT_PATH.write_text(json.dumps(labeled, indent=2))

    print(f"\nAll done. {len(labeled)} labels in {OUT_PATH}.")


if __name__ == "__main__":
    main()
