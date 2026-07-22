"""Tests for hard_filter.py predicates and the top-level apply_hard_filter function.

All tests use minimal JobListing and UserProfile fixtures — no network calls,
no config singleton.
"""
from __future__ import annotations

from datetime import datetime

from jobscout.filters.hard_filter import (
    apply_hard_filter,
    _passes_company,
    _passes_exclude_keywords,
    _passes_location,
    _passes_require_keywords,
)
from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    SkillsConfig,
    UserProfile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> JobListing:
    defaults = dict(
        id="job-1",
        source="adzuna_de",
        title="ML Engineer",
        company="Acme GmbH",
        description="We work on machine learning and AI systems.",
        location="Berlin, Germany",
        remote_percentage=50,
        url="https://example.com/job/1",
        posted_date=datetime(2026, 3, 18, 9, 30, 0),
        fetched_at=datetime(2026, 3, 18, 12, 0, 0),
        raw_data={},
    )
    defaults.update(overrides)
    return JobListing(**defaults)


def _make_profile(**overrides) -> UserProfile:
    defaults = dict(
        name="Marcos",
        target_roles=["ML Engineer"],
        skills=SkillsConfig(),
        location=LocationConfig(
            target_countries=["Germany"],
            preferred_cities=["Berlin"],
            remote_acceptable=True,
            eu_work_authorization=True,
        ),
        dealbreakers=DealbreakersConfig(
            exclude_companies=[],
            exclude_keywords=["Unpaid", "Volunteer"],
            require_any_keyword=["machine learning", "ML", "AI", "LLM"],
        ),
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


PROFILE = _make_profile()


# ---------------------------------------------------------------------------
# _passes_company
# ---------------------------------------------------------------------------

class TestPassesCompany:
    def test_no_exclusions_always_passes(self):
        assert _passes_company(_make_job(company="Google"), PROFILE)

    def test_excluded_company_drops(self):
        profile = _make_profile(
            dealbreakers=DealbreakersConfig(exclude_companies=["Bad Corp"])
        )
        assert not _passes_company(_make_job(company="Bad Corp"), profile)

    def test_excluded_company_case_insensitive(self):
        profile = _make_profile(
            dealbreakers=DealbreakersConfig(exclude_companies=["Bad Corp"])
        )
        assert not _passes_company(_make_job(company="bad corp"), profile)

    def test_partial_name_does_not_match(self):
        profile = _make_profile(
            dealbreakers=DealbreakersConfig(exclude_companies=["Google"])
        )
        assert _passes_company(_make_job(company="Google DeepMind"), profile)


# ---------------------------------------------------------------------------
# _passes_exclude_keywords
# ---------------------------------------------------------------------------

class TestPassesExcludeKeywords:
    def test_clean_job_passes(self):
        assert _passes_exclude_keywords(_make_job(), PROFILE)

    def test_exclude_keyword_in_title_drops(self):
        assert not _passes_exclude_keywords(_make_job(title="Unpaid ML Internship"), PROFILE)

    def test_exclude_keyword_in_description_drops(self):
        assert not _passes_exclude_keywords(
            _make_job(description="This is a volunteer position."), PROFILE
        )

    def test_exclude_keyword_case_insensitive(self):
        assert not _passes_exclude_keywords(_make_job(title="unpaid internship"), PROFILE)

    def test_no_exclusions_always_passes(self):
        profile = _make_profile(dealbreakers=DealbreakersConfig(exclude_keywords=[]))
        assert _passes_exclude_keywords(_make_job(title="Unpaid"), profile)


# ---------------------------------------------------------------------------
# _passes_require_keywords
# ---------------------------------------------------------------------------

class TestPassesRequireKeywords:
    def test_matching_keyword_in_title_passes(self):
        assert _passes_require_keywords(_make_job(title="ML Engineer"), PROFILE)

    def test_matching_keyword_in_description_passes(self):
        assert _passes_require_keywords(
            _make_job(title="Engineer", description="Working on LLM pipelines"), PROFILE
        )

    def test_no_matching_keyword_drops(self):
        assert not _passes_require_keywords(
            _make_job(title="Frontend Developer", description="React and CSS work"), PROFILE
        )

    def test_keyword_case_insensitive(self):
        assert _passes_require_keywords(
            _make_job(title="ai engineer", description="working on ai"), PROFILE
        )

    def test_word_boundary_ml_does_not_match_xml(self):
        assert not _passes_require_keywords(
            _make_job(title="XML Developer", description="XML processing and parsing"), PROFILE
        )

    def test_word_boundary_ml_does_not_match_email(self):
        assert not _passes_require_keywords(
            _make_job(title="Email Developer", description="email campaign tooling"), PROFILE
        )

    def test_word_boundary_ml_matches_standalone(self):
        assert _passes_require_keywords(
            _make_job(title="ML Ops Engineer", description="deploy ML models"), PROFILE
        )

    def test_no_requirements_always_passes(self):
        profile = _make_profile(dealbreakers=DealbreakersConfig(require_any_keyword=[]))
        assert _passes_require_keywords(_make_job(title="Frontend Developer"), profile)


# ---------------------------------------------------------------------------
# _passes_location
# ---------------------------------------------------------------------------

class TestPassesLocation:
    def test_remote_policy_remote_always_passes(self):
        assert _passes_location(_make_job(remote_percentage=100, location="Anywhere"), PROFILE)

    def test_germany_location_passes(self):
        assert _passes_location(_make_job(location="Berlin, Germany", remote_percentage=0), PROFILE)

    def test_non_germany_onsite_drops(self):
        assert not _passes_location(
            _make_job(location="London, UK", remote_percentage=0), PROFILE
        )

    def test_not_specified_with_germany_location_passes(self):
        assert _passes_location(
            _make_job(
                location="Munich, Germany",
                remote_percentage=None,
                remote_policy_text="not_specified",
            ),
            PROFILE,
        )

    def test_not_specified_without_germany_drops(self):
        assert not _passes_location(
            _make_job(
                location="Amsterdam, Netherlands",
                remote_percentage=None,
                remote_policy_text="not_specified",
            ),
            PROFILE,
        )


# ---------------------------------------------------------------------------
# apply_hard_filter (integration)
# ---------------------------------------------------------------------------

class TestApplyHardFilter:
    def test_all_pass(self):
        jobs = [_make_job(id=str(i)) for i in range(5)]
        result = apply_hard_filter(jobs, PROFILE)
        assert len(result) == 5

    def test_empty_input_returns_empty(self):
        assert apply_hard_filter([], PROFILE) == []

    def test_all_filtered_returns_empty(self):
        jobs = [_make_job(title="Frontend Developer", description="React work only") for _ in range(3)]
        result = apply_hard_filter(jobs, PROFILE)
        assert result == []


# ---------------------------------------------------------------------------
# Gates removed by the contract pivot
#
# These assert the observable consequence of deleting _passes_seniority,
# _passes_experience and _passes_salary: listings each of them used to reject
# now survive the filter. Stated at the pipeline's own seam, because "the
# predicate is gone" is not something a test can observe directly.
# ---------------------------------------------------------------------------

class TestRemovedGatesNoLongerReject:
    def test_senior_listing_survives(self):
        """A senior/lead framing was JobScout's own inference, and it dropped the job."""
        job = _make_job(
            title="Senior ML Engineer",
            description="Senior role — mehrjährige Erfahrung with machine learning.",
        )
        assert apply_hard_filter([job], PROFILE) == [job]

    def test_high_years_of_experience_listing_survives(self):
        """The max_years ceiling deleted a senior-skewing freelance pool invisibly."""
        job = _make_job(description="8+ years of professional experience in machine learning.")
        assert apply_hard_filter([job], PROFILE) == [job]

    def test_german_years_of_experience_listing_survives(self):
        job = _make_job(description="Mindestens 6 Jahre relevante Berufserfahrung. Thema: machine learning.")
        assert apply_hard_filter([job], PROFILE) == [job]

    def test_listing_with_no_rate_survives(self):
        """All-None rate is the DACH norm — the salary floor would reject the whole corpus."""
        job = _make_job(rate_min=None, rate_max=None, rate_unit=None, rate_currency=None)
        assert apply_hard_filter([job], PROFILE) == [job]

    def test_low_rate_listing_survives(self):
        """Nothing in the filter reads rate at all — a low day rate is a ranking concern."""
        job = _make_job(rate_min=100.0, rate_max=100.0, rate_unit="daily", rate_currency="EUR")
        assert apply_hard_filter([job], PROFILE) == [job]
