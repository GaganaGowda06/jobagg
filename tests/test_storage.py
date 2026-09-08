"""Tests for jobagg.storage."""

from jobagg.storage import count_jobs, init_db, save_jobs


def test_init_db_creates_table(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    assert count_jobs(db_path) == 0


def test_save_jobs_inserts_new_jobs(tmp_path):
    db_path = tmp_path / "test.db"
    job_a = {"source": "adzuna", "id": "1", "title": "Data Scientist"}
    job_b = {"source": "adzuna", "id": "2", "title": "Data Analyst"}

    new_count = save_jobs([job_a, job_b], db_path)

    assert new_count == 2
    assert count_jobs(db_path) == 2


def test_save_jobs_dedups_on_repeat(tmp_path):
    db_path = tmp_path / "test.db"
    job = {"source": "adzuna", "id": "1", "title": "Data Scientist"}

    save_jobs([job], db_path)
    new_count = save_jobs([job], db_path)

    assert new_count == 0
    assert count_jobs(db_path) == 1


def test_save_jobs_partial_dedup(tmp_path):
    db_path = tmp_path / "test.db"
    job_a = {"source": "adzuna", "id": "1", "title": "Data Scientist"}
    job_b = {"source": "reed", "id": "1", "title": "ML Engineer"}

    save_jobs([job_a], db_path)
    new_count = save_jobs([job_a, job_b], db_path)

    assert new_count == 1
    assert count_jobs(db_path) == 2


def test_same_id_different_source_not_treated_as_duplicate(tmp_path):
    db_path = tmp_path / "test.db"
    job_a = {"source": "adzuna", "id": "1", "title": "Data Scientist"}
    job_b = {"source": "reed", "id": "1", "title": "Completely different job"}

    n1 = save_jobs([job_a], db_path)
    n2 = save_jobs([job_b], db_path)

    assert n1 == 1
    assert n2 == 1
    assert count_jobs(db_path) == 2


def test_duplicate_within_single_call_counted_once(tmp_path):
    db_path = tmp_path / "test.db"
    job = {"source": "adzuna", "id": "1", "title": "Data Scientist"}

    new_count = save_jobs([job, job], db_path)

    assert new_count == 1
    assert count_jobs(db_path) == 1


def test_count_jobs_on_empty_db(tmp_path):
    db_path = tmp_path / "test.db"
    assert count_jobs(db_path) == 0


def test_save_jobs_handles_missing_optional_fields(tmp_path):
    db_path = tmp_path / "test.db"
    minimal_job = {"source": "adzuna", "id": "1"}

    new_count = save_jobs([minimal_job], db_path)

    assert new_count == 1
    assert count_jobs(db_path) == 1
