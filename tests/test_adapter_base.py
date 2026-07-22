"""Tests for adapters/base.py helpers shared by every adapter.

`filter_by_since` previously lived under tests/test_adapters.py, which was deleted
with the FTE adapters. The helper itself survives — it is how an adapter implements
incremental sync — so its coverage moves here rather than disappearing.
"""
from __future__ import annotations

from datetime import date, datetime

from jobscout.adapters.base import filter_by_since
from jobscout.models import JobListing


def _make_listing(posted_date: datetime | None) -> JobListing:
    return JobListing(
        id="job-1",
        source="test",
        title="ML Engineer",
        company="Acme GmbH",
        description="Contract work.",
        location="Berlin, Germany",
        url="https://example.com/job/1",
        posted_date=posted_date,
        fetched_at=datetime(2026, 3, 21, 12, 0, 0),
        raw_data={},
    )


class TestFilterBySince:
    def test_job_posted_after_cutoff_is_kept(self):
        job = _make_listing(datetime(2026, 3, 20, 8, 0, 0))
        assert filter_by_since([job], date(2026, 3, 18)) == [job]

    def test_job_posted_before_cutoff_is_dropped(self):
        job = _make_listing(datetime(2026, 3, 15, 8, 0, 0))
        assert filter_by_since([job], date(2026, 3, 18)) == []

    def test_job_posted_on_cutoff_day_is_kept_regardless_of_time(self):
        """The cutoff is day-granular: a timestamp anywhere in that day qualifies.

        Without narrowing both sides, `datetime(2026, 3, 18, 0, 0) >= date(2026, 3, 18)`
        raises TypeError rather than comparing.
        """
        for hour in (0, 9, 23):
            job = _make_listing(datetime(2026, 3, 18, hour, 30, 0))
            assert filter_by_since([job], date(2026, 3, 18)) == [job], hour

    def test_job_with_no_posted_date_is_kept(self):
        job = _make_listing(None)
        assert filter_by_since([job], date(2026, 3, 18)) == [job]

    def test_datetime_cutoff_is_accepted(self):
        """Callers holding a last-run timestamp shouldn't have to narrow it first."""
        job = _make_listing(datetime(2026, 3, 20, 8, 0, 0))
        assert filter_by_since([job], datetime(2026, 3, 18, 6, 0, 0)) == [job]

    def test_empty_input_returns_empty(self):
        assert filter_by_since([], date(2026, 3, 18)) == []
