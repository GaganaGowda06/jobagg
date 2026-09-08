"""SQLite storage for jobs and their classifications.

Replaces the per-source *_classified.json files with one queryable database.
Two tables:

- jobs: one row per (source, id) posting ever seen. first_seen is set once;
  last_seen updates on every fetch, so vanished postings are detectable
  (last_seen stops advancing) without ever deleting history.
- classifications: one row per (source, id) verdict. Same overwrite
  semantics the JSON files had: a successful verdict always beats an error,
  an error never overwrites a success.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path("jobagg.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    description TEXT,
    url TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_is_predicted TEXT,
    contract_type TEXT,
    contract_time TEXT,
    category TEXT,
    created TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (source, id)
);

CREATE TABLE IF NOT EXISTS classifications (
    source TEXT NOT NULL,
    id TEXT NOT NULL,
    predicted TEXT,
    reason TEXT,
    classified_at TEXT NOT NULL,
    PRIMARY KEY (source, id),
    FOREIGN KEY (source, id) REFERENCES jobs (source, id)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def upsert_jobs(conn: sqlite3.Connection, jobs: list[dict]) -> int:
    """Insert new jobs / refresh existing ones. Returns how many were new.

    first_seen is preserved on conflict; everything else (including
    last_seen) refreshes to the current fetch, so job edits are captured.
    """
    now = _now()
    new_count = 0
    for job in jobs:
        cursor = conn.execute(
            """
            INSERT INTO jobs (source, id, title, company, location, description,
                              url, salary_min, salary_max, salary_is_predicted,
                              contract_type, contract_time, category, created,
                              first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                description = excluded.description,
                url = excluded.url,
                salary_min = excluded.salary_min,
                salary_max = excluded.salary_max,
                salary_is_predicted = excluded.salary_is_predicted,
                contract_type = excluded.contract_type,
                contract_time = excluded.contract_time,
                category = excluded.category,
                created = excluded.created,
                last_seen = excluded.last_seen
            """,
            (
                job["source"],
                job["id"],
                job.get("title"),
                job.get("company"),
                job.get("location"),
                job.get("description"),
                job.get("url"),
                job.get("salary_min"),
                job.get("salary_max"),
                str(job.get("salary_is_predicted"))
                if job.get("salary_is_predicted") is not None
                else None,
                job.get("contract_type"),
                job.get("contract_time"),
                job.get("category"),
                job.get("created"),
                now,
                now,
            ),
        )
        # lastrowid changes only on a genuine INSERT; detect via changes+select
        if cursor.rowcount and _was_inserted(conn, job["source"], job["id"], now):
            new_count += 1
    conn.commit()
    return new_count


def _was_inserted(conn: sqlite3.Connection, source: str, job_id: str, now: str) -> bool:
    row = conn.execute(
        "SELECT first_seen FROM jobs WHERE source = ? AND id = ?", (source, job_id)
    ).fetchone()
    return row is not None and row["first_seen"] == now


def save_classification(
    conn: sqlite3.Connection, source: str, job_id: str, predicted: str | None, reason: str
) -> None:
    """Save a verdict. A success always overwrites; an error only fills a gap
    or overwrites another error - never a success. Matches the JSON-era
    semantics exactly."""
    conn.execute(
        """
        INSERT INTO classifications (source, id, predicted, reason, classified_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (source, id) DO UPDATE SET
            predicted = excluded.predicted,
            reason = excluded.reason,
            classified_at = excluded.classified_at
        WHERE excluded.predicted IS NOT NULL
              OR classifications.predicted IS NULL
        """,
        (source, job_id, predicted, reason, _now()),
    )
    conn.commit()


def classified_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """(source, id) pairs that already have a SUCCESSFUL verdict."""
    rows = conn.execute(
        "SELECT source, id FROM classifications WHERE predicted IS NOT NULL"
    ).fetchall()
    return {(r["source"], r["id"]) for r in rows}


def qualifying_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All jobs currently classified as qualifies, newest first."""
    return conn.execute(
        """
        SELECT j.*, c.reason, c.classified_at
        FROM jobs j
        JOIN classifications c ON c.source = j.source AND c.id = j.id
        WHERE c.predicted = 'qualifies'
        ORDER BY c.classified_at DESC
        """
    ).fetchall()
