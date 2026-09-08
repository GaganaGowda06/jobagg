"""Unit tests for jobagg.db - uses a temp-file database per test."""

from jobagg.db import (
    classified_keys,
    connect,
    qualifying_jobs,
    save_classification,
    upsert_jobs,
)


def _conn(tmp_path):
    return connect(tmp_path / "test.db")


def _job(source="ashby", job_id="1", **kw):
    return {"source": source, "id": job_id, "title": "Data Analyst", "company": "X", **kw}


class TestConnect:
    def test_creates_schema_idempotently(self, tmp_path):
        conn = _conn(tmp_path)
        conn.close()
        conn = _conn(tmp_path)  # second connect must not fail
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"jobs", "classifications"} <= tables


class TestUpsertJobs:
    def test_new_jobs_counted(self, tmp_path):
        conn = _conn(tmp_path)
        assert upsert_jobs(conn, [_job(job_id="1"), _job(job_id="2")]) == 2

    def test_refetch_is_not_new(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        assert upsert_jobs(conn, [_job()]) == 0

    def test_first_seen_preserved_last_seen_updated(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        first = conn.execute("SELECT first_seen, last_seen FROM jobs").fetchone()
        conn.execute("UPDATE jobs SET first_seen = 'ANCIENT', last_seen = 'ANCIENT'")
        conn.commit()
        upsert_jobs(conn, [_job(title="Renamed Role")])
        row = conn.execute("SELECT first_seen, last_seen, title FROM jobs").fetchone()
        assert row["first_seen"] == "ANCIENT"
        assert row["last_seen"] != "ANCIENT"
        assert row["title"] == "Renamed Role"
        assert first is not None

    def test_same_id_different_source_are_distinct(self, tmp_path):
        conn = _conn(tmp_path)
        assert upsert_jobs(conn, [_job(source="ashby"), _job(source="lever")]) == 2


class TestSaveClassification:
    def test_success_saved(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        save_classification(conn, "ashby", "1", "qualifies", "grad role")
        assert classified_keys(conn) == {("ashby", "1")}

    def test_error_not_treated_as_classified(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        save_classification(conn, "ashby", "1", None, "ERROR: quota")
        assert classified_keys(conn) == set()

    def test_success_overwrites_error(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        save_classification(conn, "ashby", "1", None, "ERROR: quota")
        save_classification(conn, "ashby", "1", "qualifies", "retry worked")
        row = conn.execute("SELECT predicted, reason FROM classifications").fetchone()
        assert row["predicted"] == "qualifies"

    def test_error_never_overwrites_success(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job()])
        save_classification(conn, "ashby", "1", "qualifies", "good")
        save_classification(conn, "ashby", "1", None, "ERROR: later failure")
        row = conn.execute("SELECT predicted, reason FROM classifications").fetchone()
        assert row["predicted"] == "qualifies"
        assert row["reason"] == "good"


class TestQualifyingJobs:
    def test_returns_only_qualifies_with_job_fields(self, tmp_path):
        conn = _conn(tmp_path)
        upsert_jobs(conn, [_job(job_id="1"), _job(job_id="2"), _job(job_id="3")])
        save_classification(conn, "ashby", "1", "qualifies", "yes")
        save_classification(conn, "ashby", "2", "doesnt_qualify", "no")
        save_classification(conn, "ashby", "3", None, "ERROR")
        rows = qualifying_jobs(conn)
        assert len(rows) == 1
        assert rows[0]["id"] == "1"
        assert rows[0]["title"] == "Data Analyst"
        assert rows[0]["reason"] == "yes"
