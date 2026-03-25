"""Tests for hard_filter.py predicates and the top-level apply_hard_filter function.

All tests use minimal JobListing and UserProfile fixtures — no network calls,
no config singleton.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from jobscout.filters.hard_filter import (
    apply_hard_filter,
    _passes_company,
    _passes_exclude_keywords,
    _passes_experience,
    _passes_location,
    _passes_require_keywords,
    _passes_salary,
    _passes_seniority,
)
from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    SalaryConfig,
    SeniorityConfig,
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
        salary=SalaryConfig(minimum_annual_eur=50_000.0, target_annual_eur=65_000.0),
        seniority=SeniorityConfig(target=["junior", "mid"], exclude=["intern", "director", "vp"]),
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
# _passes_seniority
# ---------------------------------------------------------------------------

class TestPassesSeniority:
    def test_target_seniority_passes(self):
        assert _passes_seniority(_make_job(seniority="mid"), PROFILE)

    def test_excluded_seniority_drops(self):
        assert not _passes_seniority(_make_job(seniority="intern"), PROFILE)

    def test_not_specified_passes(self):
        assert _passes_seniority(_make_job(seniority="not_specified"), PROFILE)

    def test_none_seniority_passes(self):
        assert _passes_seniority(_make_job(seniority=None), PROFILE)

    def test_director_drops(self):
        assert not _passes_seniority(_make_job(seniority="director"), PROFILE)

    def test_senior_not_in_target_drops(self):
        assert not _passes_seniority(_make_job(seniority="senior"), PROFILE)

    def test_lead_not_in_target_drops(self):
        assert not _passes_seniority(_make_job(seniority="lead"), PROFILE)

    def test_junior_in_target_passes(self):
        assert _passes_seniority(_make_job(seniority="junior"), PROFILE)


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
# _passes_salary
# ---------------------------------------------------------------------------

class TestPassesSalary:
    def test_salary_above_minimum_passes(self):
        assert _passes_salary(_make_job(salary_min=55_000, salary_max=75_000), PROFILE)

    def test_salary_max_below_minimum_drops(self):
        assert not _passes_salary(_make_job(salary_min=30_000, salary_max=45_000), PROFILE)

    def test_salary_max_exactly_minimum_passes(self):
        assert _passes_salary(_make_job(salary_min=None, salary_max=50_000), PROFILE)

    def test_none_salary_max_passes(self):
        assert _passes_salary(_make_job(salary_min=None, salary_max=None), PROFILE)

    def test_none_salary_min_with_valid_max_passes(self):
        assert _passes_salary(_make_job(salary_min=None, salary_max=60_000), PROFILE)


# ---------------------------------------------------------------------------
# _passes_location
# ---------------------------------------------------------------------------

class TestPassesLocation:
    def test_remote_policy_remote_always_passes(self):
        assert _passes_location(_make_job(remote_policy="remote", location="Anywhere"), PROFILE)

    def test_germany_location_passes(self):
        assert _passes_location(_make_job(location="Berlin, Germany", remote_policy="onsite"), PROFILE)

    def test_non_germany_onsite_drops(self):
        assert not _passes_location(
            _make_job(location="London, UK", remote_policy="onsite"), PROFILE
        )

    def test_not_specified_with_germany_location_passes(self):
        assert _passes_location(
            _make_job(location="Munich, Germany", remote_policy="not_specified"), PROFILE
        )

    def test_not_specified_without_germany_drops(self):
        assert not _passes_location(
            _make_job(location="Amsterdam, Netherlands", remote_policy="not_specified"), PROFILE
        )


# ---------------------------------------------------------------------------
# apply_hard_filter (integration)
# ---------------------------------------------------------------------------

class TestApplyHardFilter:
    def test_all_pass(self):
        jobs = [_make_job(id=str(i)) for i in range(5)]
        result = apply_hard_filter(jobs, PROFILE)
        assert len(result) == 5

    def test_filters_out_excluded_seniority(self):
        jobs = [_make_job(id="1", seniority="intern"), _make_job(id="2", seniority="mid")]
        result = apply_hard_filter(jobs, PROFILE)
        assert len(result) == 1
        assert result[0].id == "2"

    def test_empty_input_returns_empty(self):
        assert apply_hard_filter([], PROFILE) == []

    def test_all_filtered_returns_empty(self):
        jobs = [_make_job(title="Frontend Developer", description="React work only") for _ in range(3)]
        result = apply_hard_filter(jobs, PROFILE)
        assert result == []

    def test_filters_out_senior_not_in_target(self):
        jobs = [_make_job(id="1", seniority="senior"), _make_job(id="2", seniority="mid")]
        result = apply_hard_filter(jobs, PROFILE)
        assert len(result) == 1
        assert result[0].id == "2"


# ---------------------------------------------------------------------------
# _passes_experience
# ---------------------------------------------------------------------------

def _profile_with_max_years(max_years: int) -> UserProfile:
    return _make_profile(seniority=SeniorityConfig(
        target=["junior", "mid"], exclude=["intern"], max_years_experience=max_years
    ))


class TestPassesExperience:
    def test_passes_when_no_limit_set(self):
        job = _make_job(description="5+ years of professional experience required.")
        assert _passes_experience(job, _make_profile()) is True

    def test_passes_when_years_within_limit(self):
        job = _make_job(description="3+ years of experience with Python.")
        assert _passes_experience(job, _profile_with_max_years(4)) is True

    def test_fails_when_years_exceed_limit(self):
        job = _make_job(description="5+ years of professional experience required.")
        assert _passes_experience(job, _profile_with_max_years(4)) is False

    def test_fails_for_varied_phrasing(self):
        phrasings = [
            "Minimum 6 years of work experience.",
            "You have 7 years of industry experience.",
            "At least 5 years of relevant experience.",
            "8+ years of expertise in ML.",
        ]
        for desc in phrasings:
            job = _make_job(description=desc)
            assert _passes_experience(job, _profile_with_max_years(4)) is False, desc

    def test_passes_when_no_experience_mentioned(self):
        job = _make_job(description="Build LLM applications with LangChain.")
        assert _passes_experience(job, _profile_with_max_years(4)) is True

    def test_passes_with_range_where_minimum_is_within_limit(self):
        # "3 to 7 years" — minimum is 3, within limit of 4
        job = _make_job(description="3 to 7 years of experience preferred.")
        assert _passes_experience(job, _profile_with_max_years(4)) is True

    def test_fails_german_berufserfahrung(self):
        job = _make_job(description="5 Jahre Berufserfahrung erforderlich.")
        assert _passes_experience(job, _profile_with_max_years(4)) is False

    def test_fails_german_relevante_berufserfahrung(self):
        job = _make_job(description="Mindestens 6 Jahre relevante Berufserfahrung.")
        assert _passes_experience(job, _profile_with_max_years(4)) is False

    def test_passes_german_within_limit(self):
        job = _make_job(description="3 Jahre Berufserfahrung gewünscht.")
        assert _passes_experience(job, _profile_with_max_years(4)) is True
