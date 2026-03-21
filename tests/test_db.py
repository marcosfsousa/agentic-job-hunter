"""Tests for storage/db.py.

All tests use SQLite :memory: — no files created or cleaned up.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from jobscout.models import FeedbackEntry, JobListing
from jobscout.storage.db import JobDatabase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db() -> JobDatabase:
    return JobDatabase(Path(":memory:"))


def _make_job(id: str = "job-1", source: str = "adzuna_de", **overrides) -> JobListing:
    defaults = dict(
        id=id,
        source=source,
        title="ML Engineer",
        company="Acme GmbH",
        description="Machine learning role.",
        location="Berlin, Germany",
        remote_policy="hybrid",
        salary_min=55_000.0,
        salary_max=75_000.0,
        seniority="mid",
        url="https://example.com/job/1",
        posted_date=date(2026, 3, 18),
        fetched_at=datetime(2026, 3, 18, 12, 0, 0),
        raw_data={},
    )
    defaults.update(overrides)
    return JobListing(**defaults)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_opens_and_closes_cleanly(self, db):
        with db as d:
            assert d._conn is not None
        assert db._conn is None

    def test_requires_context_manager(self, db):
        with pytest.raises(RuntimeError, match="context manager"):
            db.filter_unseen([_make_job()])

    def test_creates_table_on_open(self, db):
        with db as d:
            rows = d._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_jobs'"
            ).fetchall()
            assert len(rows) == 1

    def test_idempotent_table_creation(self, db):
        with db:
            pass
        with db as d:
            rows = d._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_jobs'"
            ).fetchall()
            assert len(rows) == 1


# ---------------------------------------------------------------------------
# filter_unseen
# ---------------------------------------------------------------------------

class TestFilterUnseen:
    def test_empty_input_returns_empty(self, db):
        with db as d:
            assert d.filter_unseen([]) == []

    def test_all_unseen_on_empty_db(self, db):
        jobs = [_make_job(id=str(i)) for i in range(3)]
        with db as d:
            result = d.filter_unseen(jobs)
        assert result == jobs

    def test_seen_job_is_filtered_out(self, db):
        job = _make_job(id="seen-1")
        with db as d:
            d.mark_seen_bulk([job])
            result = d.filter_unseen([job])
        assert result == []

    def test_only_unseen_jobs_returned(self, db):
        seen = _make_job(id="seen-1")
        unseen = _make_job(id="new-1")
        with db as d:
            d.mark_seen_bulk([seen])
            result = d.filter_unseen([seen, unseen])
        assert result == [unseen]

    def test_same_id_different_source_both_unseen(self, db):
        job_a = _make_job(id="job-1", source="adzuna_de")
        job_b = _make_job(id="job-1", source="jsearch")
        with db as d:
            d.mark_seen_bulk([job_a])
            result = d.filter_unseen([job_a, job_b])
        assert result == [job_b]

    def test_batch_query_with_many_jobs(self, db):
        jobs = [_make_job(id=str(i)) for i in range(50)]
        with db as d:
            d.mark_seen_bulk(jobs[:25])
            result = d.filter_unseen(jobs)
        assert len(result) == 25
        assert all(j.id in {str(i) for i in range(25, 50)} for j in result)


# ---------------------------------------------------------------------------
# mark_seen_bulk
# ---------------------------------------------------------------------------

class TestMarkSeenBulk:
    def test_empty_input_is_noop(self, db):
        with db as d:
            d.mark_seen_bulk([])  # should not raise

    def test_marks_jobs_as_seen(self, db):
        jobs = [_make_job(id=str(i)) for i in range(5)]
        with db as d:
            d.mark_seen_bulk(jobs)
            result = d.filter_unseen(jobs)
        assert result == []

    def test_idempotent_double_insert(self, db):
        job = _make_job()
        with db as d:
            d.mark_seen_bulk([job])
            d.mark_seen_bulk([job])  # should not raise
            rows = d._conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
        assert rows == 1

    def test_first_seen_timestamp_is_recorded(self, db):
        job = _make_job()
        with db as d:
            d.mark_seen_bulk([job])
            row = d._conn.execute("SELECT first_seen FROM seen_jobs").fetchone()
        assert row is not None
        assert row[0]  # non-empty ISO timestamp


# ---------------------------------------------------------------------------
# upsert_feedback
# ---------------------------------------------------------------------------

class TestUpsertFeedback:
    def _entry(self, id: str = "job-1", source: str = "adzuna_de", status: str = "applied") -> FeedbackEntry:
        return FeedbackEntry(id=id, source=source, status=status)

    def test_empty_input_is_noop(self, db):
        with db as d:
            d.upsert_feedback([])  # should not raise

    def test_inserts_entry(self, db):
        with db as d:
            d.upsert_feedback([self._entry()])
            row = d._conn.execute("SELECT id, source, status FROM feedback").fetchone()
        assert row == ("job-1", "adzuna_de", "applied")

    def test_updates_existing_status(self, db):
        with db as d:
            d.upsert_feedback([self._entry(status="interested")])
            d.upsert_feedback([self._entry(status="applied")])
            rows = d._conn.execute("SELECT status FROM feedback WHERE id='job-1'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "applied"

    def test_multiple_entries(self, db):
        entries = [self._entry(id=str(i), status="rejected") for i in range(5)]
        with db as d:
            d.upsert_feedback(entries)
            count = d._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        assert count == 5

    def test_creates_feedback_table_on_open(self, db):
        with db as d:
            rows = d._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'"
            ).fetchall()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# filter_feedback
# ---------------------------------------------------------------------------

class TestFilterFeedback:
    def test_empty_input_returns_empty(self, db):
        with db as d:
            assert d.filter_feedback([]) == []

    def test_no_feedback_returns_all(self, db):
        jobs = [_make_job(id=str(i)) for i in range(3)]
        with db as d:
            result = d.filter_feedback(jobs)
        assert result == jobs

    def test_applied_job_is_excluded(self, db):
        job = _make_job(id="job-1")
        with db as d:
            d.upsert_feedback([FeedbackEntry(id="job-1", source="adzuna_de", status="applied")])
            result = d.filter_feedback([job])
        assert result == []

    def test_rejected_job_is_excluded(self, db):
        job = _make_job(id="job-1")
        with db as d:
            d.upsert_feedback([FeedbackEntry(id="job-1", source="adzuna_de", status="rejected")])
            result = d.filter_feedback([job])
        assert result == []

    def test_interested_job_is_kept(self, db):
        job = _make_job(id="job-1")
        with db as d:
            d.upsert_feedback([FeedbackEntry(id="job-1", source="adzuna_de", status="interested")])
            result = d.filter_feedback([job])
        assert result == [job]

    def test_only_excluded_jobs_removed(self, db):
        applied = _make_job(id="job-1")
        kept = _make_job(id="job-2")
        with db as d:
            d.upsert_feedback([FeedbackEntry(id="job-1", source="adzuna_de", status="applied")])
            result = d.filter_feedback([applied, kept])
        assert result == [kept]

    def test_source_scoped_exclusion(self, db):
        # Same id, different source — only the matching source is excluded
        adzuna_job = _make_job(id="job-1", source="adzuna_de")
        jsearch_job = _make_job(id="job-1", source="jsearch")
        with db as d:
            d.upsert_feedback([FeedbackEntry(id="job-1", source="adzuna_de", status="applied")])
            result = d.filter_feedback([adzuna_job, jsearch_job])
        assert result == [jsearch_job]
