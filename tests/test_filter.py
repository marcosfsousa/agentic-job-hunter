"""Tests for hard_filter.py predicates and the top-level apply_hard_filter function.

All tests use minimal JobListing and UserProfile fixtures — no network calls,
no config singleton.
"""
from __future__ import annotations

import logging
from datetime import datetime

from jobscout.filters.hard_filter import (
    apply_hard_filter,
    _passes_company,
    _passes_contract_type,
    _passes_employee_leasing,
    _passes_exclude_keywords,
    _passes_location,
    _passes_require_keywords,
)
from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    RateConfig,
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
        location=LocationConfig(target_countries=["Germany"]),
        rate=RateConfig(),
        dealbreakers=DealbreakersConfig(
            exclude_companies=[],
            exclude_keywords=["Unpaid", "Volunteer"],
            require_any_keyword=["machine learning", "ML", "AI", "LLM"],
            # Both new gates are stated explicitly rather than inherited from the
            # model defaults. The shipped default floor is 100, which would reject
            # the 50%-remote default job — so every test unrelated to the remote
            # gate would be silently gated on it and read as testing something
            # else. Tests that mean to exercise a gate set its value themselves.
            exclude_contract_types=[],
            minimum_remote_percentage=None,
        ),
        freelancermap_queries=["Machine Learning"],
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _gated(
    *,
    contract_types: list | None = None,
    remote_floor: int | None = None,
) -> UserProfile:
    """A profile with one or both new gates armed, keeping the base dealbreakers.

    Overriding `dealbreakers=` wholesale would silently drop `exclude_keywords` and
    `require_any_keyword`, so an `apply_hard_filter` assertion built that way would
    run with the surviving predicates inert — proving the new gate is wired, but
    only in a filter that has nothing else in it.
    """
    base = _make_profile().dealbreakers
    return _make_profile(
        dealbreakers=base.model_copy(update={
            "exclude_contract_types": contract_types or [],
            "minimum_remote_percentage": remote_floor,
        })
    )


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
# _passes_contract_type
# ---------------------------------------------------------------------------

class TestPassesContractType:
    def test_blocklisted_type_is_rejected(self):
        profile = _gated(contract_types=["employee_leasing", "permanent_position"])
        assert not _passes_contract_type(_make_job(contract_type="employee_leasing"), profile)

    def test_second_blocklisted_type_is_rejected(self):
        profile = _gated(contract_types=["employee_leasing", "permanent_position"])
        assert not _passes_contract_type(_make_job(contract_type="permanent_position"), profile)

    def test_contracting_passes(self):
        profile = _gated(contract_types=["employee_leasing", "permanent_position"])
        assert _passes_contract_type(_make_job(contract_type="contracting"), profile)

    def test_unknown_passes(self):
        """The whole reason this is a blocklist rather than an allowlist.

        An allowlist of ["contracting"] would silently delete every `unknown` row
        the day a source that cannot determine the engagement form is added. If
        someone "simplifies" the predicate to an allowlist, this is what catches it.
        """
        profile = _gated(contract_types=["employee_leasing", "permanent_position"])
        assert _passes_contract_type(_make_job(contract_type="unknown"), profile)

    def test_empty_blocklist_rejects_nothing(self):
        """The predicate's disabled state is expressible without deleting it."""
        profile = _gated()
        assert _passes_contract_type(_make_job(contract_type="employee_leasing"), profile)

    def test_outcome_follows_config_not_a_constant(self):
        """Two profiles differing only in the blocklist must disagree about one job.

        A single hardcoded-looking profile would pass identically against a
        predicate that hardcoded "drop leasing + permanent", so this is the
        assertion that actually proves the config wiring landed.
        """
        job = _make_job(contract_type="employee_leasing")
        assert _passes_contract_type(job, _gated())
        assert not _passes_contract_type(job, _gated(contract_types=["employee_leasing"]))


# ---------------------------------------------------------------------------
# _passes_employee_leasing
#
# The prose half of the gate above. Classification itself is tested in
# tests/test_employee_leasing.py; what is asserted here is the wiring — that the
# predicate acts on `exclusive` only, that it is armed by config rather than by a
# constant, and that the drop is not silent.
# ---------------------------------------------------------------------------

_ARMED = _gated(contract_types=["employee_leasing"])

# The default description carries a `require_any_keyword` hit, so a leasing job
# built from it fails on the leasing predicate or not at all. Without that, an
# `apply_hard_filter` assertion below would pass on the require-keyword gate and
# read as proof of a predicate that was never reached.
_CLEAN = "We work on machine learning and AI systems."


class TestPassesEmployeeLeasing:
    def test_exclusive_prose_is_rejected(self):
        job = _make_job(description=f"{_CLEAN} Bitte beachten: keine Freiberufler.")
        assert not _passes_employee_leasing(job, _ARMED)

    def test_optional_prose_passes(self):
        """`optional` is kept, deliberately. Leasing on offer is not leasing imposed."""
        job = _make_job(description=f"{_CLEAN} Einsatz als Freiberufler oder ANÜ möglich.")
        assert _passes_employee_leasing(job, _ARMED)

    def test_silent_posting_passes(self):
        assert _passes_employee_leasing(_make_job(description=_CLEAN), _ARMED)

    def test_the_title_is_read_too(self):
        """Same text basis as every other text predicate here: title + description.

        A posting that puts the engagement form in its title and nowhere else is
        not a hypothetical on a German board, and reading only the body would make
        the gate depend on where the agency chose to type the words.
        """
        job = _make_job(title="ML Engineer (nur ANÜ)", description=_CLEAN)
        assert not _passes_employee_leasing(job, _ARMED)

    def test_outcome_follows_config_not_a_constant(self):
        """One switch drives both layers of the gate.

        Scanning for leasing prose while the user permits `employee_leasing` would
        drop rows they asked to see, so the prose backstop reads the same config
        key the metadata gate does rather than carrying a constant of its own.
        """
        job = _make_job(description=f"{_CLEAN} Bitte beachten: keine Freiberufler.")
        assert _passes_employee_leasing(job, _gated())
        assert not _passes_employee_leasing(job, _ARMED)

    def test_the_drop_names_the_cue_that_caused_it(self, caplog):
        """A silent drop is invisible to review, which is the defect underneath.

        This is the whole of the drop's observability today — the predicate logs
        its own rejection because nothing else in the pipeline carries a reason.
        The general fix is the drop ledger, and it is a separate issue.
        """
        job = _make_job(id="anue-1", description=f"{_CLEAN} AÜ zwingend erforderlich.")
        with caplog.at_level(logging.INFO, logger="jobscout.filters.hard_filter"):
            assert not _passes_employee_leasing(job, _ARMED)
        assert "anue-1" in caplog.text
        assert "AÜ zwingend" in caplog.text


# ---------------------------------------------------------------------------
# _passes_location
#
# Three tickets amended this predicate in sequence — D reshaped it, F added the
# fail-open remote gate, P moved the threshold into config — so each composed
# branch is pinned separately below.
# ---------------------------------------------------------------------------

class TestPassesLocationRemoteFloor:
    """A known percentage decides alone — the country check does not run."""

    def test_at_the_floor_passes_with_a_non_matching_country(self):
        """Story 16: a remote project is not rejected for being posted from Lisbon."""
        job = _make_job(remote_percentage=100, location="Lisbon, Portugal")
        assert _passes_location(job, _gated(remote_floor=100))

    def test_above_the_floor_passes_with_a_non_matching_country(self):
        job = _make_job(remote_percentage=80, location="London, UK")
        assert _passes_location(job, _gated(remote_floor=50))

    def test_below_the_floor_is_rejected_despite_a_matching_country(self):
        """Story 17: the remote gate outranks location, not the other way round."""
        job = _make_job(remote_percentage=40, location="Berlin, Germany")
        assert not _passes_location(job, _gated(remote_floor=100))

    def test_outcome_follows_config_not_a_constant(self):
        """The same listing, two floors, opposite outcomes — proves P's move landed."""
        job = _make_job(remote_percentage=60, location="Berlin, Germany")
        assert _passes_location(job, _gated(remote_floor=50))
        assert not _passes_location(job, _gated(remote_floor=80))


class TestPassesLocationWhenPercentageIsUnknown:
    """The remote axis fails open; the location axis still applies.

    "Fails open" is scoped to remoteness: an unknown percentage means the row is
    not rejected *for being insufficiently remote*. It does not mean the row skips
    the country check — reading it that way would make `target_countries` dead
    config, which contradicts it being the only surviving location field.
    """

    def test_matching_country_passes(self):
        job = _make_job(
            remote_percentage=None,
            remote_policy_text="not_specified",
            location="Munich, Germany",
        )
        assert _passes_location(job, _gated(remote_floor=100))

    def test_non_matching_country_is_rejected(self):
        """The assertion that pins the resolved reading.

        Under the literal reading of ADR 0002 — "remote_percentage null → pass" —
        this would pass and `target_countries` would never be consulted. Both
        designs are indistinguishable without this test; do not drop it as an edge
        case. It also matters in practice: freelancermap's `remoteInPercent`
        populated-rate is still unmeasured (spec 3), so if most rows carry no
        percentage the literal reading means no location filtering at all.
        """
        job = _make_job(
            remote_percentage=None,
            remote_policy_text="not_specified",
            location="Amsterdam, Netherlands",
        )
        assert not _passes_location(job, _gated(remote_floor=100))

    def test_text_only_remote_is_exempt_from_the_country_check(self):
        """Story 19: read the best signal available, not only the structured one.

        Scoped to this class, the exemption fires because the source published no
        percentage — `remote_policy` falls back to the text. It cannot contradict
        the floor, which returned already whenever both values were present. (The
        same branch also carries fully-remote work when the gate is switched off;
        `TestPassesLocationWhenGateDisabled` covers that case.)
        """
        job = _make_job(
            remote_percentage=None,
            remote_policy_text="remote",
            location="Lisbon, Portugal",
        )
        assert _passes_location(job, _gated(remote_floor=100))


class TestPassesLocationWhenGateDisabled:
    """`minimum_remote_percentage: None` — story 20, widening without deleting config."""

    def test_low_remote_percentage_in_a_target_country_passes(self):
        """The percentage is no longer consulted; the country check decides."""
        job = _make_job(remote_percentage=0, location="Berlin, Germany")
        assert _passes_location(job, _gated(remote_floor=None))

    def test_low_remote_percentage_outside_target_countries_is_rejected(self):
        job = _make_job(remote_percentage=0, location="London, UK")
        assert not _passes_location(job, _gated(remote_floor=None))

    def test_fully_remote_still_passes_via_the_policy_exemption(self):
        job = _make_job(remote_percentage=100, location="Anywhere")
        assert _passes_location(job, _gated(remote_floor=None))

    def test_unknown_percentage_falls_through_to_the_country_check(self):
        assert _passes_location(
            _make_job(
                location="Munich, Germany",
                remote_percentage=None,
                remote_policy_text="not_specified",
            ),
            _gated(remote_floor=None),
        )
        assert not _passes_location(
            _make_job(
                location="Amsterdam, Netherlands",
                remote_percentage=None,
                remote_policy_text="not_specified",
            ),
            _gated(remote_floor=None),
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

    # Both new gates are asserted at the pipeline's own boundary as well as
    # individually, so a predicate that is correct but never wired into
    # `_passes_all` is caught.

    def test_blocklisted_contract_type_never_reaches_evaluation(self):
        leasing = _make_job(id="leasing", contract_type="employee_leasing")
        contracting = _make_job(id="contracting", contract_type="contracting")
        profile = _gated(contract_types=["employee_leasing", "permanent_position"])
        assert apply_hard_filter([leasing, contracting], profile) == [contracting]

    def test_work_below_the_remote_floor_never_reaches_evaluation(self):
        onsite = _make_job(id="onsite", remote_percentage=40, location="Berlin, Germany")
        remote = _make_job(id="remote", remote_percentage=100, location="Berlin, Germany")
        assert apply_hard_filter([onsite, remote], _gated(remote_floor=100)) == [remote]

    def test_leasing_only_prose_never_reaches_evaluation(self):
        """The gap this stage exists to close, asserted end to end.

        Both rows carry `contract_type="unknown"` — the adapter's documented
        fail-open, and the state every posting the source could not tag arrives in.
        The metadata gate passes both; only the prose separates them.
        """
        leasing = _make_job(
            id="leasing",
            description=f"{_CLEAN} Die Position wird ausschließlich ANÜ besetzt.",
        )
        clean = _make_job(id="clean", description=_CLEAN)
        assert leasing.contract_type == "unknown" and clean.contract_type == "unknown"
        assert apply_hard_filter([leasing, clean], _ARMED) == [clean]


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


# ---------------------------------------------------------------------------
# The filter stage is deterministic
#
# A static scan of `src/jobscout/filters/`, in the manner of
# tests/test_runtime_output_ascii.py, rather than a behavioural assertion that no
# request went out. Mocking a client proves only that the one path exercised did
# not call it; an import is what a call needs, and its absence is checkable for
# every path at once.
#
# This is a constraint from CLAUDE.md, not a preference: the hard filter runs over
# the whole ingested pool, before ranking has cut it to the top 20-30. An LLM call
# here is a cost multiplied by the pool size, and the ANUE classifier is the first
# stage in this package that reads prose at all — which is exactly the shape that
# invites one later.
# ---------------------------------------------------------------------------

class TestFilterStageMakesNoLLMCall:
    def test_the_filters_package_imports_no_model_client(self):
        import ast
        from pathlib import Path

        forbidden = ("anthropic", "jobscout.evaluation", "openai", "sentence_transformers")
        offences: list[str] = []

        package = Path(__file__).resolve().parent.parent / "src" / "jobscout" / "filters"
        modules = sorted(package.glob("*.py"))
        # Guards the guard: a mistyped path would glob nothing and pass silently.
        assert len(modules) >= 3

        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                offences += [
                    f"{path.name}: {n}"
                    for n in names
                    if any(n == f or n.startswith(f + ".") for f in forbidden)
                ]

        assert not offences, f"filter stage reaches a model: {offences}"
