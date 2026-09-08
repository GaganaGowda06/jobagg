"""One-time migration: load the three *_classified.json files into jobagg.db.

Preserves every verdict already paid for in API quota. Job rows are created
with the fields the JSON files carry (title, company, url) - descriptions
and the rest backfill automatically on the next fetch, because upsert_jobs
refreshes all fields. The JSON files are left untouched as a backup.

Idempotent: re-running changes nothing (upsert + success-beats-error
semantics). Not part of the pytest suite.
"""

import json
from pathlib import Path

from jobagg.db import classified_keys, connect, qualifying_jobs, save_classification, upsert_jobs

JSON_FILES = [
    Path("greenhouse_classified.json"),
    Path("lever_classified.json"),
    Path("ashby_classified.json"),
]


def main() -> None:
    conn = connect()
    total_entries = 0
    for path in JSON_FILES:
        if not path.exists():
            print(f"{path}: not found, skipping")
            continue
        entries = json.loads(path.read_text())
        jobs = [
            {
                "source": e["source"],
                "id": e["id"],
                "title": e.get("title"),
                "company": e.get("company"),
                "url": e.get("url"),
            }
            for e in entries
        ]
        new = upsert_jobs(conn, jobs)
        for e in entries:
            save_classification(conn, e["source"], e["id"], e.get("predicted"), e.get("reason", ""))
        total_entries += len(entries)
        print(f"{path}: {len(entries)} entries migrated ({new} new job rows)")

    classified = len(classified_keys(conn))
    qualifies = len(qualifying_jobs(conn))
    print(f"\nDatabase now holds {classified} classified jobs, {qualifies} qualifying.")
    print(f"Migrated {total_entries} total entries. JSON files left untouched.")


if __name__ == "__main__":
    main()
