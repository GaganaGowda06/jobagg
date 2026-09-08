"""SQLite storage for deduplicated job listings."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("jobagg.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    description TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_is_predicted INTEGER,
    contract_type TEXT,
    contract_time TEXT,
    category TEXT,
    created TEXT,
    url TEXT,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (source, id)
);
"""


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create the jobs table if it doesn't already exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_jobs(jobs: list[dict], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert new jobs into storage.

    Returns how many were genuinely new. A job already in storage (matched
    by source + id) is silently skipped, not treated as an error — that's
    the dedup behavior this function exists for.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    new_count = 0
    now = datetime.now(UTC).isoformat()
    try:
        for job in jobs:
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        source, id, title, company, location, description,
                        salary_min, salary_max, salary_is_predicted,
                        contract_type, contract_time, category, created, url,
                        first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job["source"],
                        job["id"],
                        job.get("title"),
                        job.get("company"),
                        job.get("location"),
                        job.get("description"),
                        job.get("salary_min"),
                        job.get("salary_max"),
                        job.get("salary_is_predicted"),
                        job.get("contract_type"),
                        job.get("contract_time"),
                        job.get("category"),
                        job.get("created"),
                        job.get("url"),
                        now,
                    ),
                )
                new_count += 1
            except sqlite3.IntegrityError:
                continue  # already stored — this is expected dedup, not an error
        conn.commit()
    finally:
        conn.close()
    return new_count


def count_jobs(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Return the total number of jobs currently in storage."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        conn.close()
