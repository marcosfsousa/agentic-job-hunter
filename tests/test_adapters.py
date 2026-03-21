"""Tests for Adzuna and JSearch adapter normalization logic.

All tests use fixture files and test _normalize() / inference helpers
directly — no network calls are made.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from jobscout.adapters.adzuna import (
    AdzunaAdapter,
    AdzunaJobRaw,
    _infer_remote_policy,
    _infer_seniority,
    _parse_date,
)
from jobscout.adapters.jsearch import (
    JSearchAdapter,
    _JSearchJobRaw,
    _infer_seniority as _jsearch_infer_seniority,
    _parse_date as _jsearch_parse_date,
)
from jobscout.models import JobListing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_response() -> dict:
    return json.loads((FIXTURES_DIR / "sample_adzuna_response.json").read_text())


@pytest.fixture
def raw_listings(sample_response) -> list[dict]:
    return sample_response["results"]


@pytest.fixture
def adapter() -> AdzunaAdapter:
    # config=None is fine — we never call fetch() in these tests
    return AdzunaAdapter(config=None)


# ---------------------------------------------------------------------------
# _infer_remote_policy
# ---------------------------------------------------------------------------

class TestInferRemotePolicy:
    def test_remote_keyword_in_title(self):
        assert _infer_remote_policy("Remote ML Engineer", "", "") == "remote"

    def test_remote_keyword_in_description(self):
        assert _infer_remote_policy("ML Engineer", "Fully remote within Germany", "") == "remote"

    def test_remote_keyword_in_location(self):
        assert _infer_remote_policy("ML Engineer", "", "Remote (Germany)") == "remote"

    def test_hybrid_wins_over_remote(self):
        # "hybrid" description that also mentions remote
        assert _infer_remote_policy("", "Hybrid model, some remote work allowed", "") == "hybrid"

    def test_homeoffice_german(self):
        assert _infer_remote_policy("", "Homeoffice möglich", "") == "remote"

    def test_onsite(self):
        assert _infer_remote_policy("", "This is an on-site role in Berlin", "") == "onsite"

    def test_not_specified_default(self):
        assert _infer_remote_policy("ML Engineer", "Build great models", "Berlin") == "not_specified"


# ---------------------------------------------------------------------------
# _infer_seniority
# ---------------------------------------------------------------------------

class TestInferSeniority:
    def test_senior_in_title(self):
        assert _infer_seniority("Senior ML Engineer", "") == "senior"

    def test_junior_in_title(self):
        assert _infer_seniority("Junior Data Scientist", "") == "junior"

    def test_lead_in_title(self):
        assert _infer_seniority("Lead Machine Learning Engineer", "") == "lead"

    def test_graduate_maps_to_junior(self):
        assert _infer_seniority("ML Engineer", "Graduate position, entry-level") == "junior"

    def test_mid_level_in_description(self):
        assert _infer_seniority("ML Engineer", "We are looking for a mid-level engineer") == "mid"

    def test_lead_beats_senior(self):
        # "lead" should win even if "senior" also appears
        assert _infer_seniority("Lead Senior Engineer", "") == "lead"

    def test_none_when_no_signal(self):
        assert _infer_seniority("ML Engineer", "Build models with Python") is None


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_iso_timestamp(self):
        assert _parse_date("2026-03-15T09:00:00Z") == date(2026, 3, 15)

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None


# ---------------------------------------------------------------------------
# AdzunaJobRaw Pydantic validation
# ---------------------------------------------------------------------------

class TestAdzunaJobRaw:
    def test_valid_listing(self, raw_listings):
        validated = AdzunaJobRaw.model_validate(raw_listings[0])
        assert validated.id == "4801234567"
        assert validated.company.display_name == "TechCorp GmbH"
        assert validated.location.display_name == "Berlin"

    def test_missing_company_uses_default(self):
        minimal = {
            "id": "99",
            "title": "Engineer",
            "description": "desc",
            "redirect_url": "http://example.com",
            "created": "2026-01-01T00:00:00Z",
        }
        validated = AdzunaJobRaw.model_validate(minimal)
        assert validated.company.display_name == "Unknown"

    def test_predicted_salary_flag(self, raw_listings):
        # Third fixture listing has salary_is_predicted=1
        validated = AdzunaJobRaw.model_validate(raw_listings[2])
        assert validated.salary_is_predicted == 1


# ---------------------------------------------------------------------------
# _normalize via adapter
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_returns_joblisting(self, adapter, raw_listings):
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        assert isinstance(job, JobListing)

    def test_source_is_adzuna_de(self, adapter, raw_listings):
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        assert job.source == "adzuna_de"

    def test_senior_listing_fields(self, adapter, raw_listings):
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        assert job.id == "4801234567"
        assert job.title == "Senior ML Engineer"
        assert job.company == "TechCorp GmbH"
        assert job.salary_min == 70000.0
        assert job.salary_max == 90000.0
        assert job.seniority == "senior"
        assert job.posted_date == date(2026, 3, 15)

    def test_remote_in_description_inferred(self, adapter, raw_listings):
        # First listing description contains "Remote work possible"
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        assert job.remote_policy == "remote"

    def test_hybrid_listing(self, adapter, raw_listings):
        # Second listing description contains "Hybrid work model"
        raw = AdzunaJobRaw.model_validate(raw_listings[1])
        job = adapter._normalize(raw, raw_listings[1])
        assert job.remote_policy == "hybrid"

    def test_predicted_salary_becomes_none(self, adapter, raw_listings):
        # Third listing has salary_is_predicted=1 — should be discarded
        raw = AdzunaJobRaw.model_validate(raw_listings[2])
        job = adapter._normalize(raw, raw_listings[2])
        assert job.salary_min is None
        assert job.salary_max is None

    def test_raw_data_stored(self, adapter, raw_listings):
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        assert job.raw_data["id"] == "4801234567"

    def test_joblisting_is_frozen(self, adapter, raw_listings):
        from dataclasses import FrozenInstanceError
        raw = AdzunaJobRaw.model_validate(raw_listings[0])
        job = adapter._normalize(raw, raw_listings[0])
        with pytest.raises(FrozenInstanceError):
            job.title = "mutated"

    def _make_raw_with_location(self, raw_listings: list[dict], display_name: str) -> AdzunaJobRaw:
        entry = {**raw_listings[0], "location": {"display_name": display_name}}
        return AdzunaJobRaw.model_validate(entry)

    def test_deutschland_alone_becomes_germany(self, adapter, raw_listings):
        raw = self._make_raw_with_location(raw_listings, "Deutschland")
        job = adapter._normalize(raw, {})
        assert job.location == "Germany"

    def test_city_deutschland_becomes_city_germany(self, adapter, raw_listings):
        raw = self._make_raw_with_location(raw_listings, "Berlin, Deutschland")
        job = adapter._normalize(raw, {})
        assert job.location == "Berlin, Germany"

    def test_city_without_country_appends_germany(self, adapter, raw_listings):
        raw = self._make_raw_with_location(raw_listings, "Hamburg")
        job = adapter._normalize(raw, {})
        assert job.location == "Hamburg, Germany"

    def test_already_germany_unchanged(self, adapter, raw_listings):
        raw = self._make_raw_with_location(raw_listings, "Berlin, Germany")
        job = adapter._normalize(raw, {})
        assert job.location == "Berlin, Germany"


# ===========================================================================
# JSearch adapter tests
# ===========================================================================

@pytest.fixture
def jsearch_response() -> dict:
    return json.loads((FIXTURES_DIR / "sample_jsearch_response.json").read_text())


@pytest.fixture
def jsearch_listings(jsearch_response) -> list[dict]:
    return jsearch_response["data"]


@pytest.fixture
def jsearch_adapter() -> JSearchAdapter:
    from types import SimpleNamespace
    config = SimpleNamespace(open_web_ninja_api_key="test-key")
    return JSearchAdapter(config=config)


# ---------------------------------------------------------------------------
# _JSearchJobRaw validation
# ---------------------------------------------------------------------------

class TestJSearchJobRaw:
    def test_valid_listing(self, jsearch_listings):
        validated = _JSearchJobRaw.model_validate(jsearch_listings[0])
        assert validated.job_id == "jsearch_001"
        assert validated.employer_name == "AI Startup GmbH"
        assert validated.job_city == "Berlin"

    def test_null_city_defaults_to_none(self, jsearch_listings):
        validated = _JSearchJobRaw.model_validate(jsearch_listings[2])
        assert validated.job_city is None

    def test_null_posted_date_defaults_to_none(self, jsearch_listings):
        validated = _JSearchJobRaw.model_validate(jsearch_listings[2])
        assert validated.job_posted_at_datetime_utc is None

    def test_missing_employer_defaults_to_unknown(self):
        raw = {
            "job_id": "x1",
            "job_title": "ML Engineer",
        }
        validated = _JSearchJobRaw.model_validate(raw)
        assert validated.employer_name == "Unknown"


# ---------------------------------------------------------------------------
# _parse_date (JSearch)
# ---------------------------------------------------------------------------

class TestJSearchParseDate:
    def test_valid_timestamp(self):
        assert _jsearch_parse_date("2026-03-20T09:00:00Z") == date(2026, 3, 20)

    def test_none_returns_none(self):
        assert _jsearch_parse_date(None) is None

    def test_invalid_returns_none(self):
        assert _jsearch_parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# _normalize via JSearch adapter
# ---------------------------------------------------------------------------

class TestJSearchNormalize:
    def test_returns_joblisting(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert isinstance(job, JobListing)

    def test_source_is_jsearch(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.source == "jsearch"

    def test_salary_always_none(self, jsearch_adapter, jsearch_listings):
        for listing in jsearch_listings:
            raw = _JSearchJobRaw.model_validate(listing)
            job = jsearch_adapter._normalize(raw, listing)
            assert job.salary_min is None
            assert job.salary_max is None

    def test_job_is_remote_true_sets_remote_policy(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[1])  # job_is_remote=True
        job = jsearch_adapter._normalize(raw, jsearch_listings[1])
        assert job.remote_policy == "remote"

    def test_remote_inferred_from_description(self, jsearch_adapter, jsearch_listings):
        # First listing: job_is_remote=False but description says "Remote work possible"
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.remote_policy == "remote"

    def test_seniority_inferred_from_title(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])  # "Senior ML Engineer"
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.seniority == "senior"

    def test_junior_seniority_inferred(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[1])  # "Junior AI Engineer"
        job = jsearch_adapter._normalize(raw, jsearch_listings[1])
        assert job.seniority == "junior"

    def test_city_appends_germany(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])  # city="Berlin"
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.location == "Berlin, Germany"

    def test_no_city_defaults_to_germany(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[2])  # city=None
        job = jsearch_adapter._normalize(raw, jsearch_listings[2])
        assert job.location == "Germany"

    def test_null_posted_date_becomes_none(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[2])
        job = jsearch_adapter._normalize(raw, jsearch_listings[2])
        assert job.posted_date is None

    def test_posted_date_parsed(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.posted_date == date(2026, 3, 20)

    def test_raw_data_stored(self, jsearch_adapter, jsearch_listings):
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        assert job.raw_data["job_id"] == "jsearch_001"

    def test_joblisting_is_frozen(self, jsearch_adapter, jsearch_listings):
        from dataclasses import FrozenInstanceError
        raw = _JSearchJobRaw.model_validate(jsearch_listings[0])
        job = jsearch_adapter._normalize(raw, jsearch_listings[0])
        with pytest.raises(FrozenInstanceError):
            job.title = "mutated"
