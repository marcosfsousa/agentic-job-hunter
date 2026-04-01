"""Tests for JobSpyAdapter normalization and helper logic.

All tests work without network access. Tests that require pandas/jobspy
are skipped automatically if the package is not installed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from jobscout.adapters.jobspy import (
    JobSpyAdapter,
    _is_german,
    _is_german_domain,
    _map_job_level,
    _sanitize_raw,
    _since_to_hours_old,
)

pd = pytest.importorskip("pandas", reason="python-jobspy (pandas) not installed")


# ---------------------------------------------------------------------------
# _safe
# ---------------------------------------------------------------------------

class TestSafe:
    """_safe is a module-level function — import after pandas is available."""

    def _safe(self, row, key, default=None):
        from jobscout.adapters.jobspy import _safe
        return _safe(row, key, default)

    def test_returns_value_when_present(self):
        row = pd.Series({"title": "AI Engineer"})
        assert self._safe(row, "title") == "AI Engineer"

    def test_returns_default_for_none(self):
        row = pd.Series({"title": None})
        assert self._safe(row, "title", default="") == ""

    def test_returns_default_for_nan(self):
        import math
        row = pd.Series({"salary": float("nan")})
        assert self._safe(row, "salary", default=None) is None

    def test_returns_default_for_nat(self):
        row = pd.Series({"date_posted": pd.NaT})
        assert self._safe(row, "date_posted", default=None) is None

    def test_returns_default_for_missing_key(self):
        row = pd.Series({"title": "Engineer"})
        assert self._safe(row, "nonexistent", default="x") == "x"

    def test_returns_namedtuple_as_is(self):
        from collections import namedtuple
        Location = namedtuple("Location", ["city", "state", "country"])
        loc = Location("Berlin", None, "Germany")
        row = pd.Series({"location": loc})
        # pd.isna() on a tuple returns an array → ValueError — must not raise
        result = self._safe(row, "location")
        assert result == loc

    def test_preserves_empty_string(self):
        row = pd.Series({"title": ""})
        # Empty string is NOT NaN — it should be returned as-is
        assert self._safe(row, "title", default="fallback") == ""

    def test_preserves_zero(self):
        row = pd.Series({"amount": 0})
        assert self._safe(row, "amount", default=None) == 0

    def test_preserves_false(self):
        row = pd.Series({"is_remote": False})
        # pandas stores bool as numpy.bool_ — use == not `is`
        assert self._safe(row, "is_remote", default=None) == False  # noqa: E712


# ---------------------------------------------------------------------------
# _is_german
# ---------------------------------------------------------------------------

class TestIsGerman:
    def test_germany(self):
        assert _is_german("Berlin, Germany") is True

    def test_deutschland(self):
        assert _is_german("München, Deutschland") is True

    def test_city_only(self):
        assert _is_german("Hamburg") is True

    def test_case_insensitive(self):
        assert _is_german("BERLIN") is True

    def test_non_german(self):
        assert _is_german("London, UK") is False

    def test_empty_string(self):
        assert _is_german("") is False

    def test_none_equivalent(self):
        assert _is_german("") is False

    def test_munich_english(self):
        assert _is_german("Munich") is True

    def test_cologne(self):
        assert _is_german("Cologne") is True

    def test_koeln(self):
        assert _is_german("Köln") is True


# ---------------------------------------------------------------------------
# _sanitize_raw
# ---------------------------------------------------------------------------

class TestSanitizeRaw:
    def test_plain_values_pass_through(self):
        row = pd.Series({"title": "AI Engineer", "salary": 60000})
        result = _sanitize_raw(row)
        assert result["title"] == "AI Engineer"
        assert result["salary"] == 60000

    def test_nan_becomes_none(self):
        row = pd.Series({"salary": float("nan")})
        result = _sanitize_raw(row)
        assert result["salary"] is None

    def test_nat_becomes_none(self):
        row = pd.Series({"date_posted": pd.NaT})
        result = _sanitize_raw(row)
        assert result["date_posted"] is None

    def test_numpy_int64_serializes(self):
        import numpy as np
        row = pd.Series({"count": np.int64(42)})
        result = _sanitize_raw(row)
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_timestamp_serializes_to_string(self):
        row = pd.Series({"created_at": pd.Timestamp("2026-04-01")})
        result = _sanitize_raw(row)
        assert isinstance(result["created_at"], str)
        assert "2026-04-01" in result["created_at"]

    def test_namedtuple_is_json_serializable(self):
        import json
        from collections import namedtuple
        Location = namedtuple("Location", ["city", "state", "country"])
        row = pd.Series({"location": Location("Berlin", None, "Germany")})
        result = _sanitize_raw(row)
        # json.dumps serializes namedtuples as arrays — result is a list, which is fine
        json.dumps(result)  # must not raise

    def test_result_is_json_serializable(self):
        import json
        import numpy as np
        row = pd.Series({
            "title": "Engineer",
            "salary": float("nan"),
            "count": np.int64(5),
            "date": pd.NaT,
        })
        result = _sanitize_raw(row)
        # Should not raise
        json.dumps(result)


# ---------------------------------------------------------------------------
# _is_german_domain
# ---------------------------------------------------------------------------

class TestIsGermanDomain:
    def test_linkedin(self):
        assert _is_german_domain("https://www.linkedin.com/jobs/view/12345") is True

    def test_indeed_de_subdomain(self):
        assert _is_german_domain("https://de.indeed.com/viewjob?jk=abc") is True

    def test_indeed_de_tld(self):
        assert _is_german_domain("https://www.indeed.de/viewjob?jk=abc") is True

    def test_indeed_com_not_german(self):
        assert _is_german_domain("https://www.indeed.com/viewjob?jk=abc") is False

    def test_non_german_domain(self):
        assert _is_german_domain("https://jobs.lever.co/company/role") is False

    def test_empty_url(self):
        assert _is_german_domain("") is False


# ---------------------------------------------------------------------------
# _since_to_hours_old
# ---------------------------------------------------------------------------

class TestSinceToHoursOld:
    def test_same_day_returns_24_floor(self):
        today = date.today()
        assert _since_to_hours_old(today) == 24

    def test_yesterday_returns_at_least_30(self):
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        result = _since_to_hours_old(yesterday)
        assert result >= 30  # 24h + 6h buffer

    def test_3_days_ago(self):
        from datetime import timedelta
        three_days = date.today() - timedelta(days=3)
        result = _since_to_hours_old(three_days)
        assert result == 3 * 24 + 6  # 78

    def test_7_days_ago(self):
        from datetime import timedelta
        seven_days = date.today() - timedelta(days=7)
        result = _since_to_hours_old(seven_days)
        assert result == 7 * 24 + 6  # 174

    def test_buffer_is_always_applied(self):
        from datetime import timedelta
        since = date.today() - timedelta(days=2)
        hours_requested = 2 * 24
        assert _since_to_hours_old(since) == hours_requested + 6


# ---------------------------------------------------------------------------
# _map_job_level
# ---------------------------------------------------------------------------

class TestMapJobLevel:
    def test_entry_level(self):
        assert _map_job_level("Entry level") == "junior"

    def test_associate(self):
        assert _map_job_level("Associate") == "junior"

    def test_mid_senior(self):
        assert _map_job_level("Mid-Senior level") == "mid"

    def test_director(self):
        assert _map_job_level("Director") == "lead"

    def test_executive(self):
        assert _map_job_level("Executive") == "lead"

    def test_not_applicable_returns_none(self):
        assert _map_job_level("Not Applicable") is None

    def test_none_input(self):
        assert _map_job_level(None) is None

    def test_case_insensitive(self):
        assert _map_job_level("ENTRY LEVEL") == "junior"


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

def _make_row(**kwargs) -> pd.Series:
    """Build a minimal valid JobSpy DataFrame row."""
    defaults = {
        "job_url": "https://linkedin.com/jobs/view/12345",
        "title": "AI Engineer",
        "company": "Acme GmbH",
        "description": "Build LLM applications in Python.",
        "location": None,
        "is_remote": False,
        "interval": None,
        "min_amount": None,
        "max_amount": None,
        "job_level": None,
        "date_posted": None,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


@pytest.fixture
def adapter() -> JobSpyAdapter:
    return JobSpyAdapter(config=MagicMock())


class TestNormalize:
    def test_id_is_url_hash(self, adapter):
        row = _make_row(job_url="https://linkedin.com/jobs/view/99999")
        listing = adapter._normalize(row)
        assert listing.id.startswith("jobspy_")
        assert len(listing.id) == len("jobspy_") + 16

    def test_same_url_produces_same_id(self, adapter):
        row = _make_row(job_url="https://linkedin.com/jobs/view/abc")
        assert adapter._normalize(row).id == adapter._normalize(row).id

    def test_source_is_jobspy(self, adapter):
        assert adapter._normalize(_make_row()).source == "jobspy"

    def test_title_and_company(self, adapter):
        row = _make_row(title="ML Engineer", company="TechCo GmbH")
        listing = adapter._normalize(row)
        assert listing.title == "ML Engineer"
        assert listing.company == "TechCo GmbH"

    def test_location_empty_when_no_city(self, adapter):
        row = _make_row(location=None)
        assert adapter._normalize(row).location == ""

    def test_location_from_city(self, adapter):
        loc = MagicMock()
        loc.city = "Berlin"
        row = _make_row(location=loc)
        assert adapter._normalize(row).location == "Berlin, Germany"

    def test_remote_policy_from_is_remote_true(self, adapter):
        row = _make_row(is_remote=True)
        assert adapter._normalize(row).remote_policy == "remote"

    def test_remote_policy_inferred_from_description(self, adapter):
        row = _make_row(is_remote=False, description="Fully remote position")
        assert adapter._normalize(row).remote_policy == "remote"

    def test_salary_only_when_yearly(self, adapter):
        row = _make_row(interval="yearly", min_amount=50000.0, max_amount=70000.0)
        listing = adapter._normalize(row)
        assert listing.salary_min == 50000.0
        assert listing.salary_max == 70000.0

    def test_salary_ignored_when_not_yearly(self, adapter):
        row = _make_row(interval="monthly", min_amount=5000.0, max_amount=7000.0)
        listing = adapter._normalize(row)
        assert listing.salary_min is None
        assert listing.salary_max is None

    def test_salary_none_when_interval_missing(self, adapter):
        row = _make_row(interval=None)
        listing = adapter._normalize(row)
        assert listing.salary_min is None

    def test_seniority_from_job_level(self, adapter):
        row = _make_row(job_level="Entry level")
        assert adapter._normalize(row).seniority == "junior"

    def test_seniority_inferred_from_title_when_no_job_level(self, adapter):
        row = _make_row(job_level=None, title="Senior ML Engineer")
        assert adapter._normalize(row).seniority == "senior"

    def test_date_from_date_object(self, adapter):
        d = date(2026, 4, 1)
        row = _make_row(date_posted=d)
        assert adapter._normalize(row).posted_date == d

    def test_date_from_datetime_object(self, adapter):
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        row = _make_row(date_posted=dt)
        assert adapter._normalize(row).posted_date == date(2026, 4, 1)

    def test_date_none_when_nat(self, adapter):
        row = _make_row(date_posted=pd.NaT)
        assert adapter._normalize(row).posted_date is None

    def test_description_defaults_to_empty_string(self, adapter):
        row = _make_row(description=None)
        assert adapter._normalize(row).description == ""


# ---------------------------------------------------------------------------
# fetch() failure modes
# ---------------------------------------------------------------------------

class TestFetchFailureModes:
    @pytest.mark.asyncio
    async def test_returns_empty_when_scrape_jobs_is_none(self):
        with patch("jobscout.adapters.jobspy.scrape_jobs", None):
            adapter = JobSpyAdapter(config=None)
            result = await adapter.fetch()
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_queries_configured(self):
        config = MagicMock()
        config.profile.jobspy_queries = []
        config.profile.jobspy_sites = {"linkedin": {"results_wanted": 10}}
        adapter = JobSpyAdapter(config=config)
        result = await adapter.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_sites_configured(self):
        config = MagicMock()
        config.profile.jobspy_queries = ["AI engineer Germany"]
        config.profile.jobspy_sites = {}
        adapter = JobSpyAdapter(config=config)
        result = await adapter.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_remote_listing_with_no_location_kept_via_german_domain(self):
        config = MagicMock()
        config.profile.jobspy_queries = ["AI engineer Germany"]
        config.profile.jobspy_sites = {
            "linkedin": {"results_wanted": 5, "fetch_description": False},
        }

        df = pd.DataFrame([{
            "job_url": "https://www.linkedin.com/jobs/view/99999",
            "title": "Remote AI Engineer",
            "company": "TechCo GmbH",
            "description": "Fully remote role.",
            "location": None,   # no location
            "is_remote": True,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "job_level": None,
            "date_posted": None,
        }])

        with patch("jobscout.adapters.jobspy.scrape_jobs", return_value=df):
            adapter = JobSpyAdapter(config=config)
            results = await adapter.fetch()

        assert len(results) == 1
        assert results[0].location == "Remote, Germany"
        assert results[0].remote_policy == "remote"

    @pytest.mark.asyncio
    async def test_remote_listing_with_non_german_domain_dropped(self):
        config = MagicMock()
        config.profile.jobspy_queries = ["AI engineer Germany"]
        config.profile.jobspy_sites = {
            "linkedin": {"results_wanted": 5, "fetch_description": False},
        }

        df = pd.DataFrame([{
            "job_url": "https://jobs.lever.co/company/role",  # non-German domain
            "title": "Remote AI Engineer",
            "company": "TechCo GmbH",
            "description": "Fully remote role.",
            "location": None,
            "is_remote": True,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "job_level": None,
            "date_posted": None,
        }])

        with patch("jobscout.adapters.jobspy.scrape_jobs", return_value=df):
            adapter = JobSpyAdapter(config=config)
            results = await adapter.fetch()

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_skips_site_on_exception_and_continues(self):
        config = MagicMock()
        config.profile.jobspy_queries = ["AI engineer Germany"]
        config.profile.jobspy_sites = {
            "indeed": {"results_wanted": 5, "country_indeed": "Germany"},
        }

        empty_df = pd.DataFrame(columns=["job_url", "title", "company", "description",
                                          "location", "is_remote", "interval",
                                          "min_amount", "max_amount", "job_level", "date_posted"])

        call_count = 0

        def mock_scrape(**kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("rate limited")

        with patch("jobscout.adapters.jobspy.scrape_jobs", mock_scrape):
            adapter = JobSpyAdapter(config=config)
            result = await adapter.fetch()

        assert result == []
        assert call_count == 1
